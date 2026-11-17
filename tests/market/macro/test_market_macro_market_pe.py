"""2026-11-17: Taiwan market P/E, computed from TWSE's per-stock P/E table (no official market-wide series exists)."""
from maya_sawa.services import market_macro

# BWIBBU_d fields: code, name, close, yield, dividend year, P/E, P/B, report period
PAYLOAD = {"stat": "OK", "date": "20261113", "data": [
    ["1101", "A", "20.00", "1", 114, "10.00", "1", "115/3"],   # cap 2,000 -> earnings 200
    ["1102", "B", "10.00", "1", 114, "20.00", "1", "115/3"],   # cap 3,000 -> earnings 150
    ["1103", "C", "50.00", "0", 114, "", "1", "115/3"],        # loss-making: no P/E, left out
    ["1104", "D", "30.00", "0", 114, "5.00", "1", "115/3"],    # no share count known: left out
]}
SHARES = {"1101": 100, "1102": 300, "1103": 100}


def test_market_pe_is_a_series_in_the_free_cache():
    assert market_macro.TWSE_MARKET_PE_SERIES["TW_MARKET_PE"][1:] == ("times", "daily")
    assert "TW_MARKET_PE" in market_macro.FREE_CACHE_CODES


def test_market_pe_is_total_market_cap_over_total_earnings():
    # (2000 + 3000) / (200 + 150) = 14.2857
    assert market_macro.market_pe(PAYLOAD, SHARES) == 14.29


def test_market_pe_is_none_when_nothing_can_be_weighted():
    assert market_macro.market_pe({"stat": "很抱歉，沒有符合條件的資料!"}, SHARES) is None
    assert market_macro.market_pe(PAYLOAD, {}) is None


def test_share_counts_come_from_the_company_basic_data():
    rows = [{"公司代號": "1101", "已發行普通股數或TDR原股發行股數": "7523181742"}, {"公司代號": "xx", "已發行普通股數或TDR原股發行股數": ""}]
    assert market_macro.parse_twse_share_counts(rows) == {"1101": 7523181742}


def test_new_days_are_computed_and_merged_into_the_stored_history(monkeypatch):
    monkeypatch.setattr(market_macro, "_fetched_within", lambda *a, **k: False)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *a, **k: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *a, **k: None)
    monkeypatch.setattr(market_macro, "_pe_days_without_data", set())
    old = {"history": [{"period": "2026-01-05", "value": "18.5"}]}
    monkeypatch.setattr(market_macro._macro_local_cache, "get", lambda key: old if key == "series:TW_MARKET_PE" else None)
    service = market_macro.MarketMacroService()
    monkeypatch.setattr(service, "_twse_share_counts", lambda: SHARES)
    monkeypatch.setattr(service, "_twse_pe_table", lambda day: PAYLOAD if day.isoformat() == "2026-11-13" else {"stat": "no"})
    monkeypatch.setattr(market_macro, "_today_taipei", lambda: market_macro.date(2026, 11, 17))
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *a, **k: saved.extend(rows) or len(rows))
    service._fetch_twse_market_pe()
    assert [(row["period"], row["value"]) for row in saved] == [("2026-01-05", "18.5"), ("2026-11-13", 14.29)]
    assert {row["code"] for row in saved} == {"TW_MARKET_PE"}
