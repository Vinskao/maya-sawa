"""AI-search visibility checks: GPT probes ChatGPT/Grok/Gemini/Claude for our keywords twice a week (docs/AI_VISIBILITY.md).

A submitted run is untrusted: it is stored pending, shown on the dashboard only after the keyed Claude routine accepts it.
"""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api import ai_visibility
from maya_sawa.core.auth.keycloak import require_manage_users_request
from maya_sawa.databases.ai_visibility_db import AiVisibilityDatabase, InboxFull
from maya_sawa.services.ai_visibility import KEYWORDS, MAIN_KEYWORD, PLATFORMS, summarize, validate_results, weekly_keywords

NOW = datetime(2026, 11, 17, 19, 0, tzinfo=timezone.utc)  # Tuesday 03:00 Taipei
KW = KEYWORDS[0]


def row(keyword=KW, platform="chatgpt", **over):
    base = {"keyword": keyword, "platform": platform, "status": "checked", "appeared": False, "rank": None,
            "cited": False, "snippet": "", "competitors": []}
    return {**base, **over}


def test_the_keyword_list_is_fixed_and_unique():
    assert len(KEYWORDS) == len(set(KEYWORDS)) >= 10
    assert PLATFORMS == ("chatgpt", "grok", "gemini", "claude")


def test_a_rank_needs_an_appearance_and_unknown_keywords_are_refused():
    assert validate_results([row(appeared=True, rank=3)])[0]["rank"] == 3
    for bad in (row(appeared=False, rank=2), row(keyword="不在清單的字"), row(platform="bing"), row(appeared=True, rank=0),
                row(status="unavailable", appeared=True)):
        with pytest.raises(ValueError):
            validate_results([bad])


def test_the_same_keyword_and_platform_twice_is_refused():
    with pytest.raises(ValueError, match="duplicate"):
        validate_results([row(), row()])


def test_an_unavailable_platform_is_recorded_not_guessed():
    out = validate_results([row(platform="gemini", status="unavailable", snippet="login wall")])
    assert out[0]["status"] == "unavailable" and out[0]["appeared"] is False


def run(results, day, week=None):
    return {"id": f"r-{day}", "week": week or day, "submittedAt": f"{day}T00:00:00+00:00", "results": results}


def test_summary_counts_checked_cells_only_and_compares_with_the_previous_run():
    old = run([row(platform="chatgpt"), row(platform="grok", appeared=True, rank=5)], "2026-11-10")
    new = run([row(platform="chatgpt", appeared=True, rank=2), row(platform="grok", appeared=True, rank=4),
               row(platform="gemini", status="unavailable")], "2026-11-17")
    s = summarize([new, old])
    assert s["latest"]["checked"] == 2 and s["latest"]["appeared"] == 2 and s["latest"]["unavailable"] == 1
    assert s["previous"]["appeared"] == 1
    assert s["byPlatform"]["chatgpt"] == {"checked": 1, "appeared": 1, "bestRank": 2}
    cell = {(c["keyword"], c["platform"]): c for c in s["cells"]}
    assert cell[(KW, "chatgpt")]["change"] == "new" and cell[(KW, "grok")]["change"] == "up"
    assert s["trend"][0]["appeared"] == 1 and s["trend"][-1]["appeared"] == 2  # oldest first


def test_summary_with_no_runs_is_empty_not_an_error():
    assert summarize([])["latest"] is None


@pytest.fixture
def db():
    return AiVisibilityDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))


def test_inbox_dedupes_a_rerun_and_caps_runs_per_week(db):
    first, stored = db.submit("2026-W47", [row()], NOW, limit=2)
    again, stored_again = db.submit("2026-W47", [row()], NOW, limit=2)
    assert stored and not stored_again and again["id"] == first["id"] and first["status"] == "pending"
    db.submit("2026-W47", [row(platform="grok")], NOW, limit=2)
    with pytest.raises(InboxFull):
        db.submit("2026-W47", [row(platform="gemini")], NOW, limit=2)


def test_only_accepted_runs_reach_the_dashboard_and_a_run_is_reviewed_once(db):
    pending, _ = db.submit("2026-W47", [row(appeared=True, rank=1)], NOW, limit=6)
    assert db.list("accepted") == []
    assert db.review(pending["id"], "accept", "checked", NOW)["status"] == "accepted"
    assert db.review(pending["id"], "reject", "", NOW) is None
    assert [r["id"] for r in db.list("accepted")] == [pending["id"]]
    assert db.add_fixes(pending["id"], ["sitemap 補上知識文章"])["fixes"] == ["sitemap 補上知識文章"]


KEY = "agent-secret"


@pytest.fixture
def client(db, monkeypatch):
    import hashlib
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(KEY.encode()).hexdigest())
    monkeypatch.setattr(ai_visibility, "ai_visibility_db", db)
    app = FastAPI()
    app.include_router(ai_visibility.router)
    app.dependency_overrides[require_manage_users_request] = lambda: {"sub": "owner"}
    return TestClient(app)


def test_api_flow_from_gpt_submission_to_owner_dashboard(client):
    assert client.get("/market/ai-visibility/keywords").json()["keywords"] == list(KEYWORDS)
    sent = client.post("/market/ai-visibility/runs", json={"results": [row(appeared=True, rank=2)]})
    assert sent.status_code == 200 and sent.json()["status"] == "pending"
    run_id = sent.json()["id"]
    assert client.get("/market/ai-visibility/runs").status_code == 401  # reading the inbox needs the agent key
    headers = {"X-Market-Agent-Key": KEY}
    assert [r["id"] for r in client.get("/market/ai-visibility/runs", headers=headers).json()["runs"]] == [run_id]
    assert client.get("/market/admin/ai-visibility").json()["pending"] == 1
    assert client.get("/market/admin/ai-visibility").json()["latest"] is None
    ok = client.post(f"/market/ai-visibility/runs/{run_id}/review", headers=headers, json={"action": "accept", "note": "ok"})
    assert ok.json()["status"] == "accepted"
    assert client.post(f"/market/ai-visibility/runs/{run_id}/review", headers=headers, json={"action": "accept"}).status_code == 409
    fixed = client.post(f"/market/ai-visibility/runs/{run_id}/fixes", headers=headers, json={"fixes": ["加強首頁標題"]})
    assert fixed.status_code == 200
    summary = client.get("/market/admin/ai-visibility").json()
    assert summary["latest"]["appeared"] == 1 and summary["pending"] == 0 and summary["fixes"][0]["items"] == ["加強首頁標題"]


def test_bad_submissions_are_422(client):
    assert client.post("/market/ai-visibility/runs", json={"results": [row(keyword="x")]}).status_code == 422
    assert client.post("/market/ai-visibility/runs", json={"results": []}).status_code == 422


def test_each_week_checks_the_main_keyword_plus_two_that_rotate_through_the_rest():
    weeks = [weekly_keywords(f"2026-W{n:02d}") for n in range(1, 7)]
    assert all(len(w) == 3 and w[0] == MAIN_KEYWORD for w in weeks)
    rotated = [k for w in weeks[:6] for k in w[1:]]
    assert set(rotated) == set(KEYWORDS) - {MAIN_KEYWORD}            # 11 others covered within six weeks
    assert weekly_keywords("2026-W47") == weekly_keywords("2026-W47")  # stable within a week


def test_runs_from_the_same_week_merge_into_one_column():
    gpt = run([row(platform="chatgpt", appeared=True, rank=1)], "2026-11-17", "2026-W47")
    manual = run([row(platform="grok"), row(platform="gemini", appeared=True, rank=3)], "2026-11-18", "2026-W47")
    s = summarize([manual, gpt])
    assert s["latest"]["checked"] == 3 and s["latest"]["appeared"] == 2 and s["latest"]["week"] == "2026-W47"
    assert len(s["trend"]) == 1


def test_sunday_night_checks_after_midnight_still_count_as_that_week():
    # 週一 02:30 台北（週日深夜）仍算上一週；週一 06:00 起才是新的一週
    assert ai_visibility._week(datetime(2026, 11, 22, 18, 30, tzinfo=timezone.utc)) == "2026-W47"
    assert ai_visibility._week(datetime(2026, 11, 22, 22, 0, tzinfo=timezone.utc)) == "2026-W48"
