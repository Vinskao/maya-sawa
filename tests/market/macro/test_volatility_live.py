"""2026-11-16: Taiwan VIX (TAIFEX 臺指選擇權波動率指數) and U.S. VIX as live volatility charts at the top of the macro page.

Fixtures are copied from the live sources: TAIFEX's monthly daily-close file (Big5 text), TAIFEX MIS getQuoteDetail for
TAIWANVIX, and Yahoo's one-minute ^VIX chart.
"""
from datetime import datetime, timezone

from maya_sawa.services import market_macro, volatility

MONTHLY = (
    "日期\t時間(時/分/秒/一毫秒)\t臺指選擇權波動率指數\t收盤前1分鐘均值\r\n"
    "--------\t-------------------\t--------------------\t-------------------\r\n"
    "20261102\t13450000\t\t\t31.30\t\t31.28\r\n"
    "20261103\t13450000\t\t\t36.83\t\t36.83\r\n"
    "20261113\t13450000\t\t\t37.84\t\t37.84\r\n"
)

TAIFEX_QUOTE = {"RtCode": "0", "RtMsg": "", "RtData": {"QuoteList": [{
    "Status": "PT", "COpenPrice": "40.83", "CHighPrice": "45.42", "CLowPrice": "40.83", "CLastPrice": "44.61",
    "CRefPrice": "37.84", "CDate": "20261116", "CTime": "122830"}]}}

YAHOO_VIX = {"chart": {"result": [{"meta": {
    "symbol": "^VIX", "regularMarketPrice": 19.3, "regularMarketTime": 1794604501, "regularMarketDayHigh": 20.92,
    "regularMarketDayLow": 17.64, "chartPreviousClose": 18.7, "previousClose": 18.7}}]}}


def test_monthly_file_gives_the_official_daily_close():
    rows = volatility.parse_taifex_vix_monthly(MONTHLY)
    assert rows == [{"code": "TW_VIX", "period": "2026-11-02", "value": "31.28"},
                    {"code": "TW_VIX", "period": "2026-11-03", "value": "36.83"},
                    {"code": "TW_VIX", "period": "2026-11-13", "value": "37.84"}]


def test_monthly_file_that_is_really_an_error_page_gives_nothing():
    assert volatility.parse_taifex_vix_monthly("<html>查無資料</html>") == []


def test_taiwan_vix_quote_has_the_day_range_and_the_move_from_the_prior_close():
    live = volatility.parse_taifex_vix_quote(TAIFEX_QUOTE)
    assert (live["value"], live["open"], live["high"], live["low"], live["previousClose"]) == (44.61, 40.83, 45.42, 40.83, 37.84)
    assert live["change"] == 6.77 and live["changePercent"] == 17.89
    assert live["asOf"] == "2026-11-16T12:28:30+08:00" and live["date"] == "2026-11-16"


def test_a_taiwan_vix_quote_without_a_price_is_none():
    assert volatility.parse_taifex_vix_quote({"RtCode": "0", "RtData": {"QuoteList": [{"CLastPrice": ""}]}}) is None
    assert volatility.parse_taifex_vix_quote({"RtCode": "1"}) is None


def test_us_vix_quote_from_yahoo():
    live = volatility.parse_yahoo_vix(YAHOO_VIX)
    assert (live["value"], live["high"], live["low"], live["previousClose"]) == (19.3, 20.92, 17.64, 18.7)
    assert live["change"] == 0.6 and live["changePercent"] == 3.21
    assert live["asOf"].startswith("2026-11-12T") or live["asOf"].startswith("2026-11-13T")  # Chicago close of that session
    assert volatility.parse_yahoo_vix({"chart": {"result": None}}) is None


def test_history_keeps_what_was_stored_and_lets_new_rows_win():
    stored = [{"period": "2026-07-01", "value": "20.00"}, {"period": "2026-11-13", "value": "37.00"}]
    merged = volatility.merge_history(stored, [{"code": "TW_VIX", "period": "2026-11-13", "value": "37.84"},
                                               {"code": "TW_VIX", "period": "2026-11-16", "value": "40.00"}])
    assert merged == [{"code": "TW_VIX", "period": "2026-07-01", "value": "20.00"},
                      {"code": "TW_VIX", "period": "2026-11-13", "value": "37.84"},
                      {"code": "TW_VIX", "period": "2026-11-16", "value": "40.00"}]


def test_live_readings_are_cached_for_half_a_minute_and_a_failing_source_is_null():
    calls = {"tw": 0, "us": 0}

    def tw():
        calls["tw"] += 1
        return volatility.parse_taifex_vix_quote(TAIFEX_QUOTE)

    def us():
        calls["us"] += 1
        raise RuntimeError("yahoo blocked")

    now = [datetime(2026, 11, 16, 4, 28, tzinfo=timezone.utc)]
    live = volatility.VolatilityLive(fetch_taiwan=tw, fetch_us=us, clock=lambda: now[0])
    first = live.get()
    assert first["TW_VIX"]["value"] == 44.61 and first["US_VIX"] is None
    live.get()
    assert calls == {"tw": 1, "us": 1}
    now[0] = datetime(2026, 11, 16, 4, 29, tzinfo=timezone.utc)
    live.get()
    assert calls == {"tw": 2, "us": 2}


def test_the_taiwan_vix_series_is_kept_in_the_free_series_cache():
    assert "TW_VIX" in market_macro.FREE_CACHE_CODES
    assert market_macro.TW_VIX_SERIES["TW_VIX"][2] == "daily"


# ---- 2026-11-16: VIX futures (Cboe settlement) and the VIXY overnight stand-in ----
from datetime import date

SETTLEMENT = (
    "Product,Symbol,Expiration Date,Price\n"
    "VX,VX35/U6,2026-09-02,17.2528\n"
    "VX,VX36/U6,2026-09-09,17.2528\n"
    "VX,VX/U6,2026-09-16,17.4000\n"
    "VX,VX/V6,2026-10-21,18.1000\n"
    "VX,VX/X6,2026-11-18,19.2000\n"
)


def test_front_month_is_the_nearest_standard_monthly_not_a_weekly():
    row = volatility.parse_cboe_settlement(SETTLEMENT, date(2026, 9, 1))
    assert row == {"code": "VIX_FUT_FRONT", "period": "2026-09-01", "value": "17.40", "contract": "VX/U6", "expiry": "2026-09-16"}


def test_after_expiry_the_next_monthly_is_the_front_month():
    assert volatility.parse_cboe_settlement(SETTLEMENT, date(2026, 9, 17))["contract"] == "VX/V6"
    assert volatility.parse_cboe_settlement(SETTLEMENT, date(2026, 9, 16))["contract"] == "VX/U6"  # expiry day itself still settles


def test_settlement_file_without_prices_gives_nothing():
    assert volatility.parse_cboe_settlement("Product,Symbol,Expiration Date,Price\n", date(2026, 11, 15)) is None
    assert volatility.parse_cboe_settlement("<html>nope</html>", date(2026, 11, 15)) is None


def test_a_settlement_file_identical_to_the_previous_day_is_a_holiday_repeat():
    rows = volatility.settlement_rows({date(2026, 11, 12): SETTLEMENT, date(2026, 11, 13): SETTLEMENT.replace("19.2000", "19.3000"),
                                      date(2026, 11, 16): SETTLEMENT.replace("19.2000", "19.3000")})
    assert [(r["period"], r["value"]) for r in rows] == [("2026-11-12", "19.20"), ("2026-11-13", "19.30")]


def _vixy(ts_closes, regular=(1000, 2000), prev=17.51, close=17.94):
    stamps = [t for t, _ in ts_closes]
    return {"chart": {"result": [{
        "meta": {"symbol": "VIXY", "regularMarketPrice": close, "chartPreviousClose": prev,
                 "currentTradingPeriod": {"regular": {"start": regular[0], "end": regular[1]}}},
        "timestamp": stamps, "indicators": {"quote": [{"close": [c for _, c in ts_closes]}]}}]}}


def test_vixy_after_hours_is_measured_against_the_regular_close_and_yesterdays_close():
    live = volatility.parse_yahoo_vixy(_vixy([(900, 17.6), (1500, 17.94), (2500, 18.54), (2600, None)]))
    assert live["value"] == 18.54 and live["session"] == "post"
    assert live["regularClose"] == 17.94 and live["changeFromClose"] == 0.6 and live["changeFromClosePercent"] == 3.34
    assert live["previousClose"] == 17.51 and live["changePercent"] == 5.88


def test_vixy_sessions():
    assert volatility.parse_yahoo_vixy(_vixy([(900, 17.7)]))["session"] == "pre"
    assert volatility.parse_yahoo_vixy(_vixy([(1500, 17.7)]))["session"] == "regular"
    assert volatility.parse_yahoo_vixy({"chart": {"result": None}}) is None


def test_live_endpoint_carries_the_vix_futures_stand_in_and_a_failing_one_is_null():
    live = volatility.VolatilityLive(fetch_taiwan=lambda: None, fetch_us=lambda: None,
                                     fetch_futures=lambda: (_ for _ in ()).throw(RuntimeError("yahoo")))
    assert live.get()["VIX_FUT_PROXY"] is None
    ok = volatility.VolatilityLive(fetch_taiwan=lambda: None, fetch_us=lambda: None, fetch_futures=lambda: {"value": 18.54})
    assert ok.get()["VIX_FUT_PROXY"] == {"value": 18.54}


def test_front_month_settlement_series_is_kept_in_the_free_series_cache():
    assert "VIX_FUT_FRONT" in market_macro.FREE_CACHE_CODES
    assert market_macro.VIX_FUTURES_SERIES["VIX_FUT_FRONT"][2] == "daily"
