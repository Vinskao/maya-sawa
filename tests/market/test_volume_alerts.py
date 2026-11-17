"""2026-11-16: volume alerts. A stock's trading volume is ranked against its trailing year of daily volumes; entering the top 10
or top 5 is alerted, and every price alert reports where today's and each day of this week's volume ranks, because a stock
locked at limit-up or limit-down trades very little and would otherwise look like "no volume signal".
"""
import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from maya_sawa.services import intraday_alerts as ia
from maya_sawa.services import volume_rank as vr

TZ = ZoneInfo("Asia/Taipei")
TUE_10AM = datetime(2026, 11, 17, 10, 0, tzinfo=TZ)  # this week started Monday 2026-11-16


def history(days=200, end=date(2026, 11, 13), peak=None):
    """Daily volumes, oldest first: 1,000 shares x 1..days, so rank is easy to compute by hand. Fridays and weekends are
    just dates here; `peak` overrides (date -> volume)."""
    out = []
    for i in range(days):
        day = end - timedelta(days=days - 1 - i)
        out.append([day.isoformat(), (i + 1) * 1000])
    for day, volume in (peak or {}).items():
        out.append([day, volume])
    return sorted(out)


def q(pct=0.0, volume=0, hist=None, symbol="2330", close=1000.0):
    return {"symbol": symbol, "name": "台積電", "productType": "stock", "close": close, "changePercent": pct,
            "volumeShares": volume, "volumeHistory": hist if hist is not None else history(), "timestamp": "2026-11-17T09:58:00+08:00"}


def test_rank_is_one_plus_the_number_of_larger_days():
    assert vr.rank_of(4, [5, 3, 9]) == 3
    assert vr.rank_of(10, [5, 3, 9]) == 1
    assert vr.rank_of(1, [5, 3, 9]) == 4
    assert vr.rank_of(9, [5, 3, 9]) == 1  # ties do not push it down


def test_only_the_trailing_year_counts():
    old = [["2020-01-02", 10**9]] + history(300)
    volumes = vr.trailing_volumes(old, date(2026, 11, 17))
    assert len(volumes) == vr.TRAILING_DAYS and 10**9 not in volumes


def test_trailing_window_excludes_today_so_a_day_is_not_ranked_against_itself():
    h = history(200) + [["2026-11-17", 5_000_000]]
    assert 5_000_000 not in vr.trailing_volumes(h, date(2026, 11, 17))


def test_volume_entering_the_top_10_alerts_once_then_the_top_5_alerts_once():
    state, out = {}, []
    # history volumes 1,000 .. 200,000: the 10th largest is 191,000 and the 5th largest is 196,000
    for volume in (150_000, 195_000, 195_500, 196_500, 199_000, 250_000):
        state, alerts = ia.evaluate(state, q(volume=volume), TUE_10AM)
        out += [a for a in alerts if a["kind"] == "volume"]
    assert [(a["level"], a["rank"]) for a in out] == [(10, 6), (5, 5)]


def test_a_jump_straight_into_the_top_5_reports_the_top_5_level_once():
    state, alerts = ia.evaluate({}, q(volume=300_000), TUE_10AM)
    vol = [a for a in alerts if a["kind"] == "volume"]
    assert len(vol) == 1 and vol[0]["level"] == 5 and vol[0]["rank"] == 1
    state, again = ia.evaluate(state, q(volume=320_000), TUE_10AM)
    assert [a for a in again if a["kind"] == "volume"] == []


def test_volume_alert_text_names_the_rank_and_both_cutoffs():
    _, alerts = ia.evaluate({}, q(volume=195_000), TUE_10AM)
    alert = next(a for a in alerts if a["kind"] == "volume")
    assert "2330 台積電" in alert["title"] and "前 10 大" in alert["title"] and alert["rank"] == 6
    assert "近一年" in alert["body"] and "195,000" in alert["body"]
    assert alert["telegram"] == "attention"


def test_ordinary_volume_or_too_little_history_does_not_alert():
    assert [a for a in ia.evaluate({}, q(volume=50_000), TUE_10AM)[1] if a["kind"] == "volume"] == []
    thin = history(30)
    assert [a for a in ia.evaluate({}, q(volume=10**9, hist=thin), TUE_10AM)[1] if a["kind"] == "volume"] == []
    assert [a for a in ia.evaluate({}, q(volume=0), TUE_10AM)[1] if a["kind"] == "volume"] == []


def test_a_price_alert_reports_whether_volume_is_in_the_top_10_or_5():
    _, alerts = ia.evaluate({}, q(pct=5.5, volume=50_000), TUE_10AM)
    price = next(a for a in alerts if a["kind"] == "rise")
    assert "成交量" in price["body"] and "近一年" in price["body"] and "今日第 151 名" in price["body"] and "未進前 10" in price["body"]
    _, alerts = ia.evaluate({}, q(pct=5.5, volume=300_000), TUE_10AM)
    assert "進入前 5" in next(a for a in alerts if a["kind"] == "rise")["body"]


def test_price_alert_lists_every_day_of_this_week_because_limit_days_trade_little():
    h = history(200, peak={"2026-11-16": 199_500, "2026-11-17": 2_000})  # Monday big (top 5), Tuesday tiny
    _, alerts = ia.evaluate({}, q(pct=9.9, volume=2_000, hist=h), TUE_10AM)
    body = next(a for a in alerts if a["kind"] == "rise")["body"]
    assert "本週" in body and "週一" in body and "前 5" in body
    assert "漲跌停" in body                            # a 9.9% day is probably locked: low volume is expected
    assert "週二" not in body or "今日" in body        # today is reported as 今日, not repeated


def test_this_week_summary_marks_each_day_with_its_rank():
    h = history(200, peak={"2026-11-16": 199_500})
    week = vr.week_summary(h, date(2026, 11, 17), date(2026, 11, 16), today_volume=60_000)
    assert [(d["weekday"], d["flag"]) for d in week] == [("週一", "top5"), ("週二", None)]
    assert week[0]["rank"] == 2 and week[1]["volume"] == 60_000


def test_price_alert_without_volume_data_just_omits_the_volume_line():
    quote = {**q(pct=5.5, volume=0, hist=[]), "volumeShares": None}
    _, alerts = ia.evaluate({}, quote, TUE_10AM)
    assert "成交量" not in next(a for a in alerts if a["kind"] == "rise")["body"]


def test_shioaji_volume_comes_from_amount_over_average_price_not_a_guessed_unit():
    from maya_sawa.services.shioaji_market import ShioajiMarketService
    snapshot = SimpleNamespace(close=100.0, open=99.0, high=101.0, low=98.0, change_price=1.0, change_rate=1.0, total_volume=5000,
                               volume=3, ts=1794787200, total_amount=500_000_000, average_price=100.0)
    contract = SimpleNamespace(code="2330", name="台積電")
    payload = ShioajiMarketService._snapshot_payload_from_snapshot(contract, snapshot)
    assert payload["volumeShares"] == 5_000_000          # 500,000,000 / 100 = 5,000,000 shares (5,000 lots)
    bare = SimpleNamespace(**{**snapshot.__dict__, "total_amount": 0, "average_price": 0})
    assert ShioajiMarketService._snapshot_payload_from_snapshot(contract, bare)["volumeShares"] is None


def test_yahoo_daily_chart_carries_volume_history_and_todays_running_volume():
    stamps = [1794528000, 1794787200, 1794873600]  # 11/13, 11/16, 11/17 JST 09:00
    chart = {"chart": {"result": [{"meta": {"regularMarketPrice": 110.0, "regularMarketTime": 1794877200},
                                   "timestamp": stamps,
                                   "indicators": {"quote": [{"close": [100.0, 105.0, 110.0], "volume": [1000, 2000, 1500]}]}}]}}
    quote = ia.parse_yahoo_chart(chart, "6834", date(2026, 11, 17))
    assert quote["volumeShares"] == 1500
    assert quote["volumeHistory"] == [["2026-11-13", 1000], ["2026-11-16", 2000]]


def test_volume_history_prefers_the_database_and_falls_back_to_yahoo_when_it_is_short():
    db_short = [["2026-11-12", 10]] * 90
    long_db = [["d%d" % i, 10] for i in range(vr.MIN_HISTORY_DAYS)]
    assert ia.volume_history_for("2330", date(2026, 11, 17), db=lambda c, d: long_db, yahoo=lambda c, d: [["y", 1]]) == long_db
    assert ia.volume_history_for("2330", date(2026, 11, 17), db=lambda c, d: db_short, yahoo=lambda c, d: [["y", 1]]) == [["y", 1]]
    assert ia.volume_history_for("2330", date(2026, 11, 17), db=lambda c, d: (_ for _ in ()).throw(RuntimeError("db")),
                                 yahoo=lambda c, d: [["y", 1]]) == [["y", 1]]


def test_monitor_gives_taiwan_quotes_their_volume_history(monkeypatch):
    monkeypatch.setattr(ia.telegram_notify, "send", lambda *a, **k: {"sent": True})
    monitor = ia.IntradayAlertMonitor(history_taiwan=lambda code, today: [], volume_history_taiwan=lambda code, today: history())
    quote = {k: v for k, v in q(volume=300_000).items() if k != "volumeHistory"}
    alerts = asyncio.run(monitor.check([quote], TUE_10AM))
    assert [a["kind"] for a in alerts] == ["volume"] and alerts[0]["level"] == 5


# --- 2026-11-17: the volume ranking was only sent to Telegram; stock rows never showed it. It is now a company event. ------------
def week_history(week_volumes):
    """200 days of 1,000 x 1..200 shares to 2026-11-13, then this week's days (Mon 11/16 ...) with the given volumes."""
    rows = history()
    for offset, volume in enumerate(week_volumes):
        rows.append([(date(2026, 11, 16) + timedelta(days=offset)).isoformat(), volume])
    return rows


def test_a_day_this_week_in_the_yearly_top_5_becomes_a_volume_spike_event():
    # History is 1,000 x 1..200 shares. Monday 199,000 has one larger day -> rank 2 (top 5); today's 195,000 has six above it (Monday's 199,000 is part of the window too) -> rank 7 (top 10).
    week = vr.week_summary(week_history([199_000]), date(2026, 11, 17), date(2026, 11, 16), 195_000)
    event = vr.volume_spike_event("6857", "宜特", week)
    assert event["type"] == "volume_spike" and event["code"] == "6857" and event["flag"] == "top5" and event["highlight"]
    assert event["date"] == "2026-11-17"                                    # the latest flagged day
    assert "週一第 2 名（前 5）" in event["period"] and "週二（今日）第 7 名（前 10）" in event["period"]
    assert event["days"] == [{"weekday": "週一", "rank": 2, "flag": "top5", "today": False},
                             {"weekday": "週二", "rank": 7, "flag": "top10", "today": True}]


def test_only_flagged_days_are_listed_and_ordinary_weeks_make_no_event():
    ordinary = vr.week_summary(week_history([50_000]), date(2026, 11, 17), date(2026, 11, 16), 60_000)
    assert vr.volume_spike_event("2330", "台積電", ordinary) is None
    mixed = vr.week_summary(week_history([199_000, 20_000]), date(2026, 11, 18), date(2026, 11, 16), 30_000)
    event = vr.volume_spike_event("2330", "台積電", mixed)
    assert [day["weekday"] for day in event["days"]] == ["週一"] and "週二" not in event["period"]


def test_the_event_labels_the_strongest_day_of_the_week():
    # Monday 193,000 -> rank 8 (top 10); today's 199,500 has only the 200,000 day above it -> rank 2 (top 5): the week is top 5.
    week = vr.week_summary(week_history([193_000]), date(2026, 11, 17), date(2026, 11, 16), 199_500)
    assert vr.volume_spike_event("6857", "宜特", week)["flag"] == "top5"
    only10 = vr.week_summary(week_history([193_000]), date(2026, 11, 17), date(2026, 11, 16), 1_000)
    assert vr.volume_spike_event("6857", "宜特", only10)["flag"] == "top10"


def test_company_events_carry_the_volume_spike_for_selected_stocks_using_live_volume(monkeypatch):
    from maya_sawa.services import market_company_events as mce
    service = mce.MarketCompanyEventsService()
    async def none(*a, **k): return []
    monkeypatch.setattr(mce.market_fundamentals_service, "published_events", none)
    monkeypatch.setattr(service, "_conferences", none)
    monkeypatch.setattr(mce, "_today", lambda: date(2026, 11, 17))
    service.volume_history_source = lambda code, day: week_history([199_000]) if code == "6857" else history()
    result = asyncio.run(service.get(["6857", "2330"], live_volumes={"6857": 195_000, "2330": 10_000}))
    spikes = [event for event in result["events"] if event["type"] == "volume_spike"]
    assert [event["code"] for event in spikes] == ["6857"]
    assert result["sources"]["volume"]


def test_a_stock_without_a_year_of_volume_history_makes_no_event(monkeypatch):
    from maya_sawa.services import market_company_events as mce
    service = mce.MarketCompanyEventsService()
    async def none(*a, **k): return []
    monkeypatch.setattr(mce.market_fundamentals_service, "published_events", none)
    monkeypatch.setattr(service, "_conferences", none)
    monkeypatch.setattr(mce, "_today", lambda: date(2026, 11, 17))
    service.volume_history_source = lambda code, day: history(days=30)
    result = asyncio.run(service.get(["6857"], live_volumes={"6857": 9_999_999}))
    assert [event for event in result["events"] if event["type"] == "volume_spike"] == []


def test_live_volume_is_taken_only_from_todays_stock_quotes():
    from maya_sawa.services.market_company_events import live_volumes_from_quotes
    rows = [
        {"symbol": "6857", "productType": "stock", "volumeShares": 195_000, "timestamp": "2026-11-17T10:58:00+08:00"},
        {"symbol": "2330", "productType": "stock", "volumeShares": 9_000_000, "timestamp": "2026-11-14T13:30:00+08:00"},   # last Friday's
        {"symbol": "TXFK6", "productType": "futures", "volumeShares": 5, "timestamp": "2026-11-17T10:58:00+08:00"},
        {"symbol": "2317", "productType": "stock", "volumeShares": None, "timestamp": "2026-11-17T10:58:00+08:00"},
        {"symbol": "3008", "productType": "stock", "volumeShares": 1_000, "timestamp": "not a time"},
    ]
    assert live_volumes_from_quotes(rows, date(2026, 11, 17)) == {"6857": 195_000}
