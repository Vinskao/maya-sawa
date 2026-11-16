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


def test_japanese_and_other_foreign_stocks_never_go_to_the_taiwan_quote_feed():
    # 6834 is a Japanese stock held through IBKR; Shioaji would look up Taiwan's 6834 and alert on the wrong company
    from maya_sawa.services.shioaji_market import ShioajiMarketService
    items = [{"code": "6834", "productType": "stock", "market": "JP"}, {"code": "2330", "productType": "stock", "market": "TW"},
             {"code": "0050", "productType": "stock"}, {"code": "AAPL", "productType": "stock", "market": "US"},
             {"code": "TXF", "productType": "futures", "market": "TW"}]
    assert [i["code"] for i in ShioajiMarketService._taiwan_only(items)] == ["2330", "0050", "TXF"]


# ---- 2026-11-16: Japanese stocks, multi-day streaks and next-day reversals ----
import asyncio

JST = ZoneInfo("Asia/Tokyo")
JP_MON_10AM = datetime(2026, 11, 16, 10, 0, tzinfo=JST)


def jq(pct, history=(), code="6834", name="精工電子", ts="2026-11-16T09:58:00+09:00"):
    return {"symbol": code, "name": name, "productType": "stock", "market": "JP", "close": 6500.0, "changePercent": pct,
            "timestamp": ts, "history": list(history)}


def test_japan_trades_9_to_1530_tokyo_time_and_taiwan_9_to_1330_taipei():
    assert ia.in_trading_hours(datetime(2026, 11, 16, 14, 0, tzinfo=JST), "JP")
    assert not ia.in_trading_hours(datetime(2026, 11, 16, 15, 31, tzinfo=JST), "JP")
    assert not ia.in_trading_hours(datetime(2026, 11, 16, 8, 59, tzinfo=JST), "JP")
    assert not ia.in_trading_hours(datetime(2026, 11, 14, 10, 0, tzinfo=JST), "JP")
    # 15:00 Tokyo = 14:00 Taipei: Japan still trading, Taiwan closed
    assert ia.in_trading_hours(datetime(2026, 11, 16, 15, 0, tzinfo=JST), "JP")
    assert not ia.in_trading_hours(datetime(2026, 11, 16, 15, 0, tzinfo=JST))
    assert ia.in_trading_hours(MON_10AM)


def test_a_japanese_stock_alerts_with_its_market_named():
    _, alerts = ia.evaluate({}, jq(5.6), JP_MON_10AM)
    assert [a["kind"] for a in alerts] == ["rise"]
    assert "6834 精工電子" in alerts[0]["title"] and "日股" in alerts[0]["title"]


def test_japanese_and_taiwanese_stocks_with_the_same_code_do_not_share_state():
    state, a1 = ia.evaluate({}, jq(5.6), JP_MON_10AM)
    state, a2 = ia.evaluate(state, {**q(5.6, symbol="6834"), "timestamp": "2026-11-16T10:00:00+08:00"}, MON_10AM)
    assert len(a1) == 1 and len(a2) == 1 and "日股" not in a2[0]["title"]


def test_japan_snapshot_date_is_checked_against_the_tokyo_date():
    _, alerts = ia.evaluate({}, jq(5.6, ts="2026-11-13T15:00:00+09:00"), JP_MON_10AM)
    assert alerts == []


def test_a_second_day_over_5_percent_in_a_row_is_called_out():
    _, alerts = ia.evaluate({}, q(5.4) | {"history": [1.0, 6.2]}, MON_10AM)
    assert len(alerts) == 1 and alerts[0]["streak"] == 2
    assert "連續 2 天" in alerts[0]["title"] and "漲超過 5%" in alerts[0]["title"] and alerts[0]["telegram"] == "attention"
    assert "+6.2%" in alerts[0]["body"] and "+5.4%" in alerts[0]["body"]


def test_longer_streaks_count_every_qualifying_day_and_stop_at_the_first_gap():
    _, alerts = ia.evaluate({}, q(-5.2) | {"history": [3.0, -5.5, -7.1, -6.0]}, MON_10AM)
    assert alerts[0]["streak"] == 4 and "連續 4 天" in alerts[0]["title"] and "跌超過 5%" in alerts[0]["title"]


def test_a_move_the_day_after_a_gap_is_not_a_streak():
    _, alerts = ia.evaluate({}, q(5.4) | {"history": [6.5, 2.0]}, MON_10AM)
    assert alerts[0].get("streak") is None and "連續" not in alerts[0]["title"]


def test_a_5_percent_move_against_yesterdays_5_percent_move_is_a_next_day_reversal():
    _, alerts = ia.evaluate({}, q(-5.3) | {"history": [0.4, 6.2]}, MON_10AM)
    assert alerts[0]["reversal"] is True and "隔日反向" in alerts[0]["title"] and alerts[0]["telegram"] == "attention"
    assert "+6.2%" in alerts[0]["body"] and "-5.3%" in alerts[0]["body"]
    _, up = ia.evaluate({}, q(5.3) | {"history": [-7.0]}, MON_10AM)
    assert up[0]["reversal"] is True


def test_a_small_yesterday_means_no_special_note_and_a_rise_stays_a_plain_update():
    _, alerts = ia.evaluate({}, q(5.4) | {"history": [4.9]}, MON_10AM)
    assert alerts[0].get("reversal") is None and alerts[0].get("streak") is None and alerts[0]["telegram"] == "update"
    _, none = ia.evaluate({}, q(5.4), MON_10AM)
    assert none[0]["telegram"] == "update"


def test_yahoo_daily_chart_gives_todays_move_and_the_completed_days_before():
    chart = {"chart": {"result": [{
        "meta": {"symbol": "6834.T", "shortName": "SEIKO ELECTRIC", "regularMarketPrice": 1155.0, "regularMarketTime": 1795051080,
                 "gmtoffset": 32400, "exchangeTimezoneName": "Asia/Tokyo"},
        "timestamp": [1794528000, 1794787200, 1794873600, 1794960000, 1795046400],  # 11/13, 11/16 .. 11/19 (JST 09:00)
        "indicators": {"quote": [{"close": [1000.0, 1050.0, 1102.5, 1100.0, 1155.0]}]}}]}}
    quote = ia.parse_yahoo_chart(chart, "6834", datetime(2026, 11, 19, 10, 0, tzinfo=JST).date())
    assert quote["market"] == "JP" and quote["symbol"] == "6834" and quote["close"] == 1155.0
    assert quote["changePercent"] == 5.0                    # 1155 vs yesterday's 1100
    assert quote["history"] == [5.0, 5.0, -0.23]            # completed days, oldest first; first candle has no prior close
    assert quote["timestamp"].startswith("2026-11-19")


def test_yahoo_chart_without_a_candle_for_today_is_a_holiday_or_not_open_yet():
    chart = {"chart": {"result": [{"meta": {"regularMarketPrice": 10}, "timestamp": [1794528000, 1794787200],
                                   "indicators": {"quote": [{"close": [10.0, 11.0]}]}}]}}
    assert ia.parse_yahoo_chart(chart, "6834", datetime(2026, 11, 19, tzinfo=JST).date()) is None
    assert ia.parse_yahoo_chart({"chart": {"result": None}}, "6834", datetime(2026, 11, 19, tzinfo=JST).date()) is None


def test_taiwan_daily_history_turns_official_closes_into_percent_moves():
    points = [{"date": "2026-11-12", "sources": {"twse:daily-price": {"close": 100.0, "change": 1.0}}},
              {"date": "2026-11-13", "sources": {"twse:daily-price": {"close": 106.0, "change": 6.0}}},
              {"date": "2026-11-16", "sources": {"twse:daily-price": {"close": 112.0, "change": 6.0}}}]  # today: excluded
    assert ia.pcts_from_points(points, "2026-11-16") == [1.01, 6.0]


def test_monitor_alerts_japanese_stocks_through_the_fetcher_and_attaches_a_streak(monkeypatch):
    sent = []
    monkeypatch.setattr(ia.telegram_notify, "send", lambda kind, title, body="": sent.append((kind, title)) or {"sent": True})
    monitor = ia.IntradayAlertMonitor(fetch_japan=lambda items, today: [jq(5.6, history=[6.0])])
    alerts = asyncio.run(monitor.check_japan([{"code": "6834", "name": "精工電子", "productType": "stock", "market": "JP"}], JP_MON_10AM))
    assert len(alerts) == 1 and alerts[0]["streak"] == 2 and sent and sent[0][0] == "attention"
    # throttled: asking again right away does not hit Yahoo again
    monitor2 = ia.IntradayAlertMonitor(fetch_japan=lambda items, today: (_ for _ in ()).throw(AssertionError("fetched twice")))
    monitor2._last_japan = JP_MON_10AM
    assert asyncio.run(monitor2.check_japan([{"code": "6834", "productType": "stock", "market": "JP"}], JP_MON_10AM)) == []


def test_monitor_outside_japan_hours_does_not_call_yahoo():
    monitor = ia.IntradayAlertMonitor(fetch_japan=lambda items, today: (_ for _ in ()).throw(AssertionError("fetched")))
    night = datetime(2026, 11, 16, 20, 0, tzinfo=JST)
    assert asyncio.run(monitor.check_japan([{"code": "6834", "productType": "stock", "market": "JP"}], night)) == []


def test_monitor_gives_taiwan_quotes_their_daily_history(monkeypatch):
    monkeypatch.setattr(ia.telegram_notify, "send", lambda *a, **k: {"sent": True})
    monitor = ia.IntradayAlertMonitor(history_taiwan=lambda code, today: [6.0])
    alerts = asyncio.run(monitor.check([q(5.5)], MON_10AM))
    assert alerts and alerts[0]["streak"] == 2
