from __future__ import annotations

import threading
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.adapters.xhs.account_notes_adapter import XhsAccountNotesAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text
from backend.app.core.time import shanghai_now
from backend.app.models import AccountCookieVersion, AccountNote, AccountNoteSync, PlatformAccount, User
from backend.app.schemas.common import paginated
from backend.app.services.account_notes_service import (
    account_groups, account_key, account_summary, normalize_account_note, serialize_note,
)
from backend.app.services.account_service import cookie_header_from_text

router = APIRouter(prefix="/xhs/account-notes", tags=["account-notes"])
_locks = [threading.Lock() for _ in range(64)]


def get_account_notes_adapter():
    return XhsAccountNotesAdapter()


def _owned_group(db: Session, user: User, account_id: int) -> list[PlatformAccount]:
    for group in account_groups(db, user.id):
        if any(account.id == account_id for account in group):
            return group
    raise HTTPException(404, "账号不存在")


@router.get("/accounts")
def list_note_accounts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {"items": [account_summary(db, group) for group in account_groups(db, user.id)]}


@router.get("/{account_id}/notes")
def list_account_notes(
    account_id: int, q: str = Query("", max_length=128),
    media_type: Literal["all", "image", "video"] = "all",
    presence: Literal["all", "current", "missing"] = "all",
    sort_by: Literal["published_at", "views", "likes", "collects", "comments", "shares"] = "published_at",
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    group = _owned_group(db, user, account_id)
    statement = select(AccountNote).where(AccountNote.user_id == user.id, AccountNote.account_key == account_key(group[0]))
    if q:
        statement = statement.where(AccountNote.title.contains(q, autoescape=True))
    if media_type != "all":
        statement = statement.where(AccountNote.media_type == media_type)
    if presence != "all":
        statement = statement.where(AccountNote.in_latest_sync == (presence == "current"))
    # Sorting NULLs with a separate boolean works with both SQLite and MySQL.
    column = getattr(AccountNote, sort_by)
    rows = db.scalars(statement.order_by(column.is_(None), column.desc(), AccountNote.id.desc())).all()
    return {**paginated([serialize_note(row) for row in rows], page, page_size), "account": account_summary(db, group)}


@router.post("/{account_id}/sync")
def sync_account_notes(
    account_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db),
    adapter=Depends(get_account_notes_adapter),
):
    group = _owned_group(db, user, account_id)
    key = account_key(group[0])
    lock = _locks[hash((user.id, key)) % len(_locks)]
    if not lock.acquire(blocking=False):
        raise HTTPException(409, "该账号正在同步，请稍后刷新。")
    try:
        state = db.scalar(select(AccountNoteSync).where(AccountNoteSync.user_id == user.id, AccountNoteSync.account_key == key))
        if state is None:
            state = AccountNoteSync(user_id=user.id, account_key=key)
            db.add(state)
        state.status = "syncing"
        state.last_attempt_at = shanghai_now()
        db.commit()
        normalized = None
        source = ""
        for account in group:
            version = db.scalar(select(AccountCookieVersion).where(AccountCookieVersion.platform_account_id == account.id)
                                .order_by(AccountCookieVersion.created_at.desc(), AccountCookieVersion.id.desc()).limit(1))
            if not version or not account.external_user_id:
                continue
            try:
                result = adapter.fetch(account.sub_type, cookie_header_from_text(decrypt_text(version.encrypted_cookies)), account.external_user_id)
                if not isinstance(result, list):
                    raise ValueError("Invalid note snapshot")
                # Validate the whole snapshot before changing any saved notes.
                normalized = {item["note_id"]: item for raw in result if (item := normalize_account_note(raw, account.sub_type))}
                source = account.sub_type
                break
            except Exception:
                continue
        if normalized is None:
            state.status = "failed"
            state.message = "同步失败，已保留上次数据。请在账号矩阵检查登录后重试。"
            db.commit()
            raise HTTPException(502, state.message)

        now = shanghai_now()
        existing = {row.note_id: row for row in db.scalars(select(AccountNote).where(
            AccountNote.user_id == user.id, AccountNote.account_key == key,
        )).all()}
        if source == "creator":
            for row in existing.values():
                row.in_latest_sync = False
        for note_id, values in normalized.items():
            row = existing.get(note_id)
            if row is None:
                row = AccountNote(user_id=user.id, account_key=key, note_id=note_id)
                db.add(row)
            for field, value in values.items():
                if value is not None and (value != "" or (field == "platform_status" and source == "creator")):
                    setattr(row, field, value)
            row.in_latest_sync = True
            row.synced_at = now
        state.status = "success" if source == "creator" or not any(a.sub_type == "creator" for a in group) else "partial"
        state.source = source
        state.message = "同步完成" if source == "creator" else "本次PC同步仅更新主页可见笔记，其余记录和未返回指标保留上次数据；缺失记录不代表已删除。"
        state.synced_at = now
        db.commit()
        return {"synced_count": len(normalized), "account": account_summary(db, group)}
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        try:
            state = db.scalar(select(AccountNoteSync).where(AccountNoteSync.user_id == user.id, AccountNoteSync.account_key == key))
            if state:
                state.status = "failed"
                state.message = "保存同步结果失败，已保留上次数据，请稍后重试。"
                db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(500, "保存同步结果失败，请稍后重试。")
    finally:
        lock.release()
