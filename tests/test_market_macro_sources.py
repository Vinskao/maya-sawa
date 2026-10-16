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
    assert {(row["code"], row["period"]) for row in saved} == {("TW_EMPLOYED", "2026-08"), ("TW_UNEMPLOYED", "2026-08")}


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
