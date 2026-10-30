from types import SimpleNamespace

import pytest

from backend.app.adapters.xhs.account_notes_adapter import AccountNotesFetchError, XhsAccountNotesAdapter
from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter
from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter


@pytest.fixture
def sdk(monkeypatch):
    class Api:
        calls = []
        pages = []
        closed = False

        def __init__(self):
            self.auth = SimpleNamespace(close=lambda: setattr(self, "closed", True))

        def get_posted_notes_page(self, page, tab):
            self.calls.append(page)
            return self.pages.pop(0)

        def get_user_note_info(self, user_id, cursor):
            self.calls.append((user_id, cursor))
            return self.pages.pop(0)

    api = Api()
    monkeypatch.setattr(XhsCreatorApiAdapter, "_api", lambda self: api)
    monkeypatch.setattr(XhsPcApiAdapter, "_api", lambda self: api)
    monkeypatch.setattr("backend.app.adapters.xhs.account_notes_adapter.time.sleep", lambda _: None)
    return api


def test_creator_pagination_uses_server_cursor_and_returns_full_list(sdk):
    sdk.pages = [(True, "ok", {"data": {"notes": [{"id": "a"}], "page": 7}}),
                 (True, "ok", {"data": {"notes": [{"id": "b"}], "page": -1}})]
    assert len(XhsAccountNotesAdapter().fetch("creator", "fixture", "self")) == 2
    assert sdk.calls == [0, 7]
    assert sdk.closed


@pytest.mark.parametrize("failure", ["repeated", "partial", "missing-page", "count-mismatch", "invalid-items"])
def test_creator_incomplete_snapshots_fail_instead_of_clearing_saved_notes(sdk, failure):
    data = {"notes": [{"id": "a"}], "page": 0}
    if failure == "partial":
        data["page"] = 1
        sdk.pages = [(True, "ok", {"data": data}), (False, "failed", {})]
    else:
        if failure == "missing-page":
            data.pop("page")
        elif failure == "count-mismatch":
            data.update(page=-1, tags=[{"id": "special.note_time_desc", "notes_count": 2}])
        elif failure == "invalid-items":
            data.update(notes=[None], page=-1)
        sdk.pages = [(True, "ok", {"data": data})]
    with pytest.raises(AccountNotesFetchError):
        XhsAccountNotesAdapter().fetch("creator", "fixture", "self")
    assert sdk.closed


def test_pc_pagination_retains_account_identity(sdk):
    sdk.pages = [(True, "ok", {"data": {"notes": [{"id": "a"}], "cursor": "next", "has_more": True}}),
                 (True, "ok", {"data": {"notes": [], "cursor": "end", "has_more": False}})]
    assert XhsAccountNotesAdapter().fetch("pc", "fixture", "own-user") == [{"id": "a"}]
    assert sdk.calls == [("own-user", ""), ("own-user", "next")]
    assert sdk.closed
