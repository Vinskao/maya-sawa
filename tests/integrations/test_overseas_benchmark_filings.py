"""Overseas benchmark annual reports: SEC ARS, Advantest integrated report, OpenDART 사업보고서."""
import io
import zipfile
from datetime import date

import httpx
import pytest

from maya_sawa import overseas_benchmark_filings as overseas
from maya_sawa.benchmark_evidence import select_pages


SUBMISSIONS = {"filings": {"recent": {
    "form": ["8-K", "10-K", "ARS", "ARS"],
    "accessionNumber": ["0001-26-000001", "0001-26-000002", "0001628280-26-025534", "0001628280-25-000009"],
    "primaryDocument": ["a.htm", "meta-20251231.htm", "meta-12312025x10kars.htm", "old.htm"],
    "reportDate": ["", "2025-12-31", "", ""],
    "filingDate": ["2026-10-01", "2026-01-29", "2026-04-16", "2025-04-17"],
}}}


def test_the_newest_sec_annual_report_to_shareholders_is_picked():
    report = overseas.latest_sec_report(SUBMISSIONS, "1326801")
    assert report == {"fiscal_year": 2025, "filename": "meta-12312025x10kars.htm",
                      "url": "https://www.sec.gov/Archives/edgar/data/1326801/000162828026025534/meta-12312025x10kars.htm"}
    assert overseas.latest_sec_report({"filings": {"recent": {"form": ["10-K"]}}}, "1") is None


def test_the_newest_dart_business_report_is_picked_and_quarterlies_are_ignored():
    listing = {"list": [
        {"report_nm": "분기보고서 (2026.09)", "rcept_no": "20261114000001", "rcept_dt": "20261114"},
        {"report_nm": "사업보고서 (2025.12)", "rcept_no": "20260318000802", "rcept_dt": "20260318"},
        {"report_nm": "사업보고서 (2024.12)", "rcept_no": "20250319000900", "rcept_dt": "20250319"},
    ]}
    report = overseas.latest_dart_report(listing)
    assert report["fiscal_year"] == 2025 and report["rcept_no"] == "20260318000802"
    assert report["url"].endswith("rcpNo=20260318000802")
    assert overseas.latest_dart_report({"list": listing["list"][:1]}) is None


def test_advantest_uses_the_newest_integrated_report_edition_that_exists():
    def handler(request):
        if request.url.path.endswith("E_all_IAR2026.pdf"):
            return httpx.Response(200, headers={"content-type": "application/pdf"})
        return httpx.Response(404, headers={"content-type": "text/html"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = overseas.latest_report("6857-JP", today=date(2026, 11, 11), client=client)
    assert report == {"fiscal_year": 2025, "filename": "E_all_IAR2026.pdf",
                      "url": "https://www.advantest.com/document/en/investors/ir-library/annual/E_all_IAR2026.pdf"}


def test_korea_report_is_skipped_without_the_opendart_key(monkeypatch):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    assert overseas.latest_report("000660-KR") is None


def test_only_companies_with_a_known_source_are_overseas_benchmarks():
    assert all(overseas.is_overseas(code) for code in ("NVDA-US", "MSFT-US", "6857-JP", "000660-KR"))
    assert not overseas.is_overseas("2330") and not overseas.is_overseas("LITE-US")
    with pytest.raises(ValueError):
        overseas.catalog_url("LITE-US")


def test_html_and_dart_archives_become_text_pages():
    html = b"<html><body><p>We expect capital expenditures to increase.</p><script>x()</script></body></html>"
    assert overseas.document_pages(html) == ["We expect capital expenditures to increase."]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("small.xml", "<a>x</a>")
        z.writestr("main.xml", "<DOCUMENT><P>HBM 생산능력을 확대하고 있다.</P><P>" + "본문 " * 50 + "</P></DOCUMENT>")
    pages = overseas.document_pages(archive.getvalue())
    assert "HBM 생산능력을 확대하고 있다." in pages[0]


def test_english_and_korean_annual_report_sentences_are_selected_and_financial_ones_dropped():
    page = ("We expect capital expenditures to increase in 2026 as we expand data center capacity for AI. "
            "Net income was $100 billion for the year. "
            "Demand for our accelerated computing platforms continues to exceed supply.\n\n"
            "HBM 수요가 공급을 초과하고 있어 생산능력을 확대한다.")
    selected = select_pages([page])[0]
    assert "capital expenditures to increase" in selected and "accelerated computing" in selected
    assert "HBM 수요가" in selected and "Net income" not in selected
