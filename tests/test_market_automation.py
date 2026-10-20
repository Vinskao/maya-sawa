import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from maya_sawa.services import market_automation as automation
from maya_sawa.services.market_automation import TAIPEI, AutomationStore, due_runs, ib_authenticated, session_date


def tpe(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TAIPEI)


TAIWAN, US = automation.RUNS


def test_sessions_follow_each_market_close():
    # 2026-10-19 is a Monday.
    assert session_date(TAIWAN, tpe(19, 14, 29)) is None  # Tokyo/Seoul/Taipei not all closed yet
    # Margin balances and securities lending publish around 20:45 (measured 2026-10-19) and are collected at 21:00.
    assert session_date(TAIWAN, tpe(19, 21, 9)) is None
    assert session_date(TAIWAN, tpe(19, 21, 10)) == date(2026, 10, 19)
    assert session_date(TAIWAN, tpe(18, 20)) is None  # Sunday
    assert session_date(US, tpe(19, 9)) is None  # Monday morning follows no US session
    assert session_date(US, tpe(20, 5, 29)) is None
    assert session_date(US, tpe(20, 5, 30)) == date(2026, 10, 20)  # Monday's New York session
    assert session_date(US, tpe(24, 8)) == date(2026, 10, 24)  # Saturday morning covers Friday


def test_run_fires_only_after_overseas_bars_were_collected_after_the_close():
    now = tpe(19, 21, 30)
    before_close = tpe(19, 12)
    after_close = tpe(19, 17, 50)
    assert due_runs(now, {}, {"JP": before_close, "KR": after_close}) == []  # IB lapsed before Tokyo closed
    assert due_runs(now, {}, {"JP": after_close, "KR": None}) == []  # a holding was never collected
    assert due_runs(now, {}, {"JP": after_close, "KR": after_close}) == [TAIWAN]
    assert due_runs(now, {}, {}) == [TAIWAN]  # no Japan/Korea holdings: nothing to wait for
    assert due_runs(now, {"taiwan": date(2026, 10, 19)}, {"JP": after_close}) == []  # once per session
    # Bars from the afternoon still count: the close is 14:30 even though the run waits for the evening data.
    assert due_runs(now, {}, {"JP": tpe(19, 15), "KR": tpe(19, 15)}) == [TAIWAN]
    assert due_runs(tpe(19, 18), {}, {"JP": after_close, "KR": after_close}) == []  # margin data not out yet


def test_us_run_waits_for_us_bars_and_ignores_asian_markets():
    now = tpe(20, 7)
    assert due_runs(now, {"taiwan": date(2026, 10, 20)}, {"US": tpe(20, 6), "JP": tpe(19, 12)}) == [US]
    assert due_runs(now, {"taiwan": date(2026, 10, 20)}, {"US": tpe(19, 18)}) == []


def test_ib_session_counts_as_live_only_while_the_gateway_is_being_polled():
    now = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(minutes=5)
    assert ib_authenticated(fresh, fresh, now)
    assert not ib_authenticated(now - timedelta(hours=2), fresh, now)
    assert not ib_authenticated(None, fresh, now)


def test_ib_needs_the_market_data_session_not_just_portfolio_reads():
    # 2026-10-19/20: /portfolio/* kept answering 200 while /iserver/auth/status said authenticated=false
    # ("no bridge"), so no bars were collected for a day and the site never asked for a login.
    now = datetime(2026, 10, 20, 3, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(minutes=3)
    assert not ib_authenticated(fresh, now - timedelta(hours=14), now)
    assert not ib_authenticated(fresh, None, now)


def test_store_claims_each_session_once(tmp_path):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'fires.db'}"))
    assert store.record("taiwan", date(2026, 10, 19), "https://claude.ai/code/session_1")
    assert not store.record("taiwan", date(2026, 10, 19), "https://claude.ai/code/session_2")
    store.release("us", date(2026, 10, 20))  # releasing an unclaimed run is harmless
    assert store.record("us", date(2026, 10, 20), "")
    store.release("us", date(2026, 10, 20))
    assert store.last_fired() == {"taiwan": date(2026, 10, 19)}


class FakeSource:
    def __init__(self, portfolio_at, positions, bars, market_data_at="same"):
        self.portfolio_at, self.positions, self.bars = portfolio_at, positions, bars
        self.market_data_at = portfolio_at if market_data_at == "same" else market_data_at

    def last_portfolio_at(self):
        return self.portfolio_at

    def last_market_data_at(self):
        return self.market_data_at

    def overseas_positions(self):
        return self.positions

    def bars_collected_at(self, code, market):
        return self.bars.get((code, market))


def test_check_fires_due_runs_once_and_reports_ib_status(tmp_path, monkeypatch):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'fires.db'}"))
    now = tpe(19, 21, 30).astimezone(timezone.utc)  # after the evening margin data
    source = FakeSource(now - timedelta(minutes=3), [("6857", "JP"), ("000660", "KR"), ("META", "US")],
                        {("6857", "JP"): tpe(19, 17), ("000660", "KR"): tpe(19, 17), ("META", "US"): tpe(17, 8)})
    fired = []

    async def fake_fire(run, text):
        fired.append(run.key)
        return f"https://claude.ai/code/{run.key}"

    monkeypatch.setattr(automation, "fire_routine", fake_fire)
    monkeypatch.delenv("MARKET_ROUTINE_TAIWAN_TOKEN", raising=False)
    assert {r["key"]: r["state"] for r in asyncio.run(automation.check(store, source, now))["runs"]}["taiwan"] == "not-configured"
    assert fired == []
    monkeypatch.setenv("MARKET_ROUTINE_TAIWAN_TOKEN", "test-token")
    status = asyncio.run(automation.check(store, source, now))
    assert fired == ["taiwan"]
    assert status["ib"]["authenticated"] is True
    assert {r["key"]: r["state"] for r in status["runs"]} == {"taiwan": "fired", "us": "no-session"}
    again = asyncio.run(automation.check(store, source, now))
    assert fired == ["taiwan"]
    assert {r["key"]: r["state"] for r in again["runs"]}["taiwan"] == "done"


def test_failed_fire_is_released_and_stale_ib_asks_for_login(tmp_path, monkeypatch):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'fires.db'}"))
    now = tpe(19, 21, 30).astimezone(timezone.utc)  # after the evening margin data

    async def broken_fire(run, text):
        raise RuntimeError("MARKET_ROUTINE_TAIWAN_TOKEN is not configured")

    monkeypatch.setattr(automation, "fire_routine", broken_fire)
    monkeypatch.setenv("MARKET_ROUTINE_TAIWAN_TOKEN", "revoked-token")
    fresh = FakeSource(now - timedelta(minutes=3), [], {})
    status = asyncio.run(automation.check(store, fresh, now))
    assert {r["key"]: r["state"] for r in status["runs"]}["taiwan"] == "error"
    assert store.last_fired() == {}  # released, so the next check retries

    stale = FakeSource(tpe(16, 19).astimezone(timezone.utc), [("6857", "JP")], {("6857", "JP"): tpe(16, 19)})
    status = asyncio.run(automation.check(store, stale, now))
    assert status["ib"]["authenticated"] is False
    assert {r["key"]: r["state"] for r in status["runs"]}["taiwan"] == "waiting-ib"

    portfolio_only = FakeSource(now - timedelta(minutes=3), [("6857", "JP")], {("6857", "JP"): tpe(16, 19)},
                                market_data_at=tpe(19, 13).astimezone(timezone.utc))
    status = asyncio.run(automation.check(store, portfolio_only, now))
    assert status["ib"]["authenticated"] is False  # the owner is asked to log in again


def test_owner_only_endpoint_runs_the_check(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    calls = []

    async def fake_check(store, source, now=None):
        calls.append(store)
        return {"ib": {"authenticated": False, "lastSeenAt": None, "loginUrl": ""}, "runs": []}

    monkeypatch.setattr(market.market_automation, "check", fake_check)
    app = FastAPI()
    app.include_router(market.router)
    client = TestClient(app)
    assert client.post("/market/automation/check").status_code == 401
    assert calls == []
    app.dependency_overrides[market.require_manage_users_request] = lambda: {"sub": "owner"}
    assert client.post("/market/automation/check").json()["ib"]["authenticated"] is False
    assert len(calls) == 1
