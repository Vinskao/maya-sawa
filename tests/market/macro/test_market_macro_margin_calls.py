"""2026-11-17: margin-call accounts (整戶維持率低於 130% 的戶數) from the TWSE 臺股儀表板, drawn with margin balance and ratio."""
import json
from pathlib import Path

from maya_sawa.services import market_macro

RAW = (Path(__file__).parents[2] / "fixtures/macro/twse_margin_calls_trend.json").read_bytes()
PAYLOAD = json.loads(RAW)


def test_margin_call_accounts_are_a_daily_free_series():
    assert market_macro.TWSE_MARGIN_CALL_SERIES["TW_MARGIN_CALL_ACCOUNTS"][1:] == ("accounts", "daily")
    assert "TW_MARGIN_CALL_ACCOUNTS" in market_macro.FREE_CACHE_CODES


def test_trend_rows_become_iso_dated_account_counts():
    rows = market_macro.parse_twse_margin_calls(PAYLOAD)
    assert len(rows) == len(PAYLOAD["data"])
    first = PAYLOAD["data"][0]
    assert rows[0] == {"code": "TW_MARGIN_CALL_ACCOUNTS",
                       "period": f"{first['date'][:4]}-{first['date'][4:6]}-{first['date'][6:]}", "value": first["belowAccNum"]}
    assert market_macro.parse_twse_margin_calls({"stat": "很抱歉，沒有符合條件的資料!"}) == []


def test_new_days_are_merged_into_the_stored_history_so_it_keeps_growing(monkeypatch):
    monkeypatch.setattr(market_macro, "_request_free_cached", lambda *a, **k: (200, RAW))
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *a, **k: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *a, **k: None)
    monkeypatch.setattr(market_macro, "_fetched_within", lambda *a, **k: False)
    old = {"history": [{"period": "2026-01-05", "value": "88"}]}
    monkeypatch.setattr(market_macro._macro_local_cache, "get", lambda key: old if key == "series:TW_MARGIN_CALL_ACCOUNTS" else None)
    saved = []
    service = market_macro.MarketMacroService()
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *a, **k: saved.extend(rows) or len(rows))
    service._fetch_twse_margin_calls()
    periods = [row["period"] for row in saved]
    assert periods[0] == "2026-01-05" and len(periods) == len(PAYLOAD["data"]) + 1
