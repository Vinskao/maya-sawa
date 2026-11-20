import json

import pytest

from maya_sawa.services import market_macro


def test_dgbas_skips_unpublished_months_reported_as_zero(monkeypatch):
    payload = {"data": {
        "dataSets": [{"series": {"0": {"observations": {"0": ["11655"], "1": ["0"], "2": [""]}}}}],
        "structure": {"dimensions": {"observation": [{"values": [
            {"id": "2026-M8"}, {"id": "2026-M9"}, {"id": "2026-M10"}]}]}},
    }}
    monkeypatch.setattr(market_macro, "_request_free_cached", lambda key, url: (200, json.dumps(payload).encode()))
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_dgbas_employment()
    counts = {(row["code"], row["period"]) for row in saved if row["code"] in ("TW_EMPLOYED", "TW_UNEMPLOYED")}
    assert counts == {("TW_EMPLOYED", "2026-08"), ("TW_UNEMPLOYED", "2026-08")}
    assert all(row["period"] == "2026-08" for row in saved)


def test_yahoo_markets_cache_gold_yen_and_dollar_index_daily_closes(monkeypatch):
    def chart(zone, closes):
        return {"chart": {"result": [{"meta": {"exchangeTimezoneName": zone},
            "timestamp": [1791950400, 1792036800, 1792123200],
            "indicators": {"quote": [{"close": closes}]}}]}}
    payloads = {"GC=F": chart("America/New_York", [4012.5, None, 4050.25]),
                "JPY=X": chart("Europe/London", [157.5, 157.9, 158.006]),
                "DX-Y.NYB": chart("America/New_York", [None, 101.2, 101.796]),
                "^VIX": chart("America/Chicago", [16.234, 17.9, None]),  # 2026-10-29: VIX shares a chart with Taiwan's margin ratio
                # 2026-11-03: FRED's WTI (DCOILWTICO) trails by about a week, so the oil node reads Yahoo's front-month futures
                "CL=F": chart("America/New_York", [61.2, None, 63.447])}
    calls = []

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        symbol = next(symbol for symbol in payloads if market_macro.urllib.parse.quote(symbol) in url)
        calls.append((symbol, extra_headers))
        return 200, json.dumps(payloads[symbol]).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    assert service._fetch_yahoo_markets() == 11
    by_code = {}
    for row in saved:
        by_code.setdefault(row["code"], []).append(row["value"])
    assert by_code == {"COMEX_GOLD_USD": [4012.5, 4050.25], "USD_JPY": [157.5, 157.9, 158.01], "US_DOLLAR_INDEX": [101.2, 101.8],
                       "US_VIX": [16.23, 17.9], "WTI_CRUDE_USD": [61.2, 63.45]}
    assert all(len(row["period"]) == 10 for row in saved)
    assert {symbol for symbol, _ in calls} == set(payloads)
    assert all("Mozilla" in headers["User-Agent"] for _, headers in calls)


def test_yahoo_markets_keeps_other_symbols_when_one_fails(monkeypatch):
    good = {"chart": {"result": [{"meta": {}, "timestamp": [1792123200], "indicators": {"quote": [{"close": [158.0]}]}}]}}

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        if "GC%3DF" in url:
            raise RuntimeError("upstream_http_429")
        return 200, json.dumps(good).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    assert service._fetch_yahoo_markets() == 8  # Gold failed; every other symbol still saved.
    assert {row["code"] for row in saved} == {"USD_JPY", "US_DOLLAR_INDEX", "US_VIX", "EUR_USD", "WTI_CRUDE_USD", "USD_KRW", "US_SP500", "US_SOX"}


def test_yahoo_markets_skips_series_restored_fresh_after_a_restart(monkeypatch):
    # 2026-10-29: every deploy restarts the pod and reruns the refresh, so a day of deploys spent the 12-call Yahoo
    # budget refetching gold, yen and dollar closes that the restart had just restored. VIX, added that day, never
    # got a call ("yahoo_daily_budget_exhausted") and its chart stayed empty. Fresh series are now skipped.
    cache = market_macro.LocalTTLCache(max_entries=32)
    fresh = market_macro.datetime.now(market_macro.UTC).isoformat()
    for code in ("COMEX_GOLD_USD", "USD_JPY", "US_DOLLAR_INDEX"):
        cache.set(f"series:{code}", {"code": code, "fetchedAt": fresh, "history": []}, 3600)
    monkeypatch.setattr(market_macro, "_macro_local_cache", cache)
    good = {"chart": {"result": [{"meta": {}, "timestamp": [1792123200], "indicators": {"quote": [{"close": [17.1]}]}}]}}
    urls, reservations = [], []

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        urls.append(url)
        return 200, json.dumps(good).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: reservations.append(args) or 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    assert service._fetch_yahoo_markets() == 6  # The remaining series were never cached.
    assert [row["code"] for row in saved] == ["US_VIX", "EUR_USD", "WTI_CRUDE_USD", "USD_KRW", "US_SP500", "US_SOX"]
    assert len(urls) == 6 and "%5EVIX" in urls[0] and "EURUSD" in urls[1] and "CL%3DF" in urls[2] and "KRW%3DX" in urls[3]
    assert len(reservations) == 1

    # Once these are cached too, a further restart spends nothing.
    for code in ("US_VIX", "EUR_USD", "WTI_CRUDE_USD", "USD_KRW", "US_SP500", "US_SOX"):
        cache.set(f"series:{code}", {"code": code, "fetchedAt": fresh, "history": []}, 3600)
    assert service._fetch_yahoo_markets() == 0
    assert len(urls) == 6 and len(reservations) == 1


def _sdmx(periods, values):
    return {"data": {
        "dataSets": [{"series": {"0": {"observations": {str(index): [value] for index, value in enumerate(values)}}}}],
        "structure": {"dimensions": {"observation": [{"values": [{"id": period} for period in periods]}]}},
    }}


def _stub_source_budget(monkeypatch):
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)


def test_dgbas_employment_adds_taiwan_unemployment_rate(monkeypatch):
    payloads = {"/1.1.1.M": _sdmx(["2026-M7", "2026-M8", "2026-M9"], ["11651", "11655", "0"]),
                "/2.1.1.M": _sdmx(["2026-M7", "2026-M8", "2026-M9"], ["409", "411", "0"])}
    monkeypatch.setattr(market_macro, "_request_free_cached",
        lambda key, url, **kwargs: (200, json.dumps(next(p for s, p in payloads.items() if s in url)).encode()))
    _stub_source_budget(monkeypatch)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_dgbas_employment()
    rates = {row["period"]: row["value"] for row in saved if row["code"] == "TW_UNEMPLOYMENT_RATE"}
    # DGBAS definition: unemployed / (employed + unemployed); unpublished months (0) are skipped.
    assert rates == {"2026-07": 3.39, "2026-08": 3.41}


def test_dgbas_prices_cache_taiwan_cpi_and_ppi(monkeypatch):
    payloads = {"A030101015": _sdmx(["2025-M9", "2026-M9"], ["109.82", "112.82"]),
                "A030701015": _sdmx(["2025-M9", "2026-M9"], ["107.53", "127.03"])}
    seen = []

    def fake_request(key, url, **kwargs):
        table = next(table for table in payloads if table in url)
        seen.append(table)
        return 200, json.dumps(payloads[table]).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    _stub_source_budget(monkeypatch)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    assert service._fetch_taiwan_prices() == 4
    assert {(row["code"], row["period"], row["value"]) for row in saved} == {
        ("TW_CPI", "2025-09", "109.82"), ("TW_CPI", "2026-09", "112.82"),
        ("TW_PPI", "2025-09", "107.53"), ("TW_PPI", "2026-09", "127.03")}
    assert sorted(seen) == ["A030101015", "A030701015"]
    assert "TW_CPI" in market_macro.FREE_CACHE_CODES and "TW_UNEMPLOYMENT_RATE" in market_macro.FREE_CACHE_CODES


@pytest.mark.parametrize(("code", "symbol"), [("US_SP500", "^GSPC"), ("US_SOX", "^SOX")])
def test_us_index_closes_also_store_bias_series(monkeypatch, code, symbol):
    stamps = [1792123200 + 16 * 3600 + day * 86400 for day in range(245)]
    closes = [100.0] * 243 + [None, 120.0]
    payload = {"chart": {"result": [{"meta": {"exchangeTimezoneName": "America/New_York"}, "timestamp": stamps,
                                 "indicators": {"quote": [{"close": closes}]}}]}}

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        if symbol.replace("^", "%5E") not in url: raise RuntimeError("not_this_test")
        return 200, json.dumps(payload).encode()

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro, "_fetched_within", lambda *args: False)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_yahoo_markets()
    assert market_macro.YAHOO_SYMBOLS[code] == symbol
    for days, expected in [(20, "18.81"), (60, "19.60"), (120, "19.80"), (240, "19.90")]:
        bias_code = f"{code}_BIAS_{days}"
        assert bias_code in market_macro.FREE_CACHE_CODES
        bias = [row for row in saved if row["code"] == bias_code]
        assert len(bias) == 244 - days + 1
        assert bias[-1]["value"] == expected


def test_dgbas_requests_four_years_of_months(monkeypatch):
    # 2026-11-20 integrity scan: Taiwan employment started 2024-10 (two years), short of the three-year bar.
    urls = []
    empty = {"data": {"dataSets": [{"series": {}}], "structure": {"dimensions": {"observation": [{"values": []}]}}}}
    monkeypatch.setattr(market_macro, "_request_free_cached", lambda key, url: urls.append(url) or (200, json.dumps(empty).encode()))
    monkeypatch.setattr(market_macro, "_fetched_within", lambda *args: False)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    service = market_macro.MarketMacroService()
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: len(rows))
    try: service._fetch_dgbas_employment()
    except Exception: pass
    year = market_macro.date.today().year
    assert urls and any(f"startTime={year - 4}-M" in url or f"startTime={year - 3}-M1&" in url for url in urls)
