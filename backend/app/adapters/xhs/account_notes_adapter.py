from __future__ import annotations

import time
from typing import Any

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.adapters.xhs.request_env import direct_xhs_request_env


class AccountNotesFetchError(RuntimeError):
    pass


class XhsAccountNotesAdapter:
    """Read complete snapshots, detecting partial/looping pagination."""

    max_pages = 200
    max_seconds = 90

    def fetch(self, source: str, cookies: str, external_user_id: str) -> list[dict[str, Any]]:
        started = time.monotonic()
        with direct_xhs_request_env():
            api = (XhsCreatorApiAdapter(cookies) if source == "creator" else XhsPcApiAdapter(cookies))._api()
            try:
                cursor: Any = 0 if source == "creator" else ""
                seen = set()
                notes = []
                expected_total = None
                for _ in range(self.max_pages):
                    if cursor in seen or time.monotonic() - started > self.max_seconds:
                        raise AccountNotesFetchError("分页未完成，已保留上次同步数据。")
                    seen.add(cursor)
                    if source == "creator":
                        success, _, payload = api.get_posted_notes_page(page=cursor, tab=0)
                    else:
                        success, _, payload = api.get_user_note_info(external_user_id, cursor)
                    if not success or not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
                        raise AccountNotesFetchError("笔记接口暂不可用，请检查账号登录后重试。")
                    data = payload["data"]
                    batch = data.get("notes")
                    if not isinstance(batch, list) or any(not isinstance(item, dict) for item in batch):
                        raise AccountNotesFetchError("笔记接口返回格式异常，已保留上次同步数据。")
                    notes.extend(batch)
                    if source == "creator":
                        if expected_total is None:
                            for tag in data.get("tags") or []:
                                if isinstance(tag, dict) and tag.get("id") == "special.note_time_desc":
                                    value = tag.get("notes_count")
                                    if isinstance(value, int):
                                        expected_total = value
                        try:
                            cursor = int(data["page"])
                        except (KeyError, TypeError, ValueError):
                            raise AccountNotesFetchError("分页信息异常，已保留上次同步数据。")
                        complete = cursor == -1
                    else:
                        if "has_more" not in data:
                            raise AccountNotesFetchError("分页信息异常，已保留上次同步数据。")
                        complete = not data["has_more"]
                        cursor = str(data.get("cursor", ""))
                    if complete:
                        unique_count = len({str(item.get("id") or item.get("note_id") or "") for item in notes})
                        if expected_total is not None and unique_count < expected_total:
                            raise AccountNotesFetchError("同步数量少于平台总数，已保留上次同步数据。")
                        return notes
                    if not batch:
                        raise AccountNotesFetchError("分页数据不完整，已保留上次同步数据。")
                    time.sleep(0.15)
                raise AccountNotesFetchError("超过本次同步页数限制，已保留上次同步数据。")
            finally:
                api.auth.close()
