"""Nominations from the routine, the public watch list, and the custom area that shows the watched stocks."""
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.databases.market_watch_db import MarketWatchDatabase
from maya_sawa.services import market_watch as watch

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


@pytest.fixture
def db():
    return MarketWatchDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))


def mention(source, ago=0, **extra):
    return {"at": (NOW - timedelta(days=ago)).isoformat(), "source": source, "conviction": "normal", "reason": "訂單能見度提高", **extra}


def test_nominations_are_stored_and_the_custom_area_follows_the_rules(db):
    rows, promoted = db.nominate("3711", "TW", "日月光投控", [mention("r1", 2)], NOW, held=set())
    assert promoted == [] and db.current(NOW, held=set()) == []        # one report: only a candidate
    rows, promoted = db.nominate("3711", "TW", "日月光投控", [mention("r2", 0)], NOW, held=set())
    assert promoted == ["3711"] and [item["code"] for item in db.current(NOW, held=set())] == ["3711"]
    assert db.nominate("3711", "TW", "日月光投控", [mention("r3", 0)], NOW, held=set())[1] == []  # already in: not "newly" promoted


def test_reading_the_list_applies_expiry_and_purchases(db):
    db.nominate("3711", "TW", "日月光投控", [mention("r1", 40), mention("r2", 31)], NOW - timedelta(days=31), held=set())
    assert [item["code"] for item in db.current(NOW - timedelta(days=31), held=set())] == ["3711"]
    assert db.current(NOW, held=set()) == []                           # neglected for 31 days
    db.nominate("2330", "TW", "台積電", [mention("a", 1), mention("b", 0)], NOW, held=set())
    assert db.current(NOW, held={"2330"}) == []                        # bought: it is a normal holding now
    assert [item["code"] for item in db.current(NOW, held=set())] == ["2330"]  # sold: back in the custom area


def client(db, monkeypatch, reports=("r1", "r2", "r3"), known=True):
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_watch_db", db)
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(b"k").hexdigest())

    class Reports:
        def get_report(self, report_id, *, include_pdf=False):
            return ({"id": report_id, "visibility": "public", "status": "ready"}, None, "u") if report_id in reports else None
    monkeypatch.setattr(market, "market_reports_db", Reports())

    async def search(code, kind):
        return [{"code": code, "name": "日月光投控"}] if known else []
    monkeypatch.setattr(market.shioaji_market_service, "search_contracts", search)
    monkeypatch.setattr(market.market_dashboard_db, "find_candidate", lambda kind, code: None)
    monkeypatch.setattr(market.market_dashboard_db, "latest_auto", lambda: {"positions": [{"code": "2330", "productType": "stock"}], "snapshotAt": None})
    started = []

    async def enqueue(codes):
        started.append(("history", list(codes)))
    monkeypatch.setattr(market.market_history_collector, "enqueue_codes", enqueue)
    monkeypatch.setattr(market, "start_added_analysis", lambda items: started.append(("analysis", [item["code"] for item in items])))
    app = FastAPI()
    app.include_router(market.router)
    return TestClient(app), started


BODY = {"code": "3711", "reason": "ASE 先進封裝 2027 年產能再擴，兩份報告都點名", "reportIds": ["r1", "r2"]}


def test_weekly_gpt_batch_validates_evidence_before_writing_and_defaults_to_dry_run(db, monkeypatch):
    from maya_sawa.api import market
    web, started = client(db, monkeypatch)
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setattr(market.market_reports_db.__class__, "list_claims", lambda self: [
        {"report_id": rid, "codes": ["3711"], "published_at": today} for rid in ("r1", "r2")], raising=False)
    async def macro(months):
        return {"indicators": [{"code": "US_FED", "history": [{"value": 4.0}]}]}
    monkeypatch.setattr(market.market_macro_service, "get", macro)
    payload = {"proposals": [{**BODY, "risk": "Demand risk", "macroReason": "Funding costs", "macroSourceIds": ["US_FED"]}]}
    # Cloud research can preview without a secret; it cannot publish without one.
    assert web.post('/market/watch/weekly', json={**payload, "dryRun": False}).status_code == 401
    assert web.post('/market/watch/weekly', json={**payload, "dryRun": False},
                    headers={"x-market-agent-key": "wrong"}).status_code == 401
    preview = web.post('/market/watch/weekly', json=payload)
    assert preview.status_code == 200 and preview.json()['dryRun'] is True
    assert db.load() == [] and started == []
    invalid = {"proposals": [payload['proposals'][0], {**payload['proposals'][0], "code": "2330"}], "dryRun": False}
    assert web.post('/market/watch/weekly', json=invalid, headers={"x-market-agent-key": "k"}).status_code == 422
    assert db.load() == []
    result = web.post('/market/watch/weekly', json={**payload, "dryRun": False}, headers={"x-market-agent-key": "k"})
    assert result.status_code == 200 and result.json()['results'][0]['promoted'] is True
    assert started == [("history", ["3711"]), ("analysis", ["3711"])]


PROPOSAL = {**BODY, "risk": "Demand risk", "macroReason": "Funding costs", "macroSourceIds": ["US_FED"]}
KEY = {"x-market-agent-key": "k"}
INBOX = "/market/watch/weekly/proposals"


def weekly_client(db, monkeypatch, evidence=("r1", "r2")):
    """The GPT job posts to the inbox without a key; the keyed Claude routine reviews what it left there."""
    from maya_sawa.api import market
    from maya_sawa.databases.market_weekly_proposals_db import WeeklyProposalDatabase
    web, started = client(db, monkeypatch)
    set_evidence(monkeypatch, evidence)

    async def macro(months):
        return {"indicators": [{"code": "US_FED", "history": [{"value": 4.0}]}]}
    monkeypatch.setattr(market.market_macro_service, "get", macro)
    inbox = WeeklyProposalDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))
    monkeypatch.setattr(market, "market_weekly_proposals_db", inbox)
    return web, started, inbox


def set_evidence(monkeypatch, report_ids):
    from maya_sawa.api import market
    today = datetime.now(timezone.utc).date().isoformat()
    monkeypatch.setattr(market.market_reports_db.__class__, "list_claims", lambda self: [
        {"report_id": rid, "codes": ["3711"], "published_at": today} for rid in report_ids], raising=False)


def test_gpt_leaves_proposals_without_a_key_and_nothing_is_nominated_until_review(db, monkeypatch):
    web, started, inbox = weekly_client(db, monkeypatch)
    sent = web.post(INBOX, json={"proposals": [PROPOSAL], "dryRun": True})   # GPT may echo dryRun; it is ignored
    assert sent.status_code == 200 and sent.json()["stored"] is True and sent.json()["status"] == "pending"
    assert db.load() == [] and started == []                                  # the watch list is untouched
    again = web.post(INBOX, json={"proposals": [PROPOSAL]})                   # a re-run in the same week
    assert again.json()["stored"] is False and again.json()["id"] == sent.json()["id"]
    assert web.get(INBOX).status_code == 401                                  # untrusted text is not republished
    pending = web.get(INBOX, headers=KEY).json()["proposals"]
    assert [item["id"] for item in pending] == [sent.json()["id"]]
    assert pending[0]["proposals"][0]["code"] == "3711" and pending[0]["status"] == "pending"


def test_unsupported_or_empty_submissions_are_not_stored(db, monkeypatch):
    web, _, inbox = weekly_client(db, monkeypatch)
    assert web.post(INBOX, json={"proposals": [{**PROPOSAL, "reportIds": ["r1", "nope"]}]}).status_code == 422
    assert web.post(INBOX, json={"proposals": [{**PROPOSAL, "code": "2330"}]}).status_code == 422  # a holding
    assert web.post(INBOX, json={"proposals": [{**PROPOSAL, "macroSourceIds": ["MADE_UP"]}]}).status_code == 422
    assert web.post(INBOX, json={"proposals": [PROPOSAL] * 4}).status_code == 422
    empty = web.post(INBOX, json={"proposals": []})
    assert empty.status_code == 200 and empty.json()["stored"] is False
    assert inbox.list() == []


def test_review_applies_a_proposal_once_and_a_rejection_leaves_the_watch_list(db, monkeypatch):
    web, started, inbox = weekly_client(db, monkeypatch)
    first = web.post(INBOX, json={"proposals": [PROPOSAL]}).json()["id"]
    assert web.post(f"{INBOX}/{first}/review", json={"action": "apply"}).status_code == 401
    applied = web.post(f"{INBOX}/{first}/review", json={"action": "apply"}, headers=KEY)
    assert applied.status_code == 200 and applied.json()["status"] == "applied"
    assert applied.json()["results"][0]["promoted"] is True
    assert started == [("history", ["3711"]), ("analysis", ["3711"])]
    assert web.post(f"{INBOX}/{first}/review", json={"action": "apply"}, headers=KEY).status_code == 409
    assert web.post(f"{INBOX}/missing/review", json={"action": "apply"}, headers=KEY).status_code == 404
    second = web.post(INBOX, json={"proposals": [{**PROPOSAL, "reason": "另一個理由：先進封裝訂單外溢到 2027"}]}).json()["id"]
    rejected = web.post(f"{INBOX}/{second}/review", json={"action": "reject", "note": "重複催化"}, headers=KEY)
    assert rejected.json()["status"] == "rejected" and len(started) == 2
    assert web.get(INBOX, headers=KEY).json()["proposals"] == []              # default view: pending only
    history = {item["id"]: item["status"] for item in web.get(INBOX + "?status=all", headers=KEY).json()["proposals"]}
    assert history == {first: "applied", second: "rejected"}


def test_applying_rechecks_the_evidence_as_it_stands_at_review_time(db, monkeypatch):
    web, started, _ = weekly_client(db, monkeypatch)
    pending = web.post(INBOX, json={"proposals": [PROPOSAL]}).json()["id"]
    set_evidence(monkeypatch, ("r1",))                                        # a report was withdrawn meanwhile
    result = web.post(f"{INBOX}/{pending}/review", json={"action": "apply"}, headers=KEY).json()
    assert result["status"] == "rejected" and "Two recent public reports" in result["detail"]
    assert db.load() == [] and started == []


def test_the_inbox_holds_a_bounded_number_of_batches_per_week(db, monkeypatch):
    from maya_sawa.api import market
    web, _, _ = weekly_client(db, monkeypatch)
    monkeypatch.setattr(market, "WEEKLY_INBOX_LIMIT", 2)
    send = lambda n: web.post(INBOX, json={"proposals": [{**PROPOSAL, "reason": f"第 {n} 次送出的研究理由，內容不同"}]})
    assert send(1).status_code == 200 and send(2).status_code == 200
    assert send(3).status_code == 429


def test_only_the_agent_key_nominates_and_a_promotion_starts_the_data_and_first_analysis(db, monkeypatch):
    web, started = client(db, monkeypatch)
    assert web.post("/market/watch", json=BODY).status_code == 401
    ok = web.post("/market/watch", json=BODY, headers={"x-market-agent-key": "k"})
    assert ok.status_code == 200 and ok.json()["status"] == "watching" and ok.json()["promoted"] is True
    assert started == [("history", ["3711"]), ("analysis", ["3711"])]
    shown = web.get("/market/watch").json()
    assert [item["code"] for item in shown["watching"]] == ["3711"] and shown["watching"][0]["reason"].startswith("ASE")
    again = web.post("/market/watch", json=BODY, headers={"x-market-agent-key": "k"}).json()
    assert again["promoted"] is False and len(started) == 2


def test_a_nomination_needs_real_public_reports_a_real_taiwan_stock_and_a_stated_reason(db, monkeypatch):
    web, _ = client(db, monkeypatch)
    send = lambda body: web.post("/market/watch", json=body, headers={"x-market-agent-key": "k"}).status_code
    assert send({**BODY, "reportIds": ["nope"]}) == 422                  # a report that does not exist
    assert send({**BODY, "reportIds": []}) == 422
    assert send({**BODY, "reason": "好"}) == 422
    assert send({**BODY, "code": "MU"}) == 422                           # Taiwan stocks only for now
    assert send({**BODY, "conviction": "maybe"}) == 422
    unknown, _ = client(db, monkeypatch, known=False)
    assert unknown.post("/market/watch", json=BODY, headers={"x-market-agent-key": "k"}).status_code == 422
    held, _ = client(db, monkeypatch)
    assert held.post("/market/watch", json={**BODY, "code": "2330"}, headers={"x-market-agent-key": "k"}).status_code == 422  # already a holding


def test_one_high_conviction_report_is_enough_and_the_candidates_are_listed_separately(db, monkeypatch):
    web, _ = client(db, monkeypatch)
    one = {**BODY, "reportIds": ["r1"]}
    assert web.post("/market/watch", json=one, headers={"x-market-agent-key": "k"}).json()["status"] == "candidate"
    data = web.get("/market/watch").json()
    assert data["watching"] == [] and [item["code"] for item in data["candidates"]] == ["3711"]
    high = web.post("/market/watch", json={**one, "conviction": "high"}, headers={"x-market-agent-key": "k"}).json()
    assert high["status"] == "watching"


def test_custom_rows_merge_watched_stocks_without_duplicating_the_owners_picks():
    rows = watch.merge_into_custom([{"code": "2454", "productType": "stock", "market": "TW"}],
                                   [{"code": "2454", "productType": "stock", "market": "TW", "source": "ai-watch"},
                                    {"code": "3711", "productType": "stock", "market": "TW", "source": "ai-watch"}],
                                   taken={("stock", "2330")})
    assert [(item["code"], item.get("source")) for item in rows] == [("2454", None), ("3711", "ai-watch")]
    assert watch.merge_into_custom([], [{"code": "2330", "productType": "stock", "market": "TW"}], taken={("stock", "2330")}) == []
