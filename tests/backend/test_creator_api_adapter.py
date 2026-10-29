from types import SimpleNamespace

import pytest

from backend.app.adapters.xhs.creator_api_adapter import XhsCreatorApiAdapter


def test_upload_permission_uses_authenticated_client_and_no_cookie_proxy_argument(monkeypatch):
    from apis import xhs_creator_apis
    from xhs_utils.xhs_creator import XHSCreatorAuth

    calls = []
    auth = SimpleNamespace(close=lambda: calls.append("closed"))

    def from_cookie(value):
        assert value == "fixture-creator-login"
        return auth

    class FakeApi:
        def __init__(self, provided_auth):
            assert provided_auth is auth
            self.auth = provided_auth

        def get_file_ids(self, media_type):
            assert media_type == "image"
            calls.append("checked")
            return True, "ok", ({"success": True}, "fixture-time")

    monkeypatch.setattr(XHSCreatorAuth, "from_cookie", from_cookie)
    monkeypatch.setattr(xhs_creator_apis, "XHS_Creator_Apis", FakeApi)
    assert XhsCreatorApiAdapter("fixture-creator-login").check_upload_permission() == (True, "ok")
    assert calls == ["checked", "closed"]


def test_upload_permission_closes_auth_on_request_failure(monkeypatch):
    calls = []

    class FakeApi:
        auth = SimpleNamespace(close=lambda: calls.append("closed"))

        def get_file_ids(self, media_type):
            raise RuntimeError("temporary request failure")

    monkeypatch.setattr(XhsCreatorApiAdapter, "_api", lambda self: FakeApi())
    with pytest.raises(RuntimeError, match="temporary request failure"):
        XhsCreatorApiAdapter("fixture").check_upload_permission()
    assert calls == ["closed"]


def test_upload_reads_encoded_nested_media_url_without_uploading(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import quote
    from backend.app.core import config

    image = tmp_path / "media" / "示例图" / "cover #1.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fixture-image")
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(storage_dir=tmp_path))
    url = "/api/files/media/" + quote(image.relative_to(tmp_path / "media").as_posix(), safe="/")
    assert XhsCreatorApiAdapter._resolve_file_data(url) == b"fixture-image"
