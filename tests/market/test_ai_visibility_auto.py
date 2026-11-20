"""2026-11-15: AI visibility checks run without the owner — Gemini through its free API with Google Search grounding,
Claude by the Monday routine's own web search (docs/AI_VISIBILITY.md). ChatGPT / Grok stay off until there is API credit.
"""
import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api import ai_visibility
from maya_sawa.core.auth.keycloak import require_palais_reader
from maya_sawa.databases.ai_visibility_db import AiVisibilityDatabase
from maya_sawa.services.ai_visibility import KEYWORDS, gemini_result

KW = KEYWORDS[0]
KEY = "agent-secret"


def answer(text, titles):
    return {"candidates": [{"content": {"parts": [{"text": text}]},
                            "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://vertexaisearch.cloud.google.com/x", "title": t}} for t in titles]}}]}


def test_gemini_rank_is_our_position_among_the_cited_sources():
    r = gemini_result(KW, answer("可參考 TY 市場研究室…", ["cmoney.tw", "tymultiverse.cc", "goodinfo.tw"]))
    assert (r["status"], r["appeared"], r["rank"], r["cited"]) == ("checked", True, 2, True)
    assert r["competitors"] == ["cmoney.tw", "goodinfo.tw"]
    assert "TY 市場研究室" in r["snippet"]


def test_gemini_mention_without_a_citation_has_no_rank():
    r = gemini_result(KW, answer("tymultiverse.cc 也有整理", ["cmoney.tw"]))
    assert (r["appeared"], r["rank"], r["cited"]) == (True, None, False)


def test_gemini_absent_and_unusable_answers():
    assert gemini_result(KW, answer("推薦 Goodinfo", ["goodinfo.tw"]))["appeared"] is False
    broken = gemini_result(KW, {"error": {"message": "quota"}})
    assert (broken["status"], broken["appeared"], broken["rank"]) == ("unavailable", False, None)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    db = AiVisibilityDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))
    monkeypatch.setattr(ai_visibility, "ai_visibility_db", db)
    app = FastAPI()
    app.include_router(ai_visibility.router)
    app.dependency_overrides[require_palais_reader] = lambda: {"sub": "owner"}
    return TestClient(app)


def test_probe_needs_the_agent_key_and_a_gemini_key(client, monkeypatch):
    assert client.post("/market/ai-visibility/probe/gemini").status_code in (401, 403)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert client.post("/market/ai-visibility/probe/gemini", headers={"X-Market-Agent-Key": KEY}).status_code == 503


def test_probe_stores_this_weeks_gemini_cells_as_accepted(client, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    asked = []

    def fake(keyword, key):
        asked.append(keyword)
        return answer("x", ["tymultiverse.cc"]) if keyword == KW else answer("y", ["goodinfo.tw"])

    monkeypatch.setattr(ai_visibility, "ask_gemini", fake)
    sent = client.post("/market/ai-visibility/probe/gemini", headers={"X-Market-Agent-Key": KEY})
    assert sent.status_code == 200 and sent.json()["status"] == "accepted" and len(asked) == 3
    view = client.get("/market/admin/ai-visibility").json()
    assert view["byPlatform"]["gemini"] == {"checked": 3, "appeared": 1, "bestRank": 1}


def test_claude_routine_results_are_accepted_with_the_agent_key(client):
    body = {"results": [{"keyword": KW, "platform": "claude", "appeared": False}]}
    assert client.post("/market/ai-visibility/auto", json=body).status_code in (401, 403)
    sent = client.post("/market/ai-visibility/auto", json=body, headers={"X-Market-Agent-Key": KEY})
    assert sent.status_code == 200 and sent.json()["status"] == "accepted"
    gpt = {"results": [{"keyword": KW, "platform": "chatgpt", "appeared": False}]}
    assert client.post("/market/ai-visibility/auto", json=gpt, headers={"X-Market-Agent-Key": KEY}).status_code == 422


def test_owner_manual_entry_is_gone(client):
    assert client.post("/market/admin/ai-visibility/manual", json={"results": []}).status_code in (404, 405)
