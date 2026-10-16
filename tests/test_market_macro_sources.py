import json

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
                "DX-Y.NYB": chart("America/New_York", [None, 101.2, 101.796])}
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
    assert service._fetch_yahoo_markets() == 7
    by_code = {}
    for row in saved:
        by_code.setdefault(row["code"], []).append(row["value"])
    assert by_code == {"COMEX_GOLD_USD": [4012.5, 4050.25], "USD_JPY": [157.5, 157.9, 158.01], "US_DOLLAR_INDEX": [101.2, 101.8]}
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
    assert service._fetch_yahoo_markets() == 2
    assert {row["code"] for row in saved} == {"USD_JPY", "US_DOLLAR_INDEX"}


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
