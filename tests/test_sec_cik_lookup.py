"""2026-10-29: SEC financials were collected only for META and LITE because the ticker-to-CIK map was hard-coded.
SEC publishes the full map (https://www.sec.gov/files/company_tickers.json, about 10,400 tickers), so any U.S. holding
is resolved from it. Fixture: real entries from the 2026-10-29 file."""
import asyncio
import json
from pathlib import Path

from maya_sawa.services import overseas_financials as source

TICKERS = json.loads((Path(__file__).parent / "fixtures" / "sec_company_tickers_2026-10-29.json").read_text(encoding="utf-8"))


def test_tickers_resolve_to_ten_digit_ciks():
    assert source.resolve_sec_cik("NVDA", TICKERS) == "0001045810"
    assert source.resolve_sec_cik("mu", TICKERS) == "0000723125"
    assert source.resolve_sec_cik("BRK.B", TICKERS) == "0001067983"     # SEC writes share classes with a dash
    assert source.resolve_sec_cik("NOPE", TICKERS) is None


def test_a_holding_outside_the_old_map_is_collected(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from maya_sawa.databases.ibkr_research_db import IbkrResearchDatabase
    from maya_sawa.services.ibkr_research import IbkrResearchCollector
    monkeypatch.setattr(source, "_sec_ticker_cache", {})
    raw = {"cik": 1045810, "entityName": "NVIDIA CORP", "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        {"start": "2026-05-01", "end": "2026-07-31", "val": 100, "filed": "2026-08-27", "form": "10-Q"}]}}}}}
    calls = []

    class Response:
        def __init__(self, body): self.body = body
        def raise_for_status(self): pass
        def json(self): return self.body

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            calls.append(url)
            return Response(TICKERS if url.endswith("company_tickers.json") else raw)

    monkeypatch.setattr(source.httpx, "AsyncClient", Client)
    db = IbkrResearchDatabase(engine=create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}))
    collector = IbkrResearchCollector(db=db)
    asyncio.run(source.collect_sec_financials(collector, "NVDA", "US", 4815747))
    assert calls == ["https://www.sec.gov/files/company_tickers.json", "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"]
    assert db.latest("NVDA", "US", "financials")["payload"]["quarterly"][0]["revenue"] == 100
    # The ticker file is fetched once and reused for the next holding.
    asyncio.run(source.collect_sec_financials(collector, "NOPE", "US", 1))
    assert calls.count("https://www.sec.gov/files/company_tickers.json") == 1
