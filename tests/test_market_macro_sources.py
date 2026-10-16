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
