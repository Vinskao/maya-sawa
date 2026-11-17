"""2026-11-17: the banner must describe TODAY (live), say whether a big move came with heavy volume, and flag a falling market P/E."""
from datetime import date

from maya_sawa.services import market_status as ms

TODAY = date(2026, 11, 17)
FMTQIK = {"stat": "OK", "data": [
    ["115/11/13", "12,361,786,586", "951,580,008,082", "4,257,328", "43,675.12", "583.25"],
    ["115/11/16", "14,120,171,417", "903,115,129,889", "6,662,374", "41,040.08", "-2,635.04"],
    ["115/11/17", "14,661,802,735", "1,012,867,829,864", "5,860,477", "40,092.11", "-947.97"],
]}
MIS = {"msgArray": [{"d": "20261117", "t": "13:33:00", "z": "40092.11", "y": "41040.08", "h": "41533.84", "l": "39786.45"}]}


def sessions(closes, value=800.0, start=date(2026, 10, 1)):
    """Finished sessions on consecutive weekdays with a flat trading value (NT$ 100m)."""
    from datetime import timedelta
    rows, day = [], start
    for close in closes:
        while day.weekday() > 4: day += timedelta(days=1)
        rows.append({"date": day.isoformat(), "close": close, "value": value})
        day += timedelta(days=1)
    return rows


def test_fmtqik_rows_become_dated_closes_and_trading_value_in_100_million():
    rows = ms.parse_fmtqik(FMTQIK)
    assert rows[-1] == {"date": "2026-11-17", "close": 40092.11, "value": 10128.68}
    assert ms.parse_fmtqik({"stat": "no"}) == []


def test_mis_index_gives_the_live_price_and_yesterdays_close():
    assert ms.parse_mis_index(MIS) == {"date": "2026-11-17", "time": "13:33:00", "price": 40092.11, "prev": 41040.08}
    assert ms.parse_mis_index({"msgArray": []}) is None
    assert ms.parse_mis_index({"msgArray": [{"d": "20261117", "z": "-", "y": "41040.08"}]}) is None   # nothing traded yet


def test_nothing_is_said_when_today_has_no_data_yet():
    days = sessions([100.0] * 25)
    assert ms.build_status(days, None, [], date(2099, 1, 1))["items"] == []


def test_a_big_drop_today_on_heavy_volume_is_one_alert_with_the_volume_ratio():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 96.0, "value": 1200.0}]   # -4%, 1.5x the 800 average
    items = ms.build_status(days, None, [], TODAY)["items"]
    assert items[0]["level"] == "alert"
    assert "大跌" in items[0]["zh"] and "4.00%" in items[0]["zh"]
    assert "爆量" in items[0]["zh"] and "1.5 倍" in items[0]["zh"]
    assert "plunge" in items[0]["en"].lower() or "fell" in items[0]["en"].lower()


def test_a_big_drop_on_thin_volume_says_so():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 96.0, "value": 500.0}]
    assert "量縮" in ms.build_status(days, None, [], TODAY)["items"][0]["zh"]


def test_a_small_move_without_unusual_volume_is_silent():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.5, "value": 820.0}]
    assert ms.build_status(days, None, [], TODAY)["items"] == []


def test_during_the_session_the_live_price_is_used_and_volume_is_left_out():
    days = sessions([100.0] * 24, start=date(2026, 10, 12))   # the last finished day is before today
    live = {"date": TODAY.isoformat(), "time": "10:30:00", "price": 96.0, "prev": days[-1]["close"]}
    item = ms.build_status(days, live, [], TODAY)["items"][0]
    assert item["level"] == "alert" and "盤中" in item["zh"] and "倍" not in item["zh"]


def test_yesterdays_move_is_never_the_headline():
    days = sessions([100.0] * 23) + [{"date": "2026-11-16", "close": 94.0, "value": 1500.0}]   # -6% yesterday, nothing today
    assert ms.build_status(days, None, [], TODAY)["items"] == []


def test_three_down_days_in_a_row_are_flagged_with_the_total_drop():
    days = sessions([100.0] * 21 + [99.0, 98.0]) + [{"date": TODAY.isoformat(), "close": 97.0, "value": 800.0}]
    streak = [item for item in ms.build_status(days, None, [], TODAY)["items"] if item["id"] == "streak"][0]
    assert "連跌 3" in streak["zh"] and "3.00%" in streak["zh"]


def test_market_pe_falling_for_days_with_a_widening_drop_is_flagged():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.0, "value": 800.0}]
    pe = [("2026-11-12", 24.0), ("2026-11-13", 23.5), ("2026-11-16", 22.5), (TODAY.isoformat(), 20.5)]
    item = [i for i in ms.build_status(days, None, pe, TODAY)["items"] if i["id"] == "pe"][0]
    assert "連降 3" in item["zh"] and "加快" in item["zh"] and item["level"] == "warn"


def test_market_pe_falling_at_a_steady_pace_is_info_and_a_rise_says_nothing():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.0, "value": 800.0}]
    steady = [("2026-11-12", 24.0), ("2026-11-13", 23.0), ("2026-11-16", 22.0), (TODAY.isoformat(), 21.0)]
    item = ms._pe_item(steady, TODAY)
    assert item["level"] == "info" and "加快" not in item["zh"]
    rising = [("2026-11-13", 20.0), ("2026-11-16", 21.0), (TODAY.isoformat(), 22.0)]
    assert [i for i in ms.build_status(days, None, rising, TODAY)["items"] if i["id"] == "pe"] == []


def test_a_pe_series_that_stops_before_today_is_not_reported():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.0, "value": 800.0}]
    old = [("2026-11-10", 24.0), ("2026-11-11", 23.0), ("2026-11-12", 22.0), ("2026-11-13", 20.0)]
    assert [i for i in ms.build_status(days, None, old, TODAY)["items"] if i["id"] == "pe"] == []


def test_the_week_total_is_added_for_a_big_week_and_items_are_ordered_by_severity():
    # Friday 11/13 close 100, then Mon 94, Tue today 92: the week is -8%.
    days = sessions([100.0] * 22, start=date(2026, 10, 14)) + [
        {"date": "2026-11-13", "close": 100.0, "value": 800.0}, {"date": "2026-11-16", "close": 94.0, "value": 800.0},
        {"date": TODAY.isoformat(), "close": 92.0, "value": 800.0}]
    items = ms.build_status(days, None, [], TODAY)["items"]
    ids = [item["id"] for item in items]
    assert "week" in ids and ids[0] == "move"
    assert "本週累計" in [item for item in items if item["id"] == "week"][0]["zh"]


def test_every_item_says_which_way_the_market_went():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 96.0, "value": 1200.0}]
    assert {item["dir"] for item in ms.build_status(days, None, [], TODAY)["items"]} == {"down"}
    up = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 104.0, "value": 1200.0}]
    assert ms.build_status(up, None, [], TODAY)["items"][0]["dir"] == "up"


# 2026-11-17: at night the market that is moving is the TAIEX futures night session, so day and night are told apart.
from datetime import datetime, timedelta, timezone

TPE = timezone(timedelta(hours=8))


def txf(stamp, price=40263.0, pct=0.63):
    return {"close": price, "changePercent": pct, "timestamp": stamp}


def test_a_fresh_night_session_quote_is_recognised_and_a_day_session_one_is_not():
    now = datetime(2026, 11, 17, 20, 10, tzinfo=TPE)
    assert ms.parse_txf_night(txf("2026-11-17T20:03:40+08:00"), now) == {"price": 40263.0, "pct": 0.63, "time": "20:03"}
    assert ms.parse_txf_night(txf("2026-11-17T11:03:40+08:00"), datetime(2026, 11, 17, 11, 5, tzinfo=TPE)) is None   # day session
    assert ms.parse_txf_night(txf("2026-11-17T20:03:40+08:00"), datetime(2026, 11, 17, 21, 30, tzinfo=TPE)) is None  # over 30 minutes old
    assert ms.parse_txf_night(None, now) is None
    assert ms.parse_txf_night(txf("2026-11-18T02:10:00+08:00"), datetime(2026, 11, 18, 2, 12, tzinfo=TPE))["pct"] == 0.63   # after midnight is still night


def test_a_big_night_move_is_its_own_item_labelled_night_session():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.2, "value": 800.0}]   # a calm day session
    night = {"price": 40263.0, "pct": -2.4, "time": "20:03"}
    items = ms.build_status(days, None, [], TODAY, night)["items"]
    assert [item["id"] for item in items] == ["night"]
    assert items[0]["level"] == "alert" and items[0]["dir"] == "down"
    assert "夜盤" in items[0]["zh"] and "-2.40%" in items[0]["zh"] and "night session" in items[0]["en"]


def test_a_small_night_move_alone_stays_silent_but_rides_along_when_the_banner_is_showing():
    calm = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.2, "value": 800.0}]
    small = {"price": 40100.0, "pct": 0.3, "time": "20:03"}
    assert ms.build_status(calm, None, [], TODAY, small)["items"] == []
    big_day = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 96.0, "value": 1200.0}]
    ids = [item["id"] for item in ms.build_status(big_day, None, [], TODAY, small)["items"]]
    assert ids[0] == "move" and "night" in ids


def test_the_day_session_item_says_day_session_and_the_night_move_works_before_the_day_opens():
    big_day = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 96.0, "value": 1200.0}]
    assert "日盤" in ms.build_status(big_day, None, [], TODAY)["items"][0]["zh"]
    # 03:00 the next morning: no day-session data for the new date yet, only the night session.
    early = ms.build_status(big_day, None, [], date(2026, 11, 18), {"price": 39000.0, "pct": -2.5, "time": "03:00"})
    assert [item["id"] for item in early["items"]] == ["night"]


# 2026-11-17: U.S. context on the same bar: the Philadelphia semiconductor index (SOX) and the VIX with its run of rises.
def us_bars(closes, start=date(2026, 11, 2)):
    from datetime import timedelta
    rows, day = [], start
    for close in closes:
        while day.weekday() > 4: day += timedelta(days=1)
        rows.append({"date": day.isoformat(), "close": close})
        day += timedelta(days=1)
    return rows


def test_yahoo_chart_becomes_dated_closes_in_new_york_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    stamp = int(datetime(2026, 11, 13, 16, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
    payload = {"chart": {"result": [{"timestamp": [stamp, stamp + 86400], "indicators": {"quote": [{"close": [5000.5, None]}]}}]}}
    assert ms.parse_yahoo_closes(payload) == [{"date": "2026-11-13", "close": 5000.5}]
    assert ms.parse_yahoo_closes({}) == []


def test_a_big_sox_drop_is_an_item_with_a_link_and_the_us_date():
    sox = us_bars([5000.0, 5000.0, 5000.0, 4800.0])   # -4% on 11/05
    items = ms.us_items(sox, [], date(2026, 11, 6))
    item = items[0]
    assert item["id"] == "sox" and item["level"] == "alert" and item["dir"] == "down"
    assert "費城半導體" in item["zh"] and "4.00%" in item["zh"] and "11/05" in item["zh"]
    assert item["href"] == "/stocks/"


def test_sox_down_three_days_is_a_streak_and_a_calm_sox_says_nothing():
    streak = [i for i in ms.us_items(us_bars([5000.0, 4990.0, 4980.0, 4970.0]), [], date(2026, 11, 6)) if i["id"] == "sox-streak"]
    assert streak and "連跌 3" in streak[0]["zh"]
    assert ms.us_items(us_bars([5000.0, 5005.0, 5010.0, 5015.0]), [], date(2026, 11, 6)) == []


def test_vix_rising_for_days_and_into_the_fear_zone_is_one_item_with_the_run_length():
    vix = us_bars([18.0, 19.0, 21.0, 23.0, 27.0])
    item = ms.us_items([], vix, date(2026, 11, 6))[0]
    assert item["id"] == "vix" and item["dir"] == "down" and item["level"] == "warn"
    assert "連漲 4" in item["zh"] and "27.0" in item["zh"] and "恐慌" in item["zh"]
    assert item["href"] == "/macro/#macro-volatility"
    assert ms.us_items([], us_bars([18.0, 17.5, 17.8, 17.0]), date(2026, 11, 6)) == []
    assert ms.us_items([], us_bars([20.0, 21.0, 25.0, 33.0]), date(2026, 11, 6))[0]["level"] == "alert"


def test_us_data_older_than_a_long_weekend_is_not_reported():
    sox = us_bars([5000.0, 5000.0, 5000.0, 4800.0])   # last bar 11/05
    assert ms.us_items(sox, [], date(2026, 11, 12)) == []


def test_us_items_join_the_banner_and_can_speak_alone_before_taiwan_trades():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.2, "value": 800.0}]   # a calm Taiwan day
    us = ms.us_items(us_bars([5000.0, 5000.0, 5000.0, 4800.0], start=date(2026, 11, 11)), [], TODAY)
    assert [item["id"] for item in ms.build_status(days, None, [], TODAY, None, us)["items"]] == ["sox"]
    assert [item["id"] for item in ms.build_status(days, None, [], date(2026, 11, 18), None, us)["items"]] == ["sox"]   # no Taiwan data yet today


def test_items_link_to_the_page_that_shows_them():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 96.0, "value": 1200.0}]
    pe = [("2026-11-12", 24.0), ("2026-11-13", 23.5), ("2026-11-16", 22.5), (TODAY.isoformat(), 20.5)]
    links = {item["id"]: item["href"] for item in ms.build_status(days, None, pe, TODAY)["items"]}
    assert links["move"] == "/stocks/" and links["pe"] == "/macro/#macro-leverage"


# 2026-11-17: the bar has one row for Taiwan and one for the U.S.; the U.S. row says whether the session is live.
def test_every_item_belongs_to_the_taiwan_or_the_us_row():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 96.0, "value": 1200.0}]
    pe = [("2026-11-12", 24.0), ("2026-11-13", 23.5), ("2026-11-16", 22.5), (TODAY.isoformat(), 20.5)]
    us = ms.us_items(us_bars([5000.0, 5000.0, 5000.0, 4800.0], start=date(2026, 11, 11)) , us_bars([18.0, 19.0, 21.0, 23.0, 27.0], start=date(2026, 11, 10)), TODAY)
    groups = {item["id"]: item["group"] for item in ms.build_status(days, None, pe, TODAY, {"price": 1.0, "pct": 0.2, "time": "20:00"}, us)["items"]}
    assert groups["move"] == groups["pe"] == groups["week"] == groups["night"] == "tw"
    assert groups["sox"] == groups["vix"] == "us"


def test_the_us_text_says_live_during_the_us_session_and_close_otherwise():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    sox = us_bars([5000.0, 5000.0, 5000.0, 4800.0], start=date(2026, 11, 11))   # last bar 11/16
    ny = ZoneInfo("America/New_York")
    live = ms.us_items(sox, [], date(2026, 11, 17), datetime(2026, 11, 16, 11, 0, tzinfo=ny))[0]
    assert "盤中" in live["zh"] and "intraday" in live["en"]
    closed = ms.us_items(sox, [], date(2026, 11, 17), datetime(2026, 11, 16, 17, 0, tzinfo=ny))[0]
    assert "收盤" in closed["zh"] and "close" in closed["en"]
    before_open = ms.us_items(sox, [], date(2026, 11, 17), datetime(2026, 11, 17, 7, 0, tzinfo=ny))[0]
    assert "收盤" in before_open["zh"]   # the bar is yesterday's finished session


# 2026-11-17: the bar is only for a heavy-volume or big-swing event; a quiet day shows nothing at all.
def test_calm_info_lines_alone_never_make_a_banner():
    calm = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.2, "value": 800.0}]
    steady_pe = [("2026-11-12", 24.0), ("2026-11-13", 23.0), ("2026-11-16", 22.0), (TODAY.isoformat(), 21.0)]   # info level only
    assert ms.build_status(calm, None, steady_pe, TODAY, {"price": 40100.0, "pct": 0.4, "time": "20:00"})["items"] == []


def test_heavy_volume_alone_is_an_event_even_when_the_index_barely_moved():
    days = sessions([100.0] * 24) + [{"date": TODAY.isoformat(), "close": 100.4, "value": 1300.0}]   # +0.4% on 1.6x volume
    items = ms.build_status(days, None, [], TODAY)["items"]
    assert [item["id"] for item in items] == ["volume"] and items[0]["level"] == "warn"


# 2026-11-17: once the U.S. session has closed it is yesterday's news, so the SOX line is the week so far.
def test_a_closed_us_session_reports_the_week_so_far_against_last_fridays_close():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    sox = us_bars([5000.0, 5100.0, 4900.0, 4800.0], start=date(2026, 11, 12))   # Thu, Fri, Mon 11/16 ... bars: 11/12, 11/13, 11/16, 11/17
    sox = sox[:3] + []   # Thu 11/12, Fri 11/13, Mon 11/16 = 4900
    ny = ZoneInfo("America/New_York")
    item = ms.us_items(sox, [], date(2026, 11, 17), datetime(2026, 11, 17, 7, 0, tzinfo=ny))[0]
    assert item["id"] == "sox" and item["dir"] == "down"
    assert "本週累計下跌 3.92%" in item["zh"] and "5,100→4,900" in item["zh"] and "11/16" in item["zh"]   # vs Friday's 5,100
    assert "this week" in item["en"]
