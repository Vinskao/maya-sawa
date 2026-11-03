"""The usage reporter says whether the usage service accepted a record, instead of swallowing every failure silently."""
import asyncio

import pytest

from maya_sawa.services import token_reporter as reporter


class FakeClient:
    status = 201
    error = None
    posted = []

    def __init__(self, *args, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False

    async def post(self, url, json=None, headers=None):
        if FakeClient.error:
            raise FakeClient.error
        FakeClient.posted.append((url, json, headers))

        class Response:
            status_code = FakeClient.status
        return Response()


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    FakeClient.status, FakeClient.error, FakeClient.posted = 201, None, []
    monkeypatch.setattr(reporter.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(reporter, "TYMB_URL", "http://tymb")
    monkeypatch.setattr(reporter, "AI_USAGE_ENDPOINT", "http://tymb/ai-usage")
    monkeypatch.setattr(reporter, "AI_USAGE_INGEST_TOKEN", "secret-token")


def report():
    return asyncio.run(reporter.report_token_usage_async("claude-routine", "claude-opus-5-5", 1, 2))


def test_returns_the_status_the_usage_service_answered_with():
    assert report() == 201
    FakeClient.status = 401
    assert report() == 401                               # e.g. the ingest token does not match
    assert FakeClient.posted[0][2] == {"X-AI-Usage-Token": "secret-token"}


def test_returns_zero_when_unreachable_and_minus_one_when_not_configured(monkeypatch):
    FakeClient.error = OSError("connection refused")
    assert report() == 0
    FakeClient.error = None
    monkeypatch.setattr(reporter, "TYMB_URL", "")
    assert report() == -1
