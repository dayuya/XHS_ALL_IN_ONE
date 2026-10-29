import json
from types import SimpleNamespace

import pytest

from backend.app.adapters.xhs.pc_api_adapter import XhsPcApiAdapter
from backend.app.models import PlatformAccount
from backend.app.services.account_service import enrich_user_info_with_xhs_self_profile, merged_account_profile


@pytest.mark.parametrize("detail_result", ["success", "rejected", "exception"])
def test_self_profile_fetches_statistics_for_authenticated_user_and_closes_client(monkeypatch, detail_result):
    calls = []
    identity = {"success": True, "data": {"user_id": "fixture-self", "nickname": "Fixture"}}
    details = {"success": True, "data": {"basic_info": {}, "interactions": [{"type": "fans", "count": 0}]}}

    class Api:
        auth = SimpleNamespace(close=lambda: calls.append("closed"))

        def get_user_me(self):
            calls.append("identity")
            return True, "ok", identity

        def get_user_info(self, user_id):
            calls.append(user_id)
            if detail_result == "exception":
                raise RuntimeError("temporary failure")
            return detail_result == "success", "fixture", details

    monkeypatch.setattr(XhsPcApiAdapter, "_api", lambda self: Api())
    actual = XhsPcApiAdapter("fixture").get_self_info()
    assert actual == (details if detail_result == "success" else identity)
    assert calls == ["identity", "fixture-self", "closed"]


def test_self_profile_closes_client_when_identity_is_invalid(monkeypatch):
    closed = []
    api = SimpleNamespace(auth=SimpleNamespace(close=lambda: closed.append(True)), get_user_me=lambda: (False, "invalid", {}))
    monkeypatch.setattr(XhsPcApiAdapter, "_api", lambda self: api)
    with pytest.raises(RuntimeError, match="invalid"):
        XhsPcApiAdapter("fixture").get_self_info()
    assert closed == [True]


@pytest.mark.parametrize("wrapped", [True, False])
def test_profile_metrics_accept_sdk_envelope_or_data_and_keep_exact_zero_counts(wrapped):
    data = {
        "basic_info": {"nickname": "Fixture", "red_id": "fixture-red"},
        "interactions": [
            {"type": "fans", "count": 0, "i18n_count": "0"},
            {"type": "follows", "count": "12000", "i18n_count": "1.2万"},
            {"type": "interaction", "count": 45},
        ],
    }
    enriched = enrich_user_info_with_xhs_self_profile({}, {"data": data} if wrapped else data)
    assert enriched["profile"]["followers"] == 0
    assert enriched["profile"]["following"] == "12000"
    assert enriched["profile"]["likes"] == 45
    assert enriched["nickname"] == "Fixture"


def test_incomplete_refresh_keeps_previous_statistics_and_accepts_new_zero():
    account = PlatformAccount(profile_json=json.dumps({"followers": 12, "following": 8, "likes": 50}))
    profile = merged_account_profile(account, {"profile": {"followers": None, "following": "", "likes": 0}})
    assert profile == {"followers": 12, "following": 8, "likes": 0}
