"""2026-11-14: post-event runs against TAIEX were carried only in analysis text; now stored events + recomputed tracking."""
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine

from maya_sawa.api import market
from maya_sawa.databases.market_signal_events_db import MarketSignalEventsDatabase
from maya_sawa.services import market_macro


def test_event_is_recorded_once_and_read_back_with_tracking(monkeypatch):
    db = MarketSignalEventsDatabase(create_engine("sqlite://"))
    monkeypatch.setattr(market, "market_signal_events_db", db)
    first = db.record("2330", "2026-11-09T15:00", "positive", "法說會上修全年展望", "https://example.test/a")
    again = db.record("2330", "2026-11-09T15:00", "positive", "法說會上修全年展望", "https://example.test/a")
    assert first["created"] and not again["created"] and first["id"] == again["id"]
    monkeypatch.setattr(market, "_taiex_closes", lambda start: {"2026-11-09": 100.0, "2026-11-10": 100.0, "2026-11-11": 100.0})
    monkeypatch.setattr(market.market_history_db, "history", lambda *a, **k: {"points": [
        {"date": d, "sources": {"twse:daily-price": {"close": c}}} for d, c in
        (("2026-11-09", 100.0), ("2026-11-10", 99.0), ("2026-11-11", 100.5))]})
    events = asyncio.run(market.get_signal_events(code="2330"))["events"]
    assert events[0]["tracking"]["status"] == "ended" and events[0]["tracking"]["divergingDays"] == 1


def test_posting_requires_the_agent_key(monkeypatch):
    class Req:
        headers = {}
    body = market.SignalEventBody(code="2330", publishedAt="2026-11-09T15:00", direction="positive",
                                  title="法說會上修", sourceUrl="https://example.test/a")
    with pytest.raises(HTTPException) as err:
        asyncio.run(market.post_signal_event(body, Req()))
    assert err.value.status_code == 401


def test_tx_settlements_by_month(monkeypatch):
    monkeypatch.setattr(market_macro, "tx_contract_settlements", lambda: {
        "2026-11-12": {"202611": 27000.0, "202612": 27100.0}, "2026-11-13": {"202612": 27200.0}})
    assert asyncio.run(market.get_tx_settlements())["months"] == ["202611", "202612"]
    assert asyncio.run(market.get_tx_settlements(month="202612"))["settlements"] == [
        {"date": "2026-11-12", "settlement": 27100.0}, {"date": "2026-11-13", "settlement": 27200.0}]


def test_relative_endpoint_reads_taiex_from_the_macro_cache(monkeypatch):
    # 90daad6 read the cache through a name that market.py rebinds to the service instance; this would raise.
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache())
    market_macro._macro_local_cache.set("series:TW_TAIEX", {"history": [
        {"period": "2026-11-12", "value": "100"}, {"period": "2026-11-13", "value": "101"}]}, 60)
    monkeypatch.setattr(market.market_history_db, "history", lambda *a, **k: {"points": [
        {"date": "2026-11-12", "sources": {"twse:daily-price": {"close": 50}}},
        {"date": "2026-11-13", "sources": {"twse:daily-price": {"close": 51}}}]})
    out = asyncio.run(market.get_market_relative_strength("2330"))
    assert out["status"] == "ok" and out["streakDays"] == 1 and out["todayGapPp"] == 1.0
