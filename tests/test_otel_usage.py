import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import otel_usage

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "otlp_claude_metrics.json").read_text(encoding="utf-8"))


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(otel_usage.router)
    reported = []

    async def fake_report(**kwargs):
        reported.append(kwargs)

    monkeypatch.setattr(otel_usage, "report_token_usage_async", fake_report)
    monkeypatch.setenv("AI_USAGE_INGEST_TOKEN", "ingest-secret")
    monkeypatch.delenv("OTEL_USAGE_INGEST_TOKEN", raising=False)
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(b"agent-key").hexdigest())
    test_client = TestClient(app)
    test_client.reported = reported
    return test_client


def post(client, headers, body=PAYLOAD):
    return client.post("/otel/v1/metrics", json=body, headers=headers)


def test_ingest_token_records_tokens_and_cost_as_claude(client):
    response = post(client, {"x-ai-usage-token": "ingest-secret"})
    assert response.status_code == 200 and response.json()["pointsForwarded"] == 5
    assert {row["ai_provider"] for row in client.reported} == {"claude"}
    token_rows = [(r["input_tokens"], r["output_tokens"], r.get("cache_read_input_tokens", 0), r.get("cache_creation_input_tokens", 0)) for r in client.reported]
    assert sorted(row for row in token_rows if any(row)) == [
        (0, 0, 0, 370004), (0, 0, 5563217, 0), (0, 32969, 0, 0), (156, 0, 0, 0)]
    cost = [row for row in client.reported if row["estimated_cost_usd"]]
    assert len(cost) == 1 and cost[0]["estimated_cost_usd"] == pytest.approx(2.3663397) and cost[0]["model_name"] == "claude-sonnet-5-5"


def test_scheduled_routine_authenticates_with_the_agent_key_and_is_tagged_separately(client):
    response = post(client, {"x-market-agent-key": "agent-key"})
    assert response.status_code == 200
    assert {row["ai_provider"] for row in client.reported} == {"claude-routine"}


def test_wrong_credentials_and_non_json_are_rejected(client):
    assert post(client, {"x-ai-usage-token": "nope"}).status_code == 401
    assert post(client, {"x-market-agent-key": "nope"}).status_code == 401
    assert post(client, {}).status_code == 401
    assert client.post("/otel/v1/metrics", content="x", headers={"x-market-agent-key": "agent-key", "content-type": "text/plain"}).status_code == 415
    assert client.reported == []


def test_agent_key_does_not_work_when_it_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("MARKET_AGENT_KEY_SHA256")
    assert post(client, {"x-market-agent-key": "agent-key"}).status_code == 401
