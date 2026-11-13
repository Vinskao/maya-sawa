"""2026-11-13: the macro page opens with what borrowing to invest actually costs in Taiwan.

場外 (bank loans): CBC EH45m01, the five major banks' new-loan rates by purpose, monthly.
場內 (broker margin): no official series exists; the chart's benchmark is the interbank overnight rate (CBC EG37D01, daily).
"""
import json

from maya_sawa.services import market_macro

LENDING = {"meta": {}, "data": {"dataSets": [
    # month, 購屋 amt/rate, 資本支出 amt/rate, 週轉金 amt/rate, 消費性 amt/rate, 總計 amt/rate
    ["2026M08", "57165", "2.321", "121826", "2.435", "1055372", "2.147", "9414", "2.568", "1243777", "2.187"],
    ["2026M09", "69783", "2.315", "90874", "2.477", "1156276", "2.160", "8714", "2.628", "1325647", "2.193"],
    ["bad"]]}}
INTERBANK = {"meta": {}, "data": {"dataSets": [
    ["19911001", "4.689"] + ["-"] * 18,
    ["20260929", "0.814", "0.830"] + ["-"] * 17,
    ["20260930", "-", "0.828"] + ["-"] * 17]}}


def test_parses_bank_lending_rates_by_purpose():
    rows = market_macro.parse_cbc_lending_rates(LENDING)
    assert {(r["code"], r["period"], r["value"]) for r in rows} == {
        ("TW_BANK_LOAN_RATE", "2026-08", "2.187"), ("TW_BANK_LOAN_RATE", "2026-09", "2.193"),
        ("TW_CONSUMER_LOAN_RATE", "2026-08", "2.568"), ("TW_CONSUMER_LOAN_RATE", "2026-09", "2.628"),
        ("TW_WORKING_CAPITAL_LOAN_RATE", "2026-08", "2.147"), ("TW_WORKING_CAPITAL_LOAN_RATE", "2026-09", "2.160")}


def test_parses_interbank_overnight_rate_skipping_gaps_and_old_history():
    rows = market_macro.parse_cbc_interbank_overnight(INTERBANK, since="2019-01-01")
    assert rows == [{"code": "TW_INTERBANK_OVERNIGHT", "period": "2026-09-29", "value": "0.814"}]


def test_fetch_caches_both_and_registers_codes(monkeypatch):
    payloads = {"EH45m01": LENDING, "EG37D01": INTERBANK}
    monkeypatch.setattr(market_macro, "_request_free_cached",
        lambda key, url, **kwargs: (200, json.dumps(next(p for f, p in payloads.items() if f in url)).encode()))
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *a, **k: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *a, **k: None)
    monkeypatch.setattr(market_macro, "_fetched_within", lambda *a, **k: False)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *a, **k: saved.extend(rows) or len(rows))
    assert service._fetch_cbc_borrowing_rates() == 7
    for code in ("TW_BANK_LOAN_RATE", "TW_CONSUMER_LOAN_RATE", "TW_WORKING_CAPITAL_LOAN_RATE", "TW_INTERBANK_OVERNIGHT"):
        assert code in market_macro.FREE_CACHE_CODES


def test_fetch_skips_when_fresh(monkeypatch):
    monkeypatch.setattr(market_macro, "_fetched_within", lambda *a, **k: True)
    assert market_macro.MarketMacroService()._fetch_cbc_borrowing_rates() == 0
