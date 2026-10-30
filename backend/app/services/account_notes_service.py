from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.time import SHANGHAI_TZ
from backend.app.models import AccountNote, AccountNoteSync, PlatformAccount

METRICS = ("views", "likes", "collects", "comments", "shares")


def account_key(account: PlatformAccount) -> str:
    return account.external_user_id or f"local:{account.id}"


def account_groups(db: Session, user_id: int) -> list[list[PlatformAccount]]:
    groups: dict[str, list[PlatformAccount]] = {}
    accounts = db.scalars(select(PlatformAccount).where(
        PlatformAccount.user_id == user_id, PlatformAccount.platform == "xhs",
        PlatformAccount.sub_type.in_(["pc", "creator"]),
    ).order_by(PlatformAccount.id)).all()
    for account in accounts:
        groups.setdefault(account_key(account), []).append(account)
    return [sorted(group, key=lambda a: (a.sub_type != "creator", a.status != "active", a.id)) for group in groups.values()]


def metric(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace(",", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(万|亿|[wWkK])?", text)
    if not match:
        return None
    factor = {"万": 10000, "亿": 100000000, "w": 10000, "k": 1000}.get((match[2] or "").lower(), 1)
    return int(float(match[1]) * factor)


def _first(*values):
    return next((value for value in values if value is not None and value != ""), None)


def _image(value: Any) -> str:
    if isinstance(value, str):
        return value if value.startswith(("https://", "http://")) else ""
    if isinstance(value, list):
        return next((url for item in value if (url := _image(item))), "")
    if isinstance(value, dict):
        return next((url for key in ("url_default", "url", "url_pre", "info_list") if (url := _image(value.get(key)))), "")
    return ""


def _date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (float, int)) or str(value).isdigit():
            stamp = float(value)
            if stamp <= 0:
                return None
            return datetime.fromtimestamp(stamp / 1000 if stamp > 100000000000 else stamp, SHANGHAI_TZ).replace(tzinfo=None)
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(SHANGHAI_TZ).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, OverflowError, OSError):
        return None


def normalize_account_note(item: dict, source: str) -> dict:
    card = item.get("note_card") if isinstance(item.get("note_card"), dict) else item
    note_id = str(_first(card.get("note_id"), card.get("id"), item.get("note_id"), item.get("id")) or "")
    if not note_id or len(note_id) > 128:
        raise ValueError("笔记缺少有效标识，已保留上次同步数据。")
    interact = card.get("interact_info") if isinstance(card.get("interact_info"), dict) else {}
    aliases = {
        "views": ("view_count", "views", "read_count"),
        "likes": ("likes", "liked_count", "like_count"),
        "collects": ("collected_count", "collect_count", "collects"),
        "comments": ("comments_count", "comment_count", "comments"),
        "shares": ("shared_count", "share_count", "shares"),
    }
    values = {key: metric(_first(*(obj.get(alias) for obj in (card, interact) for alias in keys))) for key, keys in aliases.items()}
    query = {}
    for key in ("xsec_token", "xsec_source"):
        if value := _first(card.get(key), item.get(key)):
            query[key] = str(value)
    url = "https://www.xiaohongshu.com/explore/" + quote(note_id, safe="")
    if query:
        url += "?" + urlencode(query)
    status = _first(card.get("permission_msg"), card.get("status_desc"), card.get("status_text"))
    if not isinstance(status, str):
        status = ""
    if metric(card.get("schedule_post_time")):
        status = status or "定时发布"
    return {
        "note_id": note_id,
        "title": str(_first(card.get("display_title"), card.get("title"), card.get("desc")) or "无标题笔记")[:512],
        "cover_url": _image(_first(card.get("cover"), card.get("images_list"), card.get("image_list"))),
        "note_url": url,
        "media_type": "video" if card.get("type") == "video" else "image",
        "platform_status": status[:256],
        "platform_status_code": str(card["tab_status"])[:32] if card.get("tab_status") is not None else None,
        "published_at": _date(_first(card.get("time"), card.get("publish_time"), card.get("create_time"))),
        "source": source,
        **values,
    }


def serialize_note(note: AccountNote) -> dict:
    fields = ("id", "note_id", "title", "cover_url", "note_url", "media_type", "platform_status",
              "platform_status_code", "source", "in_latest_sync", *METRICS)
    return {
        **{field: getattr(note, field) for field in fields},
        "published_at": note.published_at.isoformat() if note.published_at else None,
        "synced_at": note.synced_at.isoformat(),
    }


def account_summary(db: Session, group: list[PlatformAccount]) -> dict:
    account = group[0]
    key = account_key(account)
    rows = db.scalars(select(AccountNote).where(AccountNote.user_id == account.user_id, AccountNote.account_key == key)).all()
    state = db.scalar(select(AccountNoteSync).where(AccountNoteSync.user_id == account.user_id, AccountNoteSync.account_key == key))
    current = [row for row in rows if row.in_latest_sync]
    totals = {key: sum(values) if (values := [getattr(row, key) for row in current if getattr(row, key) is not None]) else None for key in METRICS}
    known_counts = {key: sum(getattr(row, key) is not None for row in current) for key in METRICS}
    return {
        "account_id": account.id, "nickname": account.nickname, "avatar_url": account.avatar_url,
        "account_types": sorted({row.sub_type for row in group}),
        "login_status": "active" if any(row.status == "active" for row in group) else account.status,
        "total_notes": len(rows), "current_notes": len(current), "missing_notes": len(rows) - len(current),
        "totals": totals, "metric_note_counts": known_counts,
        "sync_status": state.status if state else "never", "sync_source": state.source if state else "",
        "sync_message": state.message if state else "尚未同步笔记",
        "last_attempt_at": state.last_attempt_at.isoformat() if state and state.last_attempt_at else None,
        "synced_at": state.synced_at.isoformat() if state and state.synced_at else None,
    }
