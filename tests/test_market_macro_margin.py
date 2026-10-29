"""Taiwan listed-market margin maintenance ratio (台股大盤融資維持率), computed from TWSE's public tables.

TWSE publishes no market-wide ratio, so it is the usual estimate: collateral value (each stock's margin balance in lots
x 1,000 shares x that day's close) / the market's margin loan balance (融資金額, NT$ thousand). Fixtures are the real
2026-10-28 MI_MARGN (selectType=ALL) and MI_INDEX (type=ALLBUT0999) responses with unused columns dropped; every row kept.
"""
import json
from datetime import date
from pathlib import Path

from maya_sawa.services import market_macro

FIXTURES = Path(__file__).parent / "fixtures" / "twse"
MARGIN = json.loads((FIXTURES / "mi_margn_2026-10-28.json").read_text(encoding="utf-8"))
PRICES = json.loads((FIXTURES / "mi_index_2026-10-28.json").read_text(encoding="utf-8"))
HOLIDAY_MARGIN = {"stat": "很抱歉，沒有符合條件的資料"}
HOLIDAY_PRICES = {"stat": "很抱歉，沒有符合條件的資料!", "type": "ALLBUT0999"}


def test_the_ratio_is_collateral_value_over_margin_loans():
    result = market_macro.margin_maintenance(MARGIN, PRICES)
    assert result["loanTwd"] == 632_299_552_000                     # 融資金額 今日餘額 632,299,552 (NT$ thousand)
    assert result["lots"] == 9_550_911                              # equals 融資(交易單位) 今日餘額
    assert round(result["ratio"], 2) == 183.26
    # Three stocks with margin balances had no close that day (00647L, 00682U, 1589: 310 lots); they are left out, not zero.
    assert result["unpricedLots"] == 310


def test_a_holiday_has_no_ratio():
    assert market_macro.margin_maintenance(HOLIDAY_MARGIN, HOLIDAY_PRICES) is None
    assert market_macro.margin_maintenance(MARGIN, HOLIDAY_PRICES) is None   # margin out before prices: wait


def test_an_incomplete_stock_table_is_rejected_instead_of_reading_low():
    half = {**MARGIN, "tables": [MARGIN["tables"][0], {**MARGIN["tables"][1], "data": MARGIN["tables"][1]["data"][:600]}]}
    assert market_macro.margin_maintenance(half, PRICES) is None


def test_backfill_fills_missing_trading_days_newest_first_and_keeps_stored_ones(monkeypatch):
    calls = []

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        calls.append(url)
        day = url.split("date=")[1][:8]
        if day == "20261028":
            return 200, json.dumps(MARGIN if "MI_MARGN" in url else PRICES, ensure_ascii=False).encode()
        return 200, json.dumps(HOLIDAY_MARGIN if "MI_MARGN" in url else HOLIDAY_PRICES, ensure_ascii=False).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_macro.time, "sleep", lambda seconds: None)
    stored = {"series:TW_MARGIN_MAINTENANCE": {"history": [{"period": "2026-10-27", "value": "180.10"}]},
              "series:TW_MARGIN_BALANCE": {"history": [{"period": "2026-10-27", "value": "6233.87"}]}}
    monkeypatch.setattr(market_macro._macro_local_cache, "get", lambda key: stored.get(key))
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_twse_margin_maintenance(today=date(2026, 10, 29), max_days=3)
    days = [url.split("date=")[1][:8] for url in calls if "MI_MARGN" in url]
    # Weekdays only, newest first, skipping 10/27 which is already stored; at most max_days attempts per run.
    assert days == ["20261029", "20261028", "20261026"]
    assert {row["period"]: row["value"] for row in saved if row["code"] == "TW_MARGIN_MAINTENANCE"} == {"2026-10-27": "180.10", "2026-10-28": "183.26"}


def test_both_series_are_defined_for_the_dashboard():
    assert market_macro.TWSE_MARGIN_SERIES["TW_MARGIN_MAINTENANCE"][1:] == ("percent", "daily")
    assert market_macro.YAHOO_SYMBOLS["US_VIX"] == "^VIX"
    assert {"TW_MARGIN_MAINTENANCE", "US_VIX"} <= market_macro.FREE_CACHE_CODES


# 2026-10-29: the owner wants margin balance, market turnover and VIX side by side as one indicator.
def test_margin_balance_is_the_market_loan_balance_in_hundred_million_twd():
    # 融資金額(仟元) 今日餘額 632,299,552 → NT$ 6,323.00 億; a holiday has none.
    assert round(market_macro.margin_loan_balance(MARGIN), 2) == 6323.00
    assert market_macro.margin_loan_balance(HOLIDAY_MARGIN) is None


def test_backfill_adds_the_balance_to_days_that_already_have_a_ratio_without_refetching_prices(monkeypatch):
    calls = []

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        calls.append(url)
        return 200, json.dumps(MARGIN if "MI_MARGN" in url else PRICES, ensure_ascii=False).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_macro.time, "sleep", lambda seconds: None)
    stored = {"series:TW_MARGIN_MAINTENANCE": {"history": [{"period": "2026-10-28", "value": "183.26"}]}}
    monkeypatch.setattr(market_macro._macro_local_cache, "get", lambda key: stored.get(key))
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_twse_margin_maintenance(today=date(2026, 10, 28), max_days=1)
    assert len(calls) == 1 and "MI_MARGN" in calls[0]
    assert {(row["code"], row["period"], row["value"]) for row in saved} == {
        ("TW_MARGIN_MAINTENANCE", "2026-10-28", "183.26"), ("TW_MARGIN_BALANCE", "2026-10-28", "6323.00")}


FMTQIK = json.loads((FIXTURES / "fmtqik_2026-10.json").read_text(encoding="utf-8"))


def test_turnover_rows_convert_roc_dates_and_yuan_to_hundred_million():
    rows = market_macro.twse_turnover_rows(FMTQIK)
    assert len(rows) == 17
    by_day = {row["period"]: row["value"] for row in rows}
    assert by_day["2026-10-28"] == "7503.41"            # 成交金額 750,340,536,882 元
    assert by_day["2026-10-01"] == "8740.46"            # 874,046,252,416 元
    assert market_macro.twse_turnover_rows(HOLIDAY_MARGIN) == []


def test_turnover_refetches_the_current_month_and_backfills_only_missing_months(monkeypatch):
    calls = []

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        calls.append(url.split("date=")[1][:8])
        return 200, json.dumps(FMTQIK if "date=20261001" in url else HOLIDAY_MARGIN, ensure_ascii=False).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_macro.time, "sleep", lambda seconds: None)
    stored = {"series:TW_MARKET_TURNOVER": {"fetchedAt": "2026-10-28T00:00:00+00:00",
              "history": [{"period": "2026-09-30", "value": "9000.00"}]}}
    monkeypatch.setattr(market_macro._macro_local_cache, "get", lambda key: stored.get(key))
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_twse_turnover(today=date(2026, 10, 29), months=3)
    assert calls == ["20261001", "20260801"]            # September is stored; October is still filling in
    values = {row["period"]: row["value"] for row in saved}
    assert values["2026-09-30"] == "9000.00" and values["2026-10-28"] == "7503.41" and len(values) == 18


def test_balance_and_turnover_are_defined_for_the_dashboard():
    assert market_macro.TWSE_MARGIN_SERIES["TW_MARGIN_BALANCE"][1:] == ("TWD 100 million", "daily")
    assert market_macro.TWSE_TURNOVER_SERIES["TW_MARKET_TURNOVER"][1:] == ("TWD 100 million", "daily")
    assert {"TW_MARGIN_BALANCE", "TW_MARKET_TURNOVER"} <= market_macro.FREE_CACHE_CODES
