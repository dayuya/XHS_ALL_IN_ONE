from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from time import monotonic, sleep
from typing import Any, ClassVar

from backend.app.adapters.xhs.request_env import direct_xhs_request_env


class XhsCreatorLoginAdapter:
    QR_SESSION_TTL_SECONDS = 240
    QR_SESSION_LIMIT = 64
    QR_CREATE_ATTEMPTS = 3
    _qr_sessions: ClassVar[OrderedDict[str, tuple[float, Any]]] = OrderedDict()
    _qr_sessions_lock = Lock()

    def __init__(self):
        self._confirmed_api = None

    @classmethod
    def _prune_qr_sessions(cls):
        now = monotonic()
        for key, (expires, api) in list(cls._qr_sessions.items()):
            if expires <= now:
                cls._qr_sessions.pop(key)
                api.close()

    @classmethod
    def _remember_qr_session(cls, qr_id, api):
        with cls._qr_sessions_lock:
            cls._prune_qr_sessions()
            while len(cls._qr_sessions) >= cls.QR_SESSION_LIMIT:
                _, (_, oldest) = cls._qr_sessions.popitem(last=False)
                oldest.close()
            cls._qr_sessions[qr_id] = (monotonic() + cls.QR_SESSION_TTL_SECONDS, api)

    @classmethod
    def _get_qr_session(cls, qr_id):
        with cls._qr_sessions_lock:
            cls._prune_qr_sessions()
            entry = cls._qr_sessions.get(qr_id)
            return entry[1] if entry else None

    @classmethod
    def _forget_qr_session(cls, qr_id):
        with cls._qr_sessions_lock:
            cls._qr_sessions.pop(qr_id, None)

    def exchange_from_user_cookies(self, user_cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_creator_login_apis import XHSCreatorLoginApi

            api = XHSCreatorLoginApi()
            success, message, payload = api.exchange_creator_session_from_user_cookies(dict(user_cookies))
        if not success or not payload:
            raise RuntimeError(message)
        return {"status": "confirmed", "cookies": payload["cookies"]}

    def create_qrcode(self) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_creator_login_apis import XHSCreatorLoginApi

            api = XHSCreatorLoginApi()
            retained = False
            try:
                for attempt in range(self.QR_CREATE_ATTEMPTS):
                    # Match the SDK's full login lifecycle, including the CAS
                    # probe and security initialization before requesting QR.
                    api._prepare_login_session()
                    api._complete_security()
                    success, message, payload = api.generate_qrcode(api.profile.cookie_map)
                    if success and payload:
                        self._remember_qr_session(payload["qr_id"], api)
                        retained = True
                        return {
                            "cookies": payload["cookies"],
                            "qr_id": payload["qr_id"],
                            "qr_url": payload["qr_url"],
                        }
                    if "HTTP 406" not in message or attempt + 1 == self.QR_CREATE_ATTEMPTS:
                        raise RuntimeError(message)
                    api._reset_anonymous_session()
                    sleep(0.5 * (attempt + 1))
            finally:
                if not retained:
                    api.close()

    def check_qrcode_status(self, qr_id: str, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env():
            # Reuse the original device profile, host-scoped cookies and HTTP
            # session. Rebuilding them on every poll invalidates the QR flow.
            api = self._get_qr_session(qr_id)
            if api is None:
                return {"status": "expired", "cookies": cookies}
            success, message, updated_cookies = api.check_qrcode_status(qr_id, cookies)
            status = "pending"
            if success:
                status = "confirmed"
                self._forget_qr_session(qr_id)
                self._confirmed_api = api
            elif "过期" in message or "expired" in message.lower():
                status = "expired"
                self._forget_qr_session(qr_id)
                api.close()
            elif "确认" in message or "confirm" in message.lower():
                status = "scanned"
        return {"status": status, "cookies": updated_cookies}

    def get_user_info(self, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_creator_login_apis import XHSCreatorLoginApi

            api = self._confirmed_api or XHSCreatorLoginApi()
            try:
                success, data, _ = api.get_user_info(cookies)
            finally:
                api.close()
                self._confirmed_api = None
        if not success:
            raise RuntimeError("Failed to fetch XHS Creator user info")
        return {
            "external_user_id": data.get("userId", ""),
            "nickname": data.get("userName", ""),
            "avatar_url": data.get("userAvatar", ""),
            "profile": {
                "red_id": data.get("redId") or data.get("red_id") or "",
                "role": data.get("role") or "",
                "real_name_verified": data.get("realNameVerified"),
                "followers": data.get("fans") or data.get("followers") or data.get("followerCount"),
                "following": data.get("follows") or data.get("following") or data.get("followingCount"),
                "likes": data.get("likedCount") or data.get("likes") or data.get("likeCount"),
                "raw": data,
            },
        }

    def create_phone_session(self, phone: str) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_creator_login_apis import XHSCreatorLoginApi

            api = XHSCreatorLoginApi()
            cookies = api.generate_init_cookies()
            success, message, _ = api.send_phone_code(phone, cookies)
        if not success:
            raise RuntimeError(message)
        return {"cookies": cookies, "message": message or "sent"}

    def confirm_phone_login(self, phone: str, code: str, cookies: dict[str, Any]) -> dict[str, Any]:
        with direct_xhs_request_env():
            from apis.xhs_creator_login_apis import XHSCreatorLoginApi

            api = XHSCreatorLoginApi()
            success, message, payload = api.login_by_phone(phone, code, cookies)
        if not success or not payload:
            raise RuntimeError(message)
        return {"status": "confirmed", "cookies": payload["cookies"]}
