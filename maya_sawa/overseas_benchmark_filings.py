"""Newest shareholder annual report of an overseas benchmark company, from each market's official source.

Taiwan benchmarks come from MOPS (tw_benchmark_filings). Overseas ones use:
- US: SEC EDGAR form ARS, the annual report to security holders (PDF or HTML), found through the submissions API.
- Japan (Advantest): the Integrated Annual Report PDF on the company IR site; its URL carries the edition year.
- Korea (SK hynix): the 사업보고서 (annual business report) on OpenDART, with the deployment's OPENDART_API_KEY.

A report is only usable when the source returns it; nothing here guesses a document.
"""

import io
import os
import re
import zipfile
from datetime import date

import httpx

from maya_sawa.services.sec_filings import USER_AGENT, _pages, filing_text

LIMIT = 64 * 1024 * 1024
SEC = {  # record code -> SEC CIK
    "GOOGL-US": "1652044", "META-US": "1326801", "MSFT-US": "789019",
    "AMZN-US": "1018724", "NVDA-US": "1045810", "LITE-US": "1633978",
}
ADVANTEST = "6857-JP"
ADVANTEST_REPORT = "https://www.advantest.com/document/en/investors/ir-library/annual/E_all_IAR{edition}.pdf"
ADVANTEST_LIBRARY = "https://www.advantest.com/en/investors/ir-library/annual/"
MURATA = "6981-JP"
MURATA_LIBRARY = "https://corporate.murata.com/en-global/ir/library/report"
MURATA_REPORT = re.compile(r"/-/media/corporate/ir/library/murata-value-report/(\d{4})_e/[^\"'\s]*?all-for-viewing-e\.ashx")
DART = {"000660-KR": "00164779"}  # record code -> OpenDART corp_code (SK hynix)
DART_API = "https://opendart.fss.or.kr/api/"


def is_overseas(code: str) -> bool:
    return code in SEC or code in (ADVANTEST, MURATA) or code in DART


def catalog_url(code: str) -> str:
    """Where a reader finds the company's annual reports by hand."""
    if code in SEC:
        return f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={SEC[code]}&type=ARS"
    if code == ADVANTEST:
        return ADVANTEST_LIBRARY
    if code == MURATA:
        return MURATA_LIBRARY
    if code in DART:
        return "https://dart.fss.or.kr/dsab007/main.do"
    raise ValueError(f"No overseas annual report source for {code}")


def latest_sec_report(submissions: dict, cik: str) -> dict | None:
    """The newest ARS filing in an EDGAR submissions payload."""
    recent = submissions.get("filings", {}).get("recent", {})
    for index, form in enumerate(recent.get("form", [])):
        if form != "ARS":
            continue
        document = recent["primaryDocument"][index]
        accession = recent["accessionNumber"][index].replace("-", "")
        period = recent.get("reportDate", [""] * (index + 1))[index] or ""
        filed = recent["filingDate"][index]
        # The report covers the fiscal year that ended before it was filed.
        year = int(period[:4]) if period else int(filed[:4]) - 1
        return {"fiscal_year": year, "filename": document,
                "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{document}"}
    return None


def latest_murata_report(page: str) -> dict | None:
    """The newest English Murata value report (integrated report) linked from the IR library page."""
    found = {int(match[1]): match[0] for match in MURATA_REPORT.finditer(page.replace("&amp;", "&"))}
    if not found:
        return None
    edition = max(found)
    # The edition published in a year covers the fiscal year that ended that March (2025 = FY2024).
    return {"fiscal_year": edition - 1, "filename": f"murata-value-report-{edition}-e.pdf",
            "url": "https://corporate.murata.com" + found[edition] + "?la=en"}


def latest_dart_report(listing: dict) -> dict | None:
    """The newest 사업보고서 (amendments included) in an OpenDART list.json payload."""
    reports = [row for row in listing.get("list") or [] if "사업보고서" in row.get("report_nm", "")]
    if not reports:
        return None
    row = max(reports, key=lambda item: item.get("rcept_no", ""))
    period = re.search(r"\((\d{4})\.\d{2}\)", row["report_nm"])
    year = int(period[1]) if period else int(row["rcept_dt"][:4]) - 1
    return {"fiscal_year": year, "filename": f"dart_{row['rcept_no']}.zip", "rcept_no": row["rcept_no"],
            "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={row['rcept_no']}"}


def dart_corp_code(code: str) -> str:
    """The corp_code the Korea financials collector already resolved from corpCode.xml; the constant is a fallback."""
    try:
        from maya_sawa.databases.ibkr_research_db import get_ibkr_research_db
        row = get_ibkr_research_db().latest(code.split("-")[0], "KR", "dart_corp_code")
        corp = (row or {}).get("payload", {}).get("corpCode")
        if corp:
            return corp
    except Exception:
        pass
    return DART[code]


def _get(client: httpx.Client, url: str, **kwargs) -> bytes:
    response = client.get(url, **kwargs)
    response.raise_for_status()
    if len(response.content) > LIMIT:
        raise ValueError("Annual report is larger than 64 MB")
    return response.content


def latest_report(code: str, today: date | None = None, client: httpx.Client | None = None) -> dict | None:
    """Locate the newest annual report: fiscal_year, filename, url (and a DART receipt number)."""
    today = today or date.today()
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=90, follow_redirects=False)
    try:
        if code in SEC:
            cik = SEC[code]
            import json
            payload = json.loads(_get(client, f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json"))
            return latest_sec_report(payload, cik)
        if code == ADVANTEST:
            # The edition named after a year covers the fiscal year ending that March (IAR2026 = FY2025).
            for edition in (today.year + 1, today.year, today.year - 1):
                response = client.head(ADVANTEST_REPORT.format(edition=edition))
                if response.status_code == 200 and "pdf" in response.headers.get("content-type", ""):
                    return {"fiscal_year": edition - 1, "filename": f"E_all_IAR{edition}.pdf",
                            "url": ADVANTEST_REPORT.format(edition=edition)}
            return None
        if code == MURATA:
            return latest_murata_report(_get(client, MURATA_LIBRARY).decode("utf-8", errors="replace"))
        if code in DART:
            key = os.getenv("OPENDART_API_KEY", "")
            if not key:
                return None
            import json
            try:
                listing = json.loads(_get(client, DART_API + "list.json", params={
                    "crtfc_key": key, "corp_code": dart_corp_code(code), "pblntf_ty": "A", "page_count": "100",
                    "bgn_de": f"{today.year - 2}0101", "end_de": today.strftime("%Y%m%d")}))
            except httpx.HTTPError as exc:  # the request URL carries the key: drop it from the error
                raise RuntimeError(f"opendart_list_failed:{type(exc).__name__}") from None
            return latest_dart_report(listing)
        raise ValueError(f"No overseas annual report source for {code}")
    finally:
        if own:
            client.close()


def download(code: str, report: dict, client: httpx.Client | None = None) -> bytes:
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=180, follow_redirects=False)
    try:
        if code in DART:
            try:
                data = _get(client, DART_API + "document.xml",
                            params={"crtfc_key": os.getenv("OPENDART_API_KEY", ""), "rcept_no": report["rcept_no"]})
            except httpx.HTTPError as exc:
                raise RuntimeError(f"opendart_document_failed:{type(exc).__name__}") from None
            if not data.startswith(b"PK"):
                raise ValueError("OpenDART did not return a document archive")
            return data
        data = _get(client, report["url"])
        if not (data.startswith(b"%PDF") or b"<html" in data[:4096].lower() or b"<?xml" in data[:200]):
            raise ValueError("Annual report is neither a PDF nor an HTML page")
        return data
    finally:
        if own:
            client.close()


def document_pages(data: bytes) -> list[str]:
    """Text pages of a stored annual report, whatever its format.

    PDFs keep their real page order. An HTML report (an SEC ARS) or a DART archive has no pages, so its text is cut
    into fixed-size pages; a claim's page then points into that cut, not into a printed page number.
    """
    if data.startswith(b"%PDF"):
        from maya_sawa.services.market_reports import extract_pdf_pages
        return extract_pdf_pages(data)
    if data.startswith(b"PK"):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = sorted(archive.namelist(), key=lambda name: archive.getinfo(name).file_size, reverse=True)
            raw = archive.read(names[0])
        text = raw.decode("utf-8", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    return _pages(filing_text(text))
