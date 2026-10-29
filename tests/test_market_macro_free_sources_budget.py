"""2026-10-29: the macro source status showed PMI, WorldBank, DGBAS and DGBASPrices all "daily budget exhausted".

- PMI and WorldBank had never succeeded, so each refresh (and each deploy restart) spent a call on a request that
  could not work: CIER removed the NMI table from /pmi-trend/ (the parser demanded both), and worldbank.org answers
  urllib's default agent with 403.
- DGBAS and DGBASPrices refetched monthly series that a restart had just restored, as Yahoo did before e9193e1.

Fixtures are the real 2026-10-29 responses, trimmed (see the comment at the top of each HTML file).
"""
from datetime import timedelta
from pathlib import Path

import pytest

from maya_sawa.services import market_macro

FIXTURES = Path(__file__).parent / "fixtures" / "macro"


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache(max_entries=64))
    reservations = []
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: reservations.append(args[0]) or 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    svc = market_macro.MarketMacroService()
    svc.saved, svc.reservations = [], reservations
    monkeypatch.setattr(svc, "_cache_free_series", lambda rows, *args, **kwargs: svc.saved.extend(rows) or len(rows))
    return svc


def test_pmi_keeps_taiwan_manufacturing_pmi_when_the_nmi_table_is_gone(service, monkeypatch):
    html = (FIXTURES / "cier_pmi_trend_2026-10-29.html").read_bytes()
    monkeypatch.setattr(market_macro, "_request_free_cached", lambda key, url, **kwargs: (200, html))
    assert service._fetch_pmi_series() == 12
    pmi = {row["period"]: row["value"] for row in service.saved if row["code"] == "TW_PMI"}
    assert len(pmi) == 12 and pmi["2026-09"] == "63.4" and pmi["2025-10"] == "50.3"
    # The industry columns (化學暨生技醫療 56.2 …) are not the headline index.
    assert {row["code"] for row in service.saved} == {"TW_PMI"}


def test_pmi_still_fails_loudly_when_the_manufacturing_table_disappears(service, monkeypatch):
    monkeypatch.setattr(market_macro, "_request_free_cached", lambda key, url, **kwargs: (200, b"<html><table><tr><td>x</td></tr></table></html>"))
    with pytest.raises(RuntimeError, match="cier_pmi_table_missing"):
        service._fetch_pmi_series()


def test_world_bank_gold_sends_a_browser_agent_to_both_hosts(service, monkeypatch):
    page = (FIXTURES / "worldbank_commodity_markets_2026-10-29.html").read_bytes()
    workbook = (FIXTURES / "worldbank_cmo_monthly_trimmed_2026-10-29.xlsx").read_bytes()
    agents = []

    def fake_request(key, url, ttl_seconds=0, extra_headers=None):
        agent = (extra_headers or {}).get("User-Agent", "")
        agents.append(agent)
        if "Mozilla" not in agent:
            raise RuntimeError("upstream_http_403")  # what worldbank.org and thedocs.worldbank.org return to urllib
        return 200, workbook if url.endswith(".xlsx") else page

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    assert service._fetch_world_bank_gold() == 6
    gold = {row["period"]: row["value"] for row in service.saved}
    assert gold["2026-09"] == "4319" and gold["1960-01"] == "35"
    assert len(agents) == 2


@pytest.mark.parametrize("fetch, codes, source", [
    ("_fetch_dgbas_employment", ("TW_EMPLOYED", "TW_UNEMPLOYED"), "DGBAS"),
    ("_fetch_taiwan_prices", ("TW_CPI", "TW_PPI"), "DGBASPrices"),
])
def test_dgbas_skips_monthly_series_restored_fresh_after_a_restart(service, monkeypatch, fetch, codes, source):
    requests = []
    monkeypatch.setattr(market_macro, "_request_free_cached", lambda key, url, **kwargs: requests.append(url) or (200, b"{}"))
    fresh = (market_macro.datetime.now(market_macro.UTC) - timedelta(hours=1)).isoformat()
    for code in codes:
        market_macro._macro_local_cache.set(f"series:{code}", {"code": code, "fetchedAt": fresh, "history": [{"period": "2026-09", "value": "1"}]}, 3600)
    assert getattr(service, fetch)() == 0
    assert requests == [] and service.reservations == []

    # A series fetched 13 hours ago is due again, and the call is charged to its own budget.
    old = (market_macro.datetime.now(market_macro.UTC) - timedelta(hours=13)).isoformat()
    market_macro._macro_local_cache.set(f"series:{codes[0]}", {"code": codes[0], "fetchedAt": old, "history": []}, 3600)
    try: getattr(service, fetch)()
    except Exception: pass  # the stub payload is empty; only the reservation matters here
    assert service.reservations == [source]
