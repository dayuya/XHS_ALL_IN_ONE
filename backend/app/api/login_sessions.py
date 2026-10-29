from __future__ import annotations

import base64
import io
import json
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter
from backend.app.adapters.xhs.pc_login_adapter import XhsPcLoginAdapter
from backend.app.core.database import get_db
from backend.app.core.deps import get_current_user
from backend.app.core.security import decrypt_text, encrypt_text
from backend.app.models import AccountCookieVersion, LoginSession, PlatformAccount, User
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.services.account_service import (
    cookie_header_from_text,
    decode_cookie_text,
    enrich_user_info_with_xhs_self_profile,
    serialize_account,
    upsert_platform_account_from_login,
)

router = APIRouter(prefix="/xhs/login-sessions", tags=["xhs-login-sessions"])
_poll_locks = tuple(Lock() for _ in range(64))
CREATOR_SYNC_WARNING = "PC 账号已绑定，Creator 自动同步未成功。可切换 Creator，单独扫码登录创作者平台。"


class PcQrCodeRequest(BaseModel):
    sync_creator: bool = False


class PhoneSendCodeRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    sync_creator: bool = False


class PhoneConfirmRequest(BaseModel):
    session_id: int
    phone: str = Field(min_length=6, max_length=32)
    code: str = Field(min_length=4, max_length=12)
    sync_creator: bool | None = None


def _dump_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _load_json(value: str | None) -> dict:
    if not value:
        return {}
    return json.loads(value)


def _dump_temp_state(cookies: dict, *, sync_creator: bool = False) -> str:
    if sync_creator:
        return _dump_json({"cookies": cookies, "sync_creator": True})
    return _dump_json(cookies)


def _load_temp_state(value: str | None) -> tuple[dict, bool]:
    payload = _load_json(value)
    if isinstance(payload, dict) and isinstance(payload.get("cookies"), dict):
        return payload["cookies"], bool(payload.get("sync_creator"))
    if isinstance(payload, dict):
        return payload, False
    return {}, False


def _qr_data_url(qr_url: str) -> str:
    import qrcode

    image = qrcode.make(qr_url)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def get_pc_login_adapter() -> XhsPcLoginAdapter:
    return XhsPcLoginAdapter()


def get_creator_login_adapter() -> XhsCreatorLoginAdapter:
    return XhsCreatorLoginAdapter()


def _mask_phone(phone: str) -> str:
    if len(phone) <= 7:
        return f"{phone[:2]}****"
    return f"{phone[:3]}****{phone[-4:]}"


def _sync_creator_account_from_pc_login(
    *,
    db: Session,
    user_id: int,
    pc_cookies: dict,
    creator_adapter: XhsCreatorLoginAdapter,
) -> dict | None:
    try:
        creator_result = creator_adapter.exchange_from_user_cookies(pc_cookies)
        creator_user_info = creator_adapter.get_user_info(creator_result["cookies"])
        with db.begin_nested():
            creator_account, creator_action = _create_account_from_login(
                db=db,
                user_id=user_id,
                sub_type="creator",
                user_info=creator_user_info,
                cookies=creator_result["cookies"],
            )
    except Exception:
        return None
    return serialize_account(creator_account, creator_action)


def _confirmed_response(session: LoginSession, db: Session) -> dict:
    state = _load_json(decrypt_text(session.encrypted_temp_cookies))
    saved = state.get("login_result", {})
    account = db.get(PlatformAccount, saved["account_id"]) if saved.get("account_id") else None
    creator = db.get(PlatformAccount, saved["creator_account_id"]) if saved.get("creator_account_id") else None
    cookies, sync_creator = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
    if account is None and not saved:
        # Recover sessions created before result caching without remote calls.
        identity_key = "web_session" if session.sub_type == "pc" else "customer_session"
        identity = cookies.get(identity_key)
        if identity:
            versions = db.execute(
                select(PlatformAccount, AccountCookieVersion)
                .join(AccountCookieVersion, AccountCookieVersion.platform_account_id == PlatformAccount.id)
                .where(PlatformAccount.user_id == session.user_id, PlatformAccount.sub_type == session.sub_type)
                .order_by(AccountCookieVersion.id.desc())
            )
            for candidate, version in versions:
                values = decode_cookie_text(decrypt_text(version.encrypted_cookies))
                if values.get(identity_key) == identity:
                    account = candidate
                    break
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "account": serialize_account(account) if account and account.user_id == session.user_id else None,
        "creator_account": serialize_account(creator) if creator and creator.user_id == session.user_id else None,
        "creator_sync_warning": saved.get("creator_sync_warning") or (
            CREATOR_SYNC_WARNING if session.sub_type == "pc" and sync_creator and not creator else None
        ),
    }


def _create_account_from_login(
    *,
    db: Session,
    user_id: int,
    sub_type: str,
    user_info: dict,
    cookies: dict,
) -> tuple[PlatformAccount, str]:
    cookies_text = _dump_json(cookies)
    if sub_type == "pc":
        try:
            self_profile = XhsPcApiAdapter(cookie_header_from_text(cookies_text)).get_self_info()
            user_info = enrich_user_info_with_xhs_self_profile(user_info, self_profile)
        except Exception:
            pass
    return upsert_platform_account_from_login(
        db=db,
        user_id=user_id,
        platform="xhs",
        sub_type=sub_type,
        user_info=user_info,
        cookies_text=cookies_text,
    )


@router.post("/pc/qrcode")
def pc_qrcode(
    payload: PcQrCodeRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    payload = payload or PcQrCodeRequest()
    try:
        qr_payload = adapter.create_qrcode()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"XHS PC QR code generation failed: {exc}",
        ) from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        status="pending",
        qr_id=qr_payload["qr_id"],
        code=qr_payload["code"],
        qr_url=qr_payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(qr_payload["cookies"], sync_creator=payload.sync_creator)
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


@router.post("/creator/qrcode")
def creator_qrcode(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        payload = adapter.create_qrcode()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"XHS Creator QR code generation failed: {exc}",
        ) from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        status="pending",
        qr_id=payload["qr_id"],
        qr_url=payload["qr_url"],
        encrypted_temp_cookies=encrypt_text(_dump_json(payload["cookies"])),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "qr_image_data_url": _qr_data_url(session.qr_url or ""),
    }


@router.get("/{session_id}")
def login_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    pc_adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    # Coalesce confirmation requests in this single-process local deployment.
    with _poll_locks[session_id % len(_poll_locks)]:
        return _poll_login_session(session_id, current_user, db, pc_adapter, creator_adapter)


def _poll_login_session(session_id, current_user, db, pc_adapter, creator_adapter):
    session = db.get(LoginSession, session_id)
    if session is None or session.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    if session.status == "confirmed":
        return _confirmed_response(session, db)
    if session.status == "expired":
        return {"session_id": session.id, "status": session.status, "qr_url": session.qr_url}
    if session.sub_type not in {"pc", "creator"} or not session.qr_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported login session")

    cookies, sync_creator = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
    try:
        if session.sub_type == "pc":
            if not session.code:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported login session")
            result = pc_adapter.check_qrcode_status(session.qr_id, session.code, cookies)
            account_sub_type = "pc"
            user_info = pc_adapter.get_user_info(result["cookies"]) if result["status"] == "confirmed" else None
        else:
            result = creator_adapter.check_qrcode_status(session.qr_id, cookies)
            account_sub_type = "creator"
            user_info = creator_adapter.get_user_info(result["cookies"]) if result["status"] == "confirmed" else None
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail="小红书登录状态检查暂时失败，请稍后重试；二维码过期后请刷新。") from exc
    session.status = result["status"]
    session.encrypted_temp_cookies = encrypt_text(
        _dump_temp_state(result["cookies"], sync_creator=sync_creator)
    )

    account_payload = None
    creator_account_payload = None
    if session.status == "confirmed":
        account, action = _create_account_from_login(
            db=db,
            user_id=current_user.id,
            sub_type=account_sub_type,
            user_info=user_info,
            cookies=result["cookies"],
        )
        account_payload = serialize_account(account, action)
        if account_sub_type == "pc" and sync_creator:
            creator_account_payload = _sync_creator_account_from_pc_login(
                db=db,
                user_id=current_user.id,
                pc_cookies=result["cookies"],
                creator_adapter=creator_adapter,
            )

    warning = CREATOR_SYNC_WARNING if account_sub_type == "pc" and sync_creator and session.status == "confirmed" and not creator_account_payload else None
    if account_payload:
        session.encrypted_temp_cookies = encrypt_text(_dump_json({
            "cookies": result["cookies"],
            "sync_creator": sync_creator,
            "login_result": {
                "account_id": account_payload["id"],
                "creator_account_id": creator_account_payload["id"] if creator_account_payload else None,
                "creator_sync_warning": warning,
            },
        }))
    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "qr_url": session.qr_url,
        "account": account_payload,
        "creator_account": creator_account_payload,
        "creator_sync_warning": warning,
    }


@router.post("/pc/phone/send-code")
def pc_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to send phone code") from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="pc",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(
            _dump_temp_state(result["cookies"], sync_creator=payload.sync_creator)
        ),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/pc/phone/confirm")
def pc_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsPcLoginAdapter = Depends(get_pc_login_adapter),
    creator_adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "pc", creator_adapter)


@router.post("/creator/phone/send-code")
def creator_phone_send_code(
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    try:
        result = adapter.create_phone_session(payload.phone)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to send phone code") from exc
    session = LoginSession(
        user_id=current_user.id,
        platform="xhs",
        sub_type="creator",
        login_method="phone",
        phone_mask=_mask_phone(payload.phone),
        status="pending",
        encrypted_temp_cookies=encrypt_text(_dump_json(result["cookies"])),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": session.id, "status": session.status, "message": result.get("message", "sent")}


@router.post("/creator/phone/confirm")
def creator_phone_confirm(
    payload: PhoneConfirmRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    adapter: XhsCreatorLoginAdapter = Depends(get_creator_login_adapter),
):
    return _confirm_phone_login(payload, current_user, db, adapter, "creator", None)


def _confirm_phone_login(
    payload: PhoneConfirmRequest,
    current_user: User,
    db: Session,
    adapter,
    sub_type: str,
    creator_adapter: XhsCreatorLoginAdapter | None,
):
    session = db.get(LoginSession, payload.session_id)
    if (
        session is None
        or session.user_id != current_user.id
        or session.sub_type != sub_type
        or session.login_method != "phone"
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Login session not found")
    try:
        cookies, stored_sync_creator = _load_temp_state(decrypt_text(session.encrypted_temp_cookies))
        result = adapter.confirm_phone_login(payload.phone, payload.code, cookies)
        user_info = adapter.get_user_info(result["cookies"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Phone login failed") from exc

    sync_creator = payload.sync_creator if payload.sync_creator is not None else stored_sync_creator
    session.status = "confirmed"
    session.encrypted_temp_cookies = encrypt_text(
        _dump_temp_state(result["cookies"], sync_creator=sync_creator)
    )
    account, action = _create_account_from_login(
        db=db,
        user_id=current_user.id,
        sub_type=sub_type,
        user_info=user_info,
        cookies=result["cookies"],
    )
    creator_account_payload = None
    if sub_type == "pc" and creator_adapter is not None and sync_creator:
        creator_account_payload = _sync_creator_account_from_pc_login(
            db=db,
            user_id=current_user.id,
            pc_cookies=result["cookies"],
            creator_adapter=creator_adapter,
        )
    db.commit()
    return {
        "session_id": session.id,
        "status": session.status,
        "account": serialize_account(account, action),
        "creator_account": creator_account_payload,
    }
