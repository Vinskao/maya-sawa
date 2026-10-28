"""An SEC filing URL becomes several reports (one per chosen section, split into parts), like an uploaded PDF report."""
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.databases.market_reports_db import MarketReportsDatabase
from maya_sawa.services import sec_filings as sec

URL = "https://www.sec.gov/Archives/edgar/data/2130357/000162828026067168/anthropicpbc-sx1.htm"


def para(text, n=1):
    return "".join(f"<p>{text} {i}.</p>" for i in range(n))


def filing(summary_n=3, risk_n=3):
    toc = "".join(f"<div>{name}</div>" for name in [
        "Select Defined Terms", "Prospectus Summary", "Risk Factors", "Use of Proceeds", "Capitalization",
        "Management’s Discussion and Analysis of Financial Condition and Results of Operations", "Business", "Management",
        "Index to Consolidated Financial Statements"])
    return f"""<html><head><title>Anthropic, PBC - S-1 (Q2)</title></head><body>
<div>As filed with the Securities and Exchange Commission on October 26, 2026.</div>
<div>FORM S-1</div><div>Anthropic, PBC</div><div>(Exact name of registrant as specified in its charter)</div>
{toc}
<p>See “Risk Factors” and “Business” for details.</p>
<div>Table of Contents</div><div>Prospectus Summary</div>{para("Summary fact about the business and compute", summary_n)}
<div>Table of Contents</div><div>Risk Factors</div>{para("Risk about capacity and customers", risk_n)}
<div>Table of Contents</div><div>Use of Proceeds</div>{para("We intend to use the proceeds for compute")}
<div>Table of Contents</div><div>Capitalization</div>{para("Capitalization table")}
<div>Table of Contents</div><div>Management’s Discussion and Analysis of </div><div>Financial Condition and Results of Operations </div>{para("Revenue grew and gross margin changed", 2)}
<div>Table of Contents</div><div>Business</div>{para("We sell models through API and apps", 2)}
<div>Table of Contents</div><div>Management</div>{para("Directors and officers")}
</body></html>"""


def test_reads_the_title_the_filing_date_and_the_form():
    meta = sec.filing_meta(filing(), URL)
    assert meta == {"entity": "Anthropic, PBC", "form": "S-1", "filed": date(2026, 10, 26), "title": "Anthropic, PBC S-1"}


def test_finds_the_body_of_each_section_not_the_contents_page_or_cross_references():
    sections = {name: text for name, text in sec.split_sections(sec.filing_text(filing()))}
    assert list(sections)[:3] == ["Select Defined Terms", "Prospectus Summary", "Risk Factors"] or "Prospectus Summary" in sections
    assert sections["Prospectus Summary"].startswith("Summary fact about the business and compute 0.")
    assert "Risk about capacity" in sections["Risk Factors"] and "Summary fact" not in sections["Risk Factors"]
    mdna = sections["Management’s Discussion and Analysis of Financial Condition and Results of Operations"]
    assert mdna.startswith("Revenue grew") and "Directors and officers" not in sections["Business"]
    assert sections["Business"].startswith("We sell models") and "Capitalization table" in sections["Capitalization"]


def test_plans_parts_for_the_chosen_sections_capping_risk_factors_and_splitting_long_ones():
    text = sec.filing_text(filing(summary_n=40, risk_n=40))
    parts = sec.plan_parts(sec.split_sections(text), max_chars=600, caps={"Risk Factors": 1000})
    names = [(part["section"], part["index"], part["total"]) for part in parts]
    assert {name for name, _, _ in names} == {"Prospectus Summary", "Risk Factors", "Use of Proceeds",
        "Management’s Discussion and Analysis of Financial Condition and Results of Operations", "Business"}   # Capitalization / Management are not wanted
    risk = [part for part in parts if part["section"] == "Risk Factors"]
    assert sum(len(part["text"]) for part in risk) <= 1000 + 200 and "excerpt" in risk[-1]["text"].lower()   # capped, and says so
    assert all(len(part["text"]) <= 700 for part in parts)
    assert [part["index"] for part in risk] == list(range(1, len(risk) + 1)) and all(part["total"] == len(risk) for part in risk)
    assert sec.part_title("Anthropic, PBC S-1", parts[0]).startswith("Anthropic, PBC S-1｜招股說明書摘要")


def test_only_edgar_archive_pages_on_sec_gov_are_allowed():
    assert sec.allowed_filing_url(URL)
    for bad in ["http://www.sec.gov/Archives/edgar/data/1/2/a.htm", "https://evil.example/Archives/edgar/data/1/2/a.htm",
                "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany", "https://www.sec.gov.evil.example/Archives/edgar/data/1/a.htm",
                "https://www.sec.gov/Archives/edgar/data/1/2/a.pdf", "file:///etc/passwd"]:
        assert not sec.allowed_filing_url(bad), bad


@pytest.fixture
def db():
    return MarketReportsDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))


def test_import_stores_each_part_as_a_public_report_owned_by_the_importer_and_a_second_import_adds_nothing(db):
    first = sec.import_filing(db, URL, owner="owner-1", fetch=lambda url: filing(summary_n=3, risk_n=3))
    assert first["created"] == 5 and first["known"] == 0 and first["title"] == "Anthropic, PBC S-1"
    rows = db.list_reports(owner="owner-1")
    assert len(rows) == 5 and {row["publisher"] for row in rows} == {"SEC EDGAR"}
    assert all(row["source_url"] == URL and row["published_at"] == "2026-10-26" and row["status"] == "claims_pending" for row in rows)
    assert any(row["title"].startswith("Anthropic, PBC S-1｜業務") for row in rows)
    assert {row["visibility"] for row in rows} == {"public"} and len(db.list_reports(owner=None)) == 5
    pending = db.pending_claims()
    assert len(pending) == 5 and "We sell models" in next(row for row in pending if "業務" in row["title"])["text"]
    again = sec.import_filing(db, URL, owner="owner-1", fetch=lambda url: filing(summary_n=3, risk_n=3))
    assert again["created"] == 0 and again["known"] == 5


def test_an_unreadable_or_section_less_page_is_refused_with_a_reason(db):
    with pytest.raises(ValueError, match="allowed"):
        sec.import_filing(db, "https://evil.example/x.htm", owner="o", fetch=lambda url: "")
    with pytest.raises(ValueError, match="sections"):
        sec.import_filing(db, URL, owner="o", fetch=lambda url: "<html><body><p>nothing useful here</p></body></html>")


def test_the_endpoint_needs_the_owner_and_reports_what_was_stored(db, monkeypatch):
    from maya_sawa.api import market_reports
    from maya_sawa.core.auth.keycloak import require_manage_users_request
    monkeypatch.setattr(market_reports, "market_reports_db", db)
    monkeypatch.setattr(market_reports.sec_filings, "fetch_filing", lambda url: filing())
    app = FastAPI()
    app.include_router(market_reports.router)
    client = TestClient(app)
    assert client.post("/market/reports/web", json={"url": URL}).status_code in (401, 403)   # no owner token
    app.dependency_overrides[require_manage_users_request] = lambda: {"sub": "owner-1"}
    ok = client.post("/market/reports/web", json={"url": URL})
    assert ok.status_code == 200 and ok.json()["created"] == 5 and ok.json()["title"] == "Anthropic, PBC S-1"
    assert client.post("/market/reports/web", json={"url": "https://evil.example/x.htm"}).status_code == 422
