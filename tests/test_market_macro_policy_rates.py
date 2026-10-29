"""2026-10-29: the owner wants Taiwan, Korea, Japan, U.S. and euro-area policy rates on one chart, next to their
currencies, "to see where the money goes". BIS WS_CBPOL has daily policy rates for the U.S. (target-range midpoint),
euro area (deposit facility), Japan and Korea; Taiwan is not in it, so the CBC rediscount rate (step changes only) is
carried forward to every weekday. Fixture: real BIS CSV since 2026-06-01, unused columns dropped, every row kept."""
from datetime import date
from pathlib import Path

import pytest

from maya_sawa.services import market_macro

RAW = (Path(__file__).parent / "fixtures" / "macro" / "bis_cbpol_2026-06_2026-10.csv").read_bytes()


def test_bis_policy_rates_map_to_one_series_per_economy():
    rows = market_macro.parse_bis_policy_rates(RAW)
    by_code = {}
    for row in rows:
        by_code.setdefault(row["code"], {})[row["period"]] = row["value"]
    assert set(by_code) == {"POLICY_RATE_US", "POLICY_RATE_EZ", "POLICY_RATE_JP", "POLICY_RATE_KR"}
    # The BoJ moved to 1.25% on 2026-09-24, Korea to 3.00% on 2026-08-27; the U.S. value is the range midpoint.
    assert by_code["POLICY_RATE_JP"]["2026-09-23"] == "1" and by_code["POLICY_RATE_JP"]["2026-09-24"] == "1.25"
    assert by_code["POLICY_RATE_KR"]["2026-08-27"] == "3"
    assert by_code["POLICY_RATE_US"]["2026-09-17"] == "3.875"
    assert all(len(period) == 10 for codes in by_code.values() for period in codes)


def test_taiwan_rate_is_carried_forward_to_every_weekday():
    history = [{"period": "2024-03-22", "value": "2.000"}, {"period": "2026-09-19", "value": "2.125"}]
    rows = market_macro.carry_forward_weekdays("POLICY_RATE_TW", history, date(2026, 9, 17), date(2026, 9, 22))
    assert [(row["period"], row["value"]) for row in rows] == [
        ("2026-09-17", "2.000"), ("2026-09-18", "2.000"), ("2026-09-21", "2.125"), ("2026-09-22", "2.125")]
    assert market_macro.carry_forward_weekdays("POLICY_RATE_TW", [], date(2026, 9, 17), date(2026, 9, 22)) == []


def test_the_fetch_stores_five_rates_and_skips_taiwan_without_the_cbc_series(monkeypatch):
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache(max_entries=32))
    monkeypatch.setattr(market_macro, "_request_free_cached", lambda key, url, **kwargs: (200, RAW))
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_policy_rates(today=date(2026, 10, 29))
    assert {row["code"] for row in saved} == {"POLICY_RATE_US", "POLICY_RATE_EZ", "POLICY_RATE_JP", "POLICY_RATE_KR"}
    market_macro._macro_local_cache.set("series:CBC_REDISCOUNT", {"fetchedAt": "2026-10-29T00:00:00+00:00",
        "history": [{"period": "2024-03-22", "value": "2.000"}]}, 3600)
    saved.clear()
    service._fetch_policy_rates(today=date(2026, 10, 29))
    taiwan = [row for row in saved if row["code"] == "POLICY_RATE_TW"]
    assert taiwan[-1] == {"code": "POLICY_RATE_TW", "period": "2026-10-29", "value": "2.000"}
    assert len(taiwan) > 500                               # two years of weekdays


def test_policy_rates_and_euro_are_defined_for_the_dashboard():
    assert set(market_macro.POLICY_RATE_SERIES) == {"POLICY_RATE_US", "POLICY_RATE_EZ", "POLICY_RATE_JP", "POLICY_RATE_KR", "POLICY_RATE_TW"}
    assert all(spec[1:] == ("percent", "daily") for spec in market_macro.POLICY_RATE_SERIES.values())
    assert market_macro.YAHOO_SYMBOLS["EUR_USD"] == "EURUSD=X"
    assert {"POLICY_RATE_TW", "EUR_USD"} <= market_macro.FREE_CACHE_CODES
