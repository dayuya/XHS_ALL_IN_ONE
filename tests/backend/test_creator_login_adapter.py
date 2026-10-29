from collections import OrderedDict
from types import SimpleNamespace

import pytest

from backend.app.adapters.xhs import creator_login_adapter as adapter_module
from backend.app.adapters.xhs.creator_login_adapter import XhsCreatorLoginAdapter


@pytest.fixture
def sdk(monkeypatch):
    from apis import xhs_creator_login_apis

    class FakeSdk:
        instances = []
        responses = [None]
        prepare_error = False

        def __init__(self):
            self.profile = SimpleNamespace(cookie_map={"a1": "fixture-device"})
            self.generation = 0
            self.generated_with = []
            self.prepared = False
            self.secured = False
            self.closed = 0
            self.polls = 0
            self.confirmed = False
            self.results = list(type(self).responses)
            self.qr_id = f"fixture-qr-{len(self.instances)}"
            self.instances.append(self)

        def _prepare_login_session(self):
            if type(self).prepare_error:
                raise RuntimeError("initialization failed")
            self.prepared = True
            return self.profile.cookie_map, {"active": False}

        def _complete_security(self):
            assert self.prepared
            self.secured = True

        def generate_qrcode(self, cookies):
            assert self.prepared and self.secured
            self.generated_with.append(self.generation)
            message = self.results.pop(0)
            if message:
                return False, message, None
            return True, "OK", {
                "qr_id": self.qr_id,
                "qr_url": "https://example.test/qr",
                "cookies": cookies,
            }

        def _reset_anonymous_session(self):
            self.generation += 1
            self.prepared = False
            self.secured = False

        def check_qrcode_status(self, qr_id, cookies):
            assert self.secured and qr_id == self.qr_id
            self.polls += 1
            return self.confirmed, "confirmed" if self.confirmed else "请扫描二维码", cookies

        def get_user_info(self, cookies):
            assert self.confirmed and not self.closed
            return True, {"userId": "fixture-user", "userName": "fixture"}, cookies

        def close(self):
            self.closed += 1

    clock = {"now": 1000.0}
    monkeypatch.setattr(xhs_creator_login_apis, "XHSCreatorLoginApi", FakeSdk)
    monkeypatch.setattr(XhsCreatorLoginAdapter, "_qr_sessions", OrderedDict())
    monkeypatch.setattr(adapter_module, "sleep", lambda seconds: None)
    monkeypatch.setattr(adapter_module, "monotonic", lambda: clock["now"])
    yield FakeSdk, clock
    for _, api in list(XhsCreatorLoginAdapter._qr_sessions.values()):
        api.close()


def test_creator_qr_preserves_initialized_device_across_requests(sdk):
    factory, _ = sdk
    created = XhsCreatorLoginAdapter().create_qrcode()
    poll_request = XhsCreatorLoginAdapter()
    result = poll_request.check_qrcode_status(created["qr_id"], created["cookies"])
    assert result["status"] == "pending"
    assert len(factory.instances) == 1
    live_api = factory.instances[0]
    live_api.confirmed = True
    result = poll_request.check_qrcode_status(created["qr_id"], created["cookies"])
    assert result["status"] == "confirmed"
    assert poll_request.get_user_info(result["cookies"])["external_user_id"] == "fixture-user"
    assert live_api.closed == 1
    assert not XhsCreatorLoginAdapter._qr_sessions


def test_creator_qr_406_retry_reinitializes_each_attempt(sdk):
    factory, _ = sdk
    factory.responses = ["HTTP 406, code=-1", "HTTP 406, code=-1", None]
    assert XhsCreatorLoginAdapter().create_qrcode()["qr_id"]
    assert factory.instances[0].generated_with == [0, 1, 2]


def test_creator_qr_retries_are_bounded_and_release_failed_client(sdk):
    factory, _ = sdk
    factory.responses = ["HTTP 406, code=-1"] * 3
    with pytest.raises(RuntimeError, match="HTTP 406"):
        XhsCreatorLoginAdapter().create_qrcode()
    assert factory.instances[0].generated_with == [0, 1, 2]
    assert factory.instances[0].closed == 1
    assert not XhsCreatorLoginAdapter._qr_sessions


def test_creator_qr_permanent_error_is_not_retried(sdk):
    factory, _ = sdk
    factory.responses = ["HTTP 403"]
    with pytest.raises(RuntimeError, match="HTTP 403"):
        XhsCreatorLoginAdapter().create_qrcode()
    assert factory.instances[0].generated_with == [0]
    assert factory.instances[0].closed == 1


def test_creator_qr_expiry_requires_a_fresh_qr_instead_of_new_device_poll(sdk):
    factory, clock = sdk
    created = XhsCreatorLoginAdapter().create_qrcode()
    clock["now"] += XhsCreatorLoginAdapter.QR_SESSION_TTL_SECONDS + 1
    result = XhsCreatorLoginAdapter().check_qrcode_status(created["qr_id"], created["cookies"])
    assert result["status"] == "expired"
    assert len(factory.instances) == 1
    assert factory.instances[0].polls == 0
    assert factory.instances[0].closed == 1


def test_creator_qr_cache_evicts_old_runtime(sdk, monkeypatch):
    factory, _ = sdk
    monkeypatch.setattr(XhsCreatorLoginAdapter, "QR_SESSION_LIMIT", 2)
    for _ in range(3):
        XhsCreatorLoginAdapter().create_qrcode()
    assert len(XhsCreatorLoginAdapter._qr_sessions) == 2
    assert factory.instances[0].closed == 1


def test_creator_qr_initialization_failure_closes_client(sdk):
    factory, _ = sdk
    factory.prepare_error = True
    with pytest.raises(RuntimeError, match="initialization failed"):
        XhsCreatorLoginAdapter().create_qrcode()
    assert factory.instances[0].closed == 1
