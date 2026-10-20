"""People/weapons sync reads (2026-10-20: every pod start logged "'str' object has no attribute 'get'").

The backend's POST /tymb/people/get-all and GET /tymb/weapons became asynchronous: they answer 202 with
{"success", "code", "message", "timestamp", "requestId"} and no data. The sync iterated that dict's keys as
records. The gateway (/tymg/...) waits for the result and returns the list, as the website does.
"""
import pytest

import maya_sawa.core  # noqa: F401  (loads core before maya_sawa.people, as the app does; avoids the import cycle)
from maya_sawa.people import people as people_module

ASYNC_ENVELOPE = {"success": True, "code": 202, "message": "角色列表獲取請求已提交",
                  "timestamp": "2026-10-20T11:04:35.764093385Z", "requestId": "4f08e6c2-7de4-4029-992c-575bdb9177f0"}


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeClient:
    calls = []
    payload = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        FakeClient.calls.append(("POST", url))
        return FakeResponse(FakeClient.payload)

    def get(self, url, **kwargs):
        FakeClient.calls.append(("GET", url))
        return FakeResponse(FakeClient.payload)


@pytest.fixture
def manager(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(people_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(people_module.Config, "PUBLIC_API_BASE_URL", "http://ty-multiverse-gateway-service:8082")
    monkeypatch.setattr(people_module.Config, "PUBLIC_TYMB_URL", "http://ty-multiverse-backend/tymb")
    return object.__new__(people_module.PeopleWeaponManager)


def test_people_are_read_through_the_gateway_which_returns_the_list(manager):
    FakeClient.payload = [{"name": "Wavo"}]
    assert manager.fetch_people_data() == [{"name": "Wavo"}]
    assert FakeClient.calls == [("POST", "http://ty-multiverse-gateway-service:8082/tymg/people/get-all")]


def test_weapons_are_read_through_the_gateway_which_returns_the_list(manager):
    FakeClient.payload = [{"owner": "Wavo", "weapon": "x"}]
    assert manager.fetch_weapons_data() == [{"owner": "Wavo", "weapon": "x"}]
    assert FakeClient.calls == [("GET", "http://ty-multiverse-gateway-service:8082/tymg/weapons")]


def test_an_async_accepted_envelope_is_an_error_not_a_list_of_records(manager):
    FakeClient.payload = ASYNC_ENVELOPE
    with pytest.raises(ValueError, match="requestId"):
        manager.fetch_people_data()
    with pytest.raises(ValueError, match="requestId"):
        manager.fetch_weapons_data()


def test_the_periodic_loop_runs_for_people_sync_even_with_article_sync_off(monkeypatch):
    from maya_sawa.core.services import scheduler
    monkeypatch.setattr(scheduler.Config, "ENABLE_PERIODIC_SYNC", False)
    monkeypatch.setattr(scheduler.Config, "ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC", True)
    assert scheduler.periodic_sync_wanted() is True
    monkeypatch.setattr(scheduler.Config, "ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC", False)
    assert scheduler.periodic_sync_wanted() is False
