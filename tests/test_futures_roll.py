"""TAIEX futures roll cost: next-month minus near-month spread above fair carry (台指期轉倉超額價差).

2026-10-29: the owner wants a "are futures expensive right now" gauge next to margin balance, turnover and VIX. The raw
calendar spread mostly reflects carry: interest on the near-month price minus the dividend points that go ex between
the two expiries (June to September dividends make it deeply negative every year). The excess spread removes both:

    fair  = F_near * r * days / 365 - D,   excess = (F_next - F_near) - fair

D is the index points of cash dividends going ex in (near expiry, next expiry]: cash per share x shares issued /
index divisor, where divisor = listed market value / TAIEX. Fixtures are real 2026-10 TAIFEX, TWSE and open-data
responses, trimmed as described in each file.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from maya_sawa.services import futures_roll

TWSE = Path(__file__).parent / "fixtures" / "twse"
TAIFEX = Path(__file__).parent / "fixtures" / "taifex"
SHARES = futures_roll.parse_shares(json.loads((TWSE / "t187ap03_L_2026-10-28.json").read_text(encoding="utf-8")))
PRICES = json.loads((TWSE / "mi_index_2026-10-28.json").read_text(encoding="utf-8"))
PAST = json.loads((TWSE / "twt49u_2025-10-01_2026-10-28.json").read_text(encoding="utf-8"))
UPCOMING = json.loads((TWSE / "twt48u_2026-10-29.json").read_text(encoding="utf-8"))
TX = (TAIFEX / "tx_2026-10-27_28.csv").read_text(encoding="utf-8")


def test_expiries_are_the_third_wednesday():
    assert futures_roll.third_wednesday(2026, 11) == date(2026, 11, 18)
    assert futures_roll.third_wednesday(2026, 12) == date(2026, 12, 16)
    assert futures_roll.third_wednesday(2026, 7) == date(2026, 7, 15)


def test_settlements_keep_regular_session_monthly_contracts_only():
    days = futures_roll.parse_tx_settlements(TX)
    assert set(days) == {date(2026, 10, 27), date(2026, 10, 28)}
    # 10/28: near 202611 settled 47,249, next 202612 47,371; spread orders ("202611/202612") and the after-hours session are dropped.
    assert days[date(2026, 10, 28)]["202611"] == 47249 and days[date(2026, 10, 28)]["202612"] == 47371
    assert all(len(month) == 6 for month in days[date(2026, 10, 28)])


def test_the_index_divisor_is_listed_market_value_over_taiex():
    # 1,386 closes x shares issued for every listed company = NT$154.1 trillion; TAIEX 47,035.58 on 2026-10-28.
    divisor = futures_roll.index_divisor(PRICES, SHARES)
    assert round(divisor / 1e6) == 3277


def test_dividend_points_count_cash_dividends_going_ex_inside_the_window():
    dividends = futures_roll.parse_past_dividends(PAST)
    # Only cash rows (息). 權 has no cash; 權息 mixes stock and cash in one number, so it cannot be split and is left out.
    assert {code for _, code, _ in dividends} == {"2330", "2382"}
    divisor = futures_roll.index_divisor(PRICES, SHARES)
    # 廣達 2382: NT$15.6 x 3,862,964,447 shares went ex on 7/16, inside (7/15, 8/19].
    july = futures_roll.dividend_points(dividends, SHARES, divisor, date(2026, 7, 15), date(2026, 8, 19))
    assert july == pytest.approx(15.6 * SHARES["2382"] / divisor)
    # TSMC went ex on 6/11, before the June expiry (6/17): not in the June-July window; ex on the near expiry is excluded too.
    assert futures_roll.dividend_points(dividends, SHARES, divisor, date(2026, 6, 11), date(2026, 7, 15)) == 0


def test_announced_dividends_skip_placeholders_rights_issues_and_etfs():
    upcoming = futures_roll.parse_upcoming_dividends(UPCOMING)
    codes = {code for _, code, _ in upcoming}
    assert "6165" in codes and "3563" in codes            # 浪凡 NT$5 on 11/2, 牧德 NT$1 on 10/29
    assert "2025" not in codes                             # 權: a rights issue, no cash
    assert "00940" not in codes                            # 「待公告實際收益分配金額」 placeholder
    assert next(cash for day, code, cash in upcoming if code == "6165") == 5.0


def test_excess_spread_on_2026_10_28():
    rows = futures_roll.roll_rows(futures_roll.parse_tx_settlements(TX), [], SHARES, 3.277e9, lambda day: 2.0)
    row = next(item for item in rows if item["period"] == "2026-10-28")
    # Nov (11/18) to Dec (12/16) is 28 days; no listed dividends in it. fair = 47,249 x 2% x 28/365 = 72.49.
    assert row["spread"] == 122
    assert row["fair"] == pytest.approx(72.49, abs=0.01)
    assert row["excess"] == pytest.approx(49.51, abs=0.01)
    assert row["nearMonth"] == "202611" and row["nextMonth"] == "202612"


def test_dividends_in_the_window_raise_the_excess_by_their_points():
    dividends = [(date(2026, 12, 1), "2330", 7.0)]
    rows = futures_roll.roll_rows(futures_roll.parse_tx_settlements(TX), dividends, SHARES, 3.277e9, lambda day: 2.0)
    row = next(item for item in rows if item["period"] == "2026-10-28")
    points = 7.0 * SHARES["2330"] / 3.277e9
    assert row["dividendPoints"] == pytest.approx(points)
    assert row["excess"] == pytest.approx(49.51 + points, abs=0.01)


def test_a_day_without_a_next_month_settlement_is_skipped():
    days = {date(2026, 10, 28): {"202611": 47249.0}}
    assert futures_roll.roll_rows(days, [], SHARES, 3.277e9, lambda day: 2.0) == []


def test_the_service_backfills_missing_months_and_stores_spread_and_excess(monkeypatch):
    from maya_sawa.services import market_macro
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache(max_entries=64))
    market_macro._macro_local_cache.set("series:CBC_REDISCOUNT", {"code": "CBC_REDISCOUNT", "fetchedAt": "2026-10-29T00:00:00+00:00",
        "history": [{"period": "2024-03-22", "value": "2.000"}]}, 3600)
    market_macro._macro_local_cache.set("series:TX_CALENDAR_SPREAD", {"code": "TX_CALENDAR_SPREAD", "fetchedAt": "2026-10-28T00:00:00+00:00",
        "history": [{"period": "2026-09-30", "value": "160.00"}]}, 3600)
    gets, posts = [], []

    def fake_get(key, url, ttl_seconds=0, extra_headers=None):
        gets.append(url)
        if "t187ap03_L" in url:
            return 200, (TWSE / "t187ap03_L_2026-10-28.json").read_bytes()
        if "MI_INDEX" in url:
            return 200, json.dumps(PRICES if "20261028" in url else {"stat": "很抱歉，沒有符合條件的資料!"}, ensure_ascii=False).encode()
        if "TWT49U" in url:
            return 200, json.dumps(PAST, ensure_ascii=False).encode()
        return 200, json.dumps(UPCOMING, ensure_ascii=False).encode()

    def fake_taifex(start, end):
        posts.append((start, end))
        return TX if start.month == 10 else TX.splitlines()[0] + "\n"

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_get)
    monkeypatch.setattr(market_macro, "_taifex_tx_csv", fake_taifex)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_macro.time, "sleep", lambda seconds: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_tx_roll_spread(today=date(2026, 10, 29), months=3)
    # October is refetched (still filling in); September is stored; August has nothing stored, so it is backfilled.
    assert [(start.isoformat(), end.isoformat()) for start, end in posts] == [("2026-10-01", "2026-10-29"), ("2026-08-01", "2026-08-31")]
    by = {(row["code"], row["period"]): row["value"] for row in saved}
    assert by[("TX_CALENDAR_SPREAD", "2026-10-28")] == "122.00"
    assert by[("TX_CALENDAR_SPREAD", "2026-09-30")] == "160.00"            # kept from the stored history
    assert float(by[("TX_ROLL_EXCESS_SPREAD", "2026-10-28")]) == pytest.approx(49.5, abs=0.1)


def test_the_service_waits_for_the_policy_rate(monkeypatch):
    from maya_sawa.services import market_macro
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache(max_entries=8))
    with pytest.raises(RuntimeError, match="cbc_rediscount_rate_missing"):
        market_macro.MarketMacroService()._fetch_tx_roll_spread(today=date(2026, 10, 29))


def test_roll_series_are_defined_for_the_dashboard():
    from maya_sawa.services import market_macro
    assert market_macro.TX_ROLL_SERIES["TX_ROLL_EXCESS_SPREAD"][1:] == ("TAIEX points", "daily")
    assert market_macro.TX_ROLL_SERIES["TX_CALENDAR_SPREAD"][1:] == ("TAIEX points", "daily")
    assert {"TX_ROLL_EXCESS_SPREAD", "TX_CALENDAR_SPREAD"} <= market_macro.FREE_CACHE_CODES
