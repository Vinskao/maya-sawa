"""2026-11-16: the TAIEX gets the same intraday alerts as a stock, with index-sized thresholds (2/3/5%, 2-point swing)."""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from maya_sawa.services import intraday_alerts as ia

TZ = ZoneInfo("Asia/Taipei")
TUE_10AM = datetime(2026, 11, 17, 10, 0, tzinfo=TZ)


def taiex(pct, history=None):
    return {"symbol": "TAIEX", "name": "加權指數", "productType": "index", "market": "TW", "close": 41040.08, "changePercent": pct,
            "history": history or [], "timestamp": "2026-11-17T09:58:00+08:00",
            "levels": ia.INDEX_LEVELS, "swing": ia.INDEX_SWING, "bigDay": ia.INDEX_BIG_DAY}


def test_a_two_percent_index_move_alerts_but_a_stock_at_two_percent_does_not():
    _, alerts = ia.evaluate({}, taiex(-2.4), TUE_10AM)
    assert [a["kind"] for a in alerts] == ["fall"] and "TAIEX 加權指數" in alerts[0]["title"] and "超過 2%" in alerts[0]["body"]
    stock = {**taiex(-2.4), "symbol": "2330", "productType": "stock", "levels": None, "swing": None, "bigDay": None}
    assert ia.evaluate({}, stock, TUE_10AM)[1] == []


def test_index_levels_alert_once_each_and_a_swing_from_the_high_alerts():
    state, out = {}, []
    for pct in (2.1, 2.2, 3.3, 0.9):
        state, alerts = ia.evaluate(state, taiex(pct), TUE_10AM)
        out += [a["kind"] for a in alerts]
    assert out == ["rise", "rise", "pullback"]


def test_streak_note_uses_the_index_big_day_threshold():
    _, alerts = ia.evaluate({}, taiex(-3.5, history=[-3.2, -4.0]), TUE_10AM)
    assert "連續 3 天" in alerts[0]["title"] and "超過 3%" in alerts[0]["title"]


def test_monitor_polls_the_index_at_most_once_a_minute_and_only_in_trading_hours(monkeypatch):
    monkeypatch.setattr(ia.telegram_notify, "send", lambda *a, **k: {"sent": True})
    calls = []
    monitor = ia.IntradayAlertMonitor(fetch_index=lambda today: calls.append(today) or taiex(-5.5))
    first = asyncio.run(monitor.check_index(TUE_10AM))
    assert {a["kind"] for a in first} == {"fall"} and len(calls) == 1
    assert asyncio.run(monitor.check_index(TUE_10AM.replace(second=30))) == [] and len(calls) == 1
    assert asyncio.run(monitor.check_index(TUE_10AM.replace(hour=15))) == [] and len(calls) == 1
