from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.api.account_notes import get_account_notes_adapter
from backend.app.core.database import Base, get_db
from backend.app.core.security import create_access_token, encrypt_text
from backend.app.main import app
from backend.app.models import AccountCookieVersion, AccountNote, PlatformAccount, User
from backend.app.services.account_notes_service import normalize_account_note


@pytest.fixture
def workspace(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'notes.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add_all([User(id=1, username="notes-owner", password_hash="fixture"), User(id=2, username="other-owner", password_hash="fixture")])
        for account_id, owner, external_id, kind in [(1, 1, "own-a", "pc"), (2, 1, "own-a", "creator"), (3, 1, "own-b", "pc"), (4, 2, "own-a", "creator")]:
            db.add(PlatformAccount(id=account_id, user_id=owner, platform="xhs", sub_type=kind, external_user_id=external_id, nickname=f"Fixture {account_id}", status="active"))
            db.add(AccountCookieVersion(platform_account_id=account_id, encrypted_cookies=encrypt_text("a1=fixture")))
        db.commit()

    def database():
        with sessions() as db:
            yield db

    class Adapter:
        items = []
        fail = set()
        calls = []

        def fetch(self, source, cookies, external_id):
            self.calls.append((source, external_id))
            if source in self.fail:
                raise RuntimeError("fixture failure")
            return self.items

    adapter = Adapter()
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_account_notes_adapter] = lambda: adapter
    yield SimpleNamespace(client=TestClient(app), adapter=adapter, sessions=sessions,
                          owner={"Authorization": "Bearer " + create_access_token(1)},
                          other={"Authorization": "Bearer " + create_access_token(2)})
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_account_notes_adapter, None)
    engine.dispose()


def note(note_id="note-a", **values):
    return {"id": note_id, "display_title": "Fixture note", "type": "normal", "likes": 0,
            "view_count": 10, "collected_count": 2, "comments_count": 1, "shared_count": 0,
            "time": "2026-10-30 15:12", "images_list": [{"url": "https://example.test/cover.png"}], **values}


def sync(workspace, account=2, owner=None):
    return workspace.client.post(f"/api/xhs/account-notes/{account}/sync", headers=owner or workspace.owner)


def listed(workspace, account=2, **query):
    return workspace.client.get(f"/api/xhs/account-notes/{account}/notes", headers=workspace.owner, params=query).json()


def test_accounts_group_pc_and_creator_and_enforce_owner(workspace):
    w = workspace
    assert w.client.get("/api/xhs/account-notes/accounts").status_code == 401
    accounts = w.client.get("/api/xhs/account-notes/accounts", headers=w.owner).json()["items"]
    assert len(accounts) == 2
    assert accounts[0]["account_id"] == 2
    assert accounts[0]["account_types"] == ["creator", "pc"]
    assert accounts[0]["totals"]["views"] is None
    assert sync(w, 4).status_code == 404
    assert w.client.get("/api/xhs/account-notes/4/notes", headers=w.owner).status_code == 404
    w.adapter.items = [note()]
    assert sync(w).status_code == 200
    assert w.client.get("/api/xhs/account-notes/4/notes", headers=w.other).json()["total"] == 0
    assert w.adapter.calls == [("creator", "own-a")]


def test_sync_updates_without_duplicates_and_preserves_zero_and_missing_metrics(workspace):
    w = workspace
    w.adapter.items = [note(), note("note-b", view_count=None, likes=7, type="video")]
    assert sync(w).json()["synced_count"] == 2
    data = listed(w, 1, sort_by="views")  # PC alias reads the same logical account.
    assert data["total"] == 2
    assert data["items"][0]["likes"] == 0
    assert data["account"]["totals"]["views"] == 10
    assert data["account"]["metric_note_counts"]["views"] == 1
    w.adapter.items = [note(likes=3), note("note-b", view_count=0, likes=0)]
    assert sync(w, 1).status_code == 200
    assert listed(w)["total"] == 2
    assert listed(w)["account"]["totals"]["likes"] == 3


def test_failed_sync_keeps_previous_snapshot_and_records_failure(workspace):
    w = workspace
    w.adapter.items = [note()]
    assert sync(w).status_code == 200
    previous = listed(w)["items"]
    w.adapter.fail = {"creator", "pc"}
    assert sync(w).status_code == 502
    data = listed(w)
    assert data["items"] == previous
    assert data["account"]["sync_status"] == "failed"
    assert data["account"]["synced_at"] is not None


def test_creator_failure_falls_back_to_pc_without_clearing_private_notes_or_metrics(workspace):
    w = workspace
    w.adapter.items = [note(permission_msg="私密"), note("private-note")]
    assert sync(w).status_code == 200
    w.adapter.fail = {"creator"}
    w.adapter.items = [{"note_id": "note-a", "display_title": "PC title", "interact_info": {"liked_count": "0"}}]
    result = sync(w).json()
    assert result["account"]["sync_status"] == "partial"
    assert result["account"]["sync_source"] == "pc"
    data = listed(w)
    assert data["total"] == 2
    assert all(item["in_latest_sync"] for item in data["items"])
    original = next(item for item in data["items"] if item["note_id"] == "note-a")
    assert original["views"] == 10
    assert original["likes"] == 0
    assert original["platform_status"] == "私密"


def test_missing_notes_are_retained_and_empty_complete_snapshot_is_valid(workspace):
    w = workspace
    w.adapter.items = [note()]
    assert sync(w).status_code == 200
    w.adapter.items = []
    assert sync(w).status_code == 200
    data = listed(w, presence="missing")
    assert data["total"] == 1
    assert data["account"]["current_notes"] == 0
    assert data["account"]["totals"]["views"] is None
    assert listed(w, presence="current")["total"] == 0


def test_query_sort_search_and_pagination(workspace):
    w = workspace
    w.adapter.items = [note("a", display_title="100% design", likes=5), note("b", display_title="Video design", likes=9, type="video"), note("c", likes=0)]
    assert sync(w).status_code == 200
    assert listed(w, q="%", page_size=1)["total"] == 1
    assert listed(w, media_type="video")["items"][0]["note_id"] == "b"
    page = listed(w, sort_by="likes", page=2, page_size=1)
    assert page["total"] == 3
    assert page["items"][0]["note_id"] == "a"


def test_invalid_snapshot_does_not_overwrite_saved_notes(workspace):
    w = workspace
    w.adapter.items = [note()]
    assert sync(w).status_code == 200
    w.adapter.items = [{"title": "Missing id"}]
    assert sync(w).status_code == 502
    assert listed(w)["items"][0]["note_id"] == "note-a"


def test_concurrent_sync_returns_conflict_without_fetching(workspace, monkeypatch):
    import threading
    from backend.app.api import account_notes
    lock = threading.Lock()
    lock.acquire()
    monkeypatch.setattr(account_notes, "_locks", [lock] * 64)
    try:
        assert sync(workspace).status_code == 409
        assert not workspace.adapter.calls
    finally:
        lock.release()


def test_pc_only_account_does_not_fill_unavailable_statistics_with_zero(workspace):
    w = workspace
    w.adapter.items = [{"note_id": "public-note", "display_title": "Public note", "interact_info": {"liked_count": "2"}}]
    assert sync(w, 3).status_code == 200
    data = listed(w, 3)
    assert data["items"][0]["views"] is None
    assert data["account"]["totals"]["views"] is None
    assert data["account"]["totals"]["likes"] == 2


def test_normalizer_keeps_platform_text_and_does_not_invent_publication_status():
    item = normalize_account_note(note(permission_msg="审核中", tab_status=9, xsec_token="fixture link value"), "creator")
    assert item["platform_status"] == "审核中"
    assert item["published_at"].hour == 15
    assert "xsec_token=fixture+link+value" in item["note_url"]
    assert normalize_account_note(note(), "creator")["platform_status"] == ""
