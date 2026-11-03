import asyncio
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from maya_sawa.services import market_automation as automation
from maya_sawa.services.market_automation import TAIPEI, AutomationStore, due_runs, ib_authenticated, session_date


def tpe(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=TAIPEI)


TAIWAN, US = automation.RUNS


def test_taiwan_automation_is_weekly_and_does_not_depend_on_ib_market_bars():
    assert TAIWAN.weekdays == (4,)
    assert TAIWAN.markets == ()
    assert session_date(TAIWAN, tpe(29, 21, 10)) is None
    assert session_date(TAIWAN, tpe(30, 21, 10)) == date(2026, 10, 30)
    assert automation.missed_runs(tpe(30, 21, 15), {"JP": tpe(28, 15), "KR": tpe(28, 15)}) == []


def test_sessions_follow_each_market_close():
    # Taiwan analysis reconciles only on Friday; overseas market routines retain their daily schedule.
    assert session_date(TAIWAN, tpe(29, 21, 10)) is None  # Thursday
    assert session_date(TAIWAN, tpe(30, 21, 10)) == date(2026, 10, 30)
    assert session_date(TAIWAN, tpe(25, 21, 10)) is None  # Sunday
    assert session_date(US, tpe(19, 9)) is None  # Monday morning follows no US session
    assert session_date(US, tpe(20, 5, 29)) is None
    assert session_date(US, tpe(20, 5, 30)) == date(2026, 10, 20)  # Monday's New York session
    assert session_date(US, tpe(24, 8)) == date(2026, 10, 24)  # Saturday morning covers Friday


def test_a_scheduled_run_that_had_its_data_is_not_repeated():
    # IB was fine: the 21:15 scheduled run already saw today's bars, so nothing is fired on top of it.
    assert due_runs(tpe(19, 21, 40), {}, {"JP": tpe(19, 17), "KR": tpe(19, 17)}, {}) == []
    assert due_runs(tpe(19, 21, 40), {}, {}, {}) == []


def test_runs_are_marked_missed_when_their_schedule_passes_without_fresh_bars():
    stale = {"JP": tpe(16, 17), "KR": tpe(16, 17)}
    fresh = {"JP": tpe(19, 17), "KR": tpe(19, 17)}
    assert automation.missed_runs(tpe(19, 21, 15), stale) == []  # Taiwan reconciliation does not wait for IB bars
    assert automation.missed_runs(tpe(19, 21, 15), fresh) == []
    assert automation.missed_runs(tpe(20, 7, 30), {"US": tpe(16, 6)}) == [US]  # Monday's New York session
    assert automation.missed_runs(tpe(20, 7, 30), {"US": tpe(20, 6)}) == []


def test_us_run_waits_for_us_bars_and_ignores_asian_markets():
    now = tpe(20, 9)
    missed = {"us": date(2026, 10, 20)}
    assert due_runs(now, {"taiwan": date(2026, 10, 20)}, {"US": tpe(20, 8, 50), "JP": tpe(19, 12)}, missed) == [US]
    assert due_runs(now, {"taiwan": date(2026, 10, 20)}, {"US": tpe(19, 18)}, missed) == []


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


def test_report_event_fires_once_for_only_explicit_taiwan_codes(tmp_path, monkeypatch):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'events.db'}"))
    monkeypatch.setenv("MARKET_ROUTINE_TAIWAN_TOKEN", "test-token")
    fired = []

    async def fake_fire(run, text):
        fired.append((run.key, text))
        return "https://claude.ai/code/event-run"

    monkeypatch.setattr(automation, "fire_routine", fake_fire)
    now = tpe(29, 21, 30).astimezone(timezone.utc)
    result = asyncio.run(automation.fire_analysis_event(
        store, event_key="report:report-123", codes=["2330", "MU-US", "3008"],
        reason="新研究報告主張已擷取", now=now,
    ))
    assert result["state"] == "fired"
    assert result["codes"] == ["2330", "3008"]
    assert "只更新這些台股" in fired[0][1]
    assert "MU-US" not in fired[0][1]
    assert asyncio.run(automation.fire_analysis_event(
        store, event_key="report:report-123", codes=["2330", "3008"],
        reason="重送不得重複觸發", now=now,
    ))["state"] == "done"
    assert len(fired) == 1


def test_report_event_without_taiwan_codes_does_not_fire(tmp_path, monkeypatch):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'events.db'}"))
    monkeypatch.setenv("MARKET_ROUTINE_TAIWAN_TOKEN", "test-token")
    fired = []
    async def fake_fire(run, text):
        fired.append(text)
        return ""
    monkeypatch.setattr(automation, "fire_routine", fake_fire)
    result = asyncio.run(automation.fire_analysis_event(
        store, event_key="report:overseas", codes=["MU-US", "6857-JP"], reason="overseas",
        now=tpe(29, 21, 30).astimezone(timezone.utc),
    ))
    assert result == {"state": "no-taiwan-codes", "codes": []}
    assert fired == []


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


def test_check_does_not_fire_or_wait_for_ib_on_weekdays(tmp_path, monkeypatch):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'fires.db'}"))
    positions = [("6857", "JP"), ("000660", "KR"), ("META", "US")]
    # 2026-10-29 is Thursday. Taiwan's weekly reconciliation is Friday and ignores overseas login state.
    logged_out = FakeSource(tpe(16, 19).astimezone(timezone.utc), positions,
                            {("6857", "JP"): tpe(16, 17), ("000660", "KR"): tpe(16, 17), ("META", "US"): tpe(17, 8)})
    status = asyncio.run(automation.check(store, logged_out, tpe(29, 21, 20).astimezone(timezone.utc)))
    assert status["ib"]["authenticated"] is False
    assert {r["key"]: r["state"] for r in status["runs"]}["taiwan"] == "no-session"


def test_a_day_with_ib_up_fires_nothing_extra(tmp_path, monkeypatch):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'fires.db'}"))
    fired = []

    async def fake_fire(run, text):
        fired.append(run.key)
        return ""

    monkeypatch.setattr(automation, "fire_routine", fake_fire)
    monkeypatch.setenv("MARKET_ROUTINE_TAIWAN_TOKEN", "test-token")
    for hour, minute in ((18, 0), (21, 20), (22, 0)):
        now = tpe(30, hour, minute).astimezone(timezone.utc)
        source = FakeSource(now - timedelta(minutes=3), [("6857", "JP")], {("6857", "JP"): tpe(30, 17)})
        status = asyncio.run(automation.check(store, source, now))
    assert fired == []
    assert {r["key"]: r["state"] for r in status["runs"]}["taiwan"] == "scheduled"  # Friday's reconciliation is handled by the routine cron


def test_stale_ib_status_does_not_block_or_fire_taiwan_reconciliation(tmp_path, monkeypatch):
    store = AutomationStore(create_engine(f"sqlite:///{tmp_path / 'fires.db'}"))
    now = tpe(30, 21, 30).astimezone(timezone.utc)
    fresh = FakeSource(now - timedelta(hours=2), [], {})
    status = asyncio.run(automation.check(store, fresh, now))
    assert status["ib"]["authenticated"] is False
    assert {r["key"]: r["state"] for r in status["runs"]}["taiwan"] == "scheduled"

    portfolio_only = FakeSource(now - timedelta(minutes=3), [("6857", "JP")], {("6857", "JP"): tpe(16, 19)},
                                market_data_at=tpe(19, 13).astimezone(timezone.utc))
    status = asyncio.run(automation.check(store, portfolio_only, now))
    assert status["ib"]["authenticated"] is False
    assert {r["key"]: r["state"] for r in status["runs"]}["taiwan"] == "scheduled"


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
