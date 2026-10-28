"""A scheduled routine reports its own token use at the end of a run: the cloud session keeps a transcript with per-message
usage, a small script sums it, and the backend records it as provider "claude-routine" for the portfolio chart's cost line."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("report_routine_usage", ROOT / "maya_sawa" / "public_scripts" / "report_routine_usage.py")
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)
FIXTURE = Path(__file__).parent / "fixtures" / "claude_session_usage.jsonl"


def test_sums_usage_per_model_counting_each_message_once_and_skipping_noise():
    totals = script.summarize(FIXTURE.read_text(encoding="utf-8").splitlines())
    assert totals == {
        "claude-opus-5-5": {"input": 10, "output": 430, "cacheCreation": 9300, "cacheRead": 9000, "calls": 2},  # msg_01 once (its last, fullest line)
        "claude-sonnet-5-5": {"input": 3, "output": 40, "cacheCreation": 0, "cacheRead": 500, "calls": 1},
    }


def test_picks_the_newest_transcript_and_builds_the_payload(tmp_path):
    old, new = tmp_path / "p" / "old.jsonl", tmp_path / "p" / "new-session-id.jsonl"
    old.parent.mkdir()
    old.write_text("{}", encoding="utf-8")
    new.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    import os
    os.utime(old, (1, 1))
    assert script.latest_transcript([str(tmp_path)]) == new
    body = script.build_payload(new, "萃取主張")
    assert body["sessionId"] == "new-session-id" and body["label"] == "萃取主張"
    assert sorted(item["model"] for item in body["models"]) == ["claude-opus-5-5", "claude-sonnet-5-5"]
    assert script.latest_transcript([str(tmp_path / "missing")]) is None


def test_main_never_fails_the_routine(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(script, "ROOTS", [str(tmp_path)])
    assert script.main(["萃取主張"]) == 0 and "no transcript" in capsys.readouterr().out
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "s.jsonl").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    sent = []
    monkeypatch.setattr(script, "post", lambda body: sent.append(body) or {"recorded": 2, "failed": {}})
    assert script.main(["萃取主張"]) == 0 and sent[0]["models"] and "reported" in capsys.readouterr().out
    monkeypatch.setattr(script, "post", lambda body: {"recorded": 0, "failed": {"claude-opus-5-5": 401}})
    assert script.main(["萃取主張"]) == 0 and "not recorded" in capsys.readouterr().out
    monkeypatch.setattr(script, "post", lambda body: (_ for _ in ()).throw(OSError("offline")))
    assert script.main(["萃取主張"]) == 0 and "not reported" in capsys.readouterr().out


@pytest.fixture
def web(monkeypatch):
    from maya_sawa.api import market
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(b"k").hexdigest())
    calls = []

    async def record(**kwargs):
        calls.append(kwargs)
        return 201
    monkeypatch.setattr(market, "report_token_usage_async", record)
    app = FastAPI()
    app.include_router(market.router)
    return TestClient(app), calls


BODY = {"sessionId": "s1", "label": "萃取主張", "models": [{"model": "claude-opus-5-5", "input": 10, "output": 430, "cacheCreation": 9300, "cacheRead": 9000}]}


def test_the_endpoint_records_each_model_as_routine_usage_and_only_for_the_agent_key(web):
    client, calls = web
    assert client.post("/market/routine-usage", json=BODY).status_code == 401
    assert client.post("/market/routine-usage", json={**BODY, "models": []}, headers={"x-market-agent-key": "k"}).status_code == 422
    ok = client.post("/market/routine-usage", json=BODY, headers={"x-market-agent-key": "k"})
    assert ok.status_code == 200 and ok.json() == {"recorded": 1, "failed": {}}
    assert calls == [dict(ai_provider="claude-routine", model_name="claude-opus-5-5", input_tokens=10, output_tokens=430,
                          cache_creation_input_tokens=9300, cache_read_input_tokens=9000, estimated_cost_usd=0.02144, session_id="s1",
                          endpoint="/market/routine-usage/萃取主張")]


def test_the_script_is_served_so_routines_without_a_checkout_can_run_it(web):
    client, _ = web
    response = client.get("/market/routine-usage.py")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/plain")
    assert "def main" in response.text and "claude-routine" not in response.text  # the provider tag lives on the server


def test_cost_is_an_estimate_from_the_recorded_rates_and_never_zero_for_an_unknown_model():
    from maya_sawa.services.routine_cost import estimate_cost
    # Opus 5.5 at ~$1.46/M input: (10 + 5*430 + 1.25*9300 + 0.1*9000) tokens-equivalent
    assert estimate_cost("claude-opus-5-5", 10, 430, 9300, 9000) == pytest.approx(1.46 * (10 + 2150 + 11625 + 900) / 1e6, rel=1e-3)
    assert estimate_cost("claude-sonnet-5-5-20261001", 1_000_000, 0) == pytest.approx(1.18)   # a dated model id still matches
    assert estimate_cost("claude-future-9", 1_000_000, 0) == pytest.approx(1.2)
    assert estimate_cost("claude-sonnet-5-5", 0, 0) == 0


def test_the_endpoint_says_when_the_usage_service_refused_the_record(monkeypatch):
    """2026-10-28: a routine reported success but nothing reached the database; the endpoint now tells the script what really happened."""
    from maya_sawa.api import market
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(b"k").hexdigest())

    async def refused(**kwargs):
        return 401
    monkeypatch.setattr(market, "report_token_usage_async", refused)
    app = FastAPI()
    app.include_router(market.router)
    reply = TestClient(app).post("/market/routine-usage", json=BODY, headers={"x-market-agent-key": "k"}).json()
    assert reply == {"recorded": 0, "failed": {"claude-opus-5-5": 401}}
