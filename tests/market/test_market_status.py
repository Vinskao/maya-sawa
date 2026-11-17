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
    item = [i for i in ms.build_status(days, None, steady, TODAY)["items"] if i["id"] == "pe"][0]
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
