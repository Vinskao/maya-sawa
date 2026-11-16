"""2026-11-16: intraday move alerts to Telegram (docs/INTRADAY_ALERTS.md).

Fires on a ±5% move against the prior close, and on a 5-point pullback from the day's high (+10% -> +5% counts) or a
5-point bounce from the day's low. Both directions are reported; each situation is reported once.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from maya_sawa.services import intraday_alerts as ia

TZ = ZoneInfo("Asia/Taipei")
MON_10AM = datetime(2026, 11, 16, 10, 0, tzinfo=TZ)


def q(pct, symbol="2330", name="台積電", close=1000.0):
    return {"symbol": symbol, "name": name, "productType": "stock", "close": close, "changePercent": pct}


def run(pcts, symbol="2330", state=None):
    """Feed a path of change-percents; return (all alert texts, final state)."""
    state, out = state or {}, []
    for pct in pcts:
        state, alerts = ia.evaluate(state, q(pct, symbol), MON_10AM)
        out += alerts
    return out, state


def kinds(alerts):
    return [a["kind"] for a in alerts]


def test_quiet_moves_do_not_alert():
    assert run([0.5, -1.2, 2.9, 1.0, -1.5, -2.0, 2.5])[0] == []


def test_a_rise_past_5_percent_alerts_once():
    alerts, _ = run([3, 5.2, 5.6, 6.1])
    assert kinds(alerts) == ["rise"] and alerts[0]["direction"] == "up"


def test_a_fall_past_5_percent_alerts_once():
    alerts, _ = run([-2, -5.1, -5.5])
    assert kinds(alerts) == ["fall"] and alerts[0]["direction"] == "down"


def test_further_levels_alert_again():
    alerts, _ = run([5.2, 7.1, 7.4, 9.0, 9.6])
    assert kinds(alerts) == ["rise", "rise", "rise"] and [a["level"] for a in alerts] == [5, 7, 9]


def test_falling_five_points_from_a_ten_percent_high_alerts():
    # +10% at the high, back to +5% = a 5-point pullback, even though the stock is still up 5% on the day
    alerts, _ = run([6, 8, 10, 9, 7, 5.0])
    pullback = [a for a in alerts if a["kind"] == "pullback"]
    assert len(pullback) == 1 and pullback[0]["high"] == 10 and pullback[0]["pct"] == 5.0


def test_pullback_is_reported_once_then_needs_another_five_points():
    alerts, _ = run([10, 5, 4.5, 4, 0.0, -0.2])
    assert [a["kind"] for a in alerts if a["kind"] == "pullback"] == ["pullback", "pullback"]


def test_a_new_high_re_arms_the_pullback():
    alerts, _ = run([10, 5, 9.9, 9.95, 4.9])
    assert kinds(alerts).count("pullback") == 2


def test_bouncing_five_points_from_a_ten_percent_low_alerts():
    alerts, _ = run([-6, -8, -10, -7, -5.0])
    assert [a["kind"] for a in alerts if a["kind"] == "bounce"] == ["bounce"]


def test_small_swings_inside_a_quiet_day_do_not_trigger_pullback():
    assert [a for a in run([1, 2, 3, 4, 4.9, 0.0])[0] if a["kind"] == "pullback"] == []


def test_each_stock_and_each_day_has_its_own_state():
    _, state = run([5.5], symbol="2330")
    alerts, _ = run([5.5], symbol="2454", state=state)
    assert kinds(alerts) == ["rise"]
    tomorrow = datetime(2026, 11, 17, 10, 0, tzinfo=TZ)
    state, alerts = ia.evaluate(state, q(5.5), tomorrow)
    assert kinds(alerts) == ["rise"]


def test_only_trading_hours_of_stocks_count():
    saturday = datetime(2026, 11, 14, 10, 0, tzinfo=TZ)
    before_open = datetime(2026, 11, 16, 8, 30, tzinfo=TZ)
    after_close = datetime(2026, 11, 16, 14, 30, tzinfo=TZ)
    assert not any(ia.in_trading_hours(t) for t in (saturday, before_open, after_close))
    assert ia.in_trading_hours(MON_10AM) and ia.in_trading_hours(datetime(2026, 11, 16, 13, 30, tzinfo=TZ))


def test_futures_and_rows_without_a_price_are_ignored():
    state, alerts = ia.evaluate({}, {**q(9.0), "productType": "futures"}, MON_10AM)
    assert alerts == []
    state, alerts = ia.evaluate({}, {**q(9.0), "close": 0}, MON_10AM)
    assert alerts == []


def test_a_stale_snapshot_from_an_earlier_day_is_ignored():
    # a weekday market holiday: Shioaji still returns yesterday's snapshot
    stale = {**q(8.0), "timestamp": "2026-11-13T13:30:00+08:00"}
    assert ia.evaluate({}, stale, MON_10AM)[1] == []
    fresh = {**q(8.0), "timestamp": "2026-11-16T09:58:00+08:00"}
    assert [a["kind"] for a in ia.evaluate({}, fresh, MON_10AM)[1]] == ["rise"]


def test_message_names_the_stock_and_the_numbers():
    alerts, _ = run([10, 5.0])
    pull = next(a for a in alerts if a["kind"] == "pullback")
    assert "2330 台積電" in pull["title"] and "回落" in pull["title"]
    assert "+10.0%" in pull["body"] and "+5.0%" in pull["body"]
    rise = run([5.3])[0][0]
    assert "上漲" in rise["title"] and "+5.3%" in rise["body"]
    fall = run([-5.3])[0][0]
    assert "下跌" in fall["title"] and "-5.3%" in fall["body"]


def test_rises_are_updates_and_drops_need_attention():
    assert run([5.3])[0][0]["telegram"] == "update"
    assert run([-5.3])[0][0]["telegram"] == "attention"
    assert next(a for a in run([10, 5])[0] if a["kind"] == "pullback")["telegram"] == "attention"


def test_notify_sends_every_alert_and_survives_a_failing_send(monkeypatch):
    sent = []

    def fake_send(kind, title, body=""):
        sent.append((kind, title))
        if len(sent) == 1:
            raise RuntimeError("telegram down")
        return {"sent": True}

    monkeypatch.setattr(ia.telegram_notify, "send", fake_send)
    alerts, _ = run([10, 5.0])
    ia.notify(alerts)
    assert len(sent) == len(alerts) >= 2


# ---- scope: current holdings + everything held or traded since Monday of this week (2026-11-16) ----
import json
from datetime import timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from maya_sawa.databases import market_dashboard_db as mdb


def test_the_week_starts_on_monday_taipei_midnight():
    assert ia.week_start(datetime(2026, 11, 18, 10, 0, tzinfo=TZ)) == datetime(2026, 11, 16, 0, 0, tzinfo=TZ)
    assert ia.week_start(datetime(2026, 11, 16, 9, 5, tzinfo=TZ)) == datetime(2026, 11, 16, 0, 0, tzinfo=TZ)
    assert ia.week_start(datetime(2026, 11, 22, 23, 0, tzinfo=TZ)) == datetime(2026, 11, 16, 0, 0, tzinfo=TZ)


def test_symbols_held_in_any_snapshot_this_week_are_in_scope():
    engine = create_engine("sqlite://")
    mdb.MarketDashboardSnapshot.metadata.create_all(engine, tables=[mdb.MarketDashboardSnapshot.__table__])
    db = mdb.MarketDashboardDatabase.__new__(mdb.MarketDashboardDatabase)
    db.engine, db.sessions = engine, sessionmaker(bind=engine)

    ids = iter(range(1, 99))  # SQLite does not autoincrement BigInteger

    def snap(at, items):
        with db.sessions.begin() as s:
            s.add(mdb.MarketDashboardSnapshot(id=next(ids), source="shioaji", snapshot_at=at, created_at=at,
                                              positions=json.dumps([{"code": c, "name": c, "productType": t} for c, t in items])))

    snap(datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc), [("1101", "stock")])                   # last week: out
    snap(datetime(2026, 11, 17, 2, 0, tzinfo=timezone.utc), [("2330", "stock"), ("TXF", "futures")])  # sold since
    snap(datetime(2026, 11, 18, 2, 0, tzinfo=timezone.utc), [("2454", "stock")])
    got = db.traded_since(datetime(2026, 11, 16, 0, 0, tzinfo=TZ))
    assert sorted((i["code"], i["productType"]) for i in got) == [("2330", "stock"), ("2454", "stock"), ("TXF", "futures")]
    assert db.traded_since(datetime(2026, 12, 1, tzinfo=TZ)) == []
