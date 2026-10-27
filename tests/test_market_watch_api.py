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
