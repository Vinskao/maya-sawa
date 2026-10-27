"""2026-10-27: claims are tagged with plain tickers (MU, NVDA, 000660) while the dashboard and the routines use
MU-US / 6857-JP / 000660-KR, so a lookup by the dashboard code found nothing. A code lookup now also tries the plain ticker."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import market_reports


def test_variants_add_the_plain_ticker_for_market_suffixed_codes():
    assert market_reports.claim_code_variants("MU-US") == ["MU-US", "MU"]
    assert market_reports.claim_code_variants("6857-jp") == ["6857-JP", "6857"]
    assert market_reports.claim_code_variants("000660-KR") == ["000660-KR", "000660"]
    assert market_reports.claim_code_variants("2330") == ["2330"]
    assert market_reports.claim_code_variants("BRK-B") == ["BRK-B"]  # a share class, not a market suffix


def test_code_lookup_merges_both_spellings_without_duplicates(monkeypatch):
    claim = lambda n, codes: {"report_id": f"r{n}", "page": 1, "claim": f"c{n}", "codes": codes}
    stored = {"MU": [claim(1, ["MU"]), claim(2, ["MU", "NVDA"])], "MU-US": [claim(2, ["MU", "NVDA"]), claim(3, ["MU-US"])]}
    calls = []

    class Db:
        def list_claims(self, code=None, segment=None, since=None):
            calls.append(code)
            return stored.get(code, [])
    monkeypatch.setattr(market_reports, "market_reports_db", Db())
    app = FastAPI()
    app.include_router(market_reports.router)
    data = TestClient(app).get("/market/reports/claims?code=mu-us").json()
    assert calls == ["MU-US", "MU"]
    assert [row["claim"] for row in data["claims"]] == ["c2", "c3", "c1"]  # merged, no duplicate of c2
