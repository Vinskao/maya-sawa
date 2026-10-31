"""SEC EDGAR filings as research reports: a filing URL becomes one report per chosen section (long ones split into parts).

A prospectus is far too large for one report (the Anthropic S-1 is ~1.6M characters), so only the sections that matter to the
research are kept, each split into parts the claim-extraction routine can read, with Risk Factors capped to its opening part.
Only https://www.sec.gov/Archives/edgar/data/... pages are fetched, one request, with a descriptive User-Agent.
"""
import hashlib
import html
import os
import re
from datetime import date
from urllib.parse import urlsplit

import httpx

USER_AGENT = os.environ.get("SEC_USER_AGENT", "TYMultiverse maya-sawa research (+https://tymultiverse.cc)")
MAX_BYTES = 30 * 1024 * 1024
PART_CHARS = 40000
PAGE_CHARS = 8000
PUBLISHER = "SEC EDGAR"

# The order sections appear in an S-1 (its table of contents). Each section ends where the next one begins.
S1_ORDER = [
    "Select Defined Terms", "Prospectus Summary", "Risk Factors", "Special Note Regarding Forward-Looking Statements",
    "Industry, Market, and Other Data", "Use of Proceeds", "Dividend Policy", "Capitalization", "Dilution",
    "Management’s Discussion and Analysis of Financial Condition and Results of Operations", "Business",
    "Our Governance Structure and Its Goals", "Management", "Executive Compensation",
    "Certain Relationships and Related Person Transactions", "Principal and Selling Stockholders", "Description of Capital Stock",
    "Shares Eligible for Future Sale", "Underwriting", "Index to Consolidated Financial Statements",
]
# Chosen for the AI-supply-chain research, narrowed on the owner's request: the summary, what the money is for, and the numbers
# (growth, margins, compute commitments and liquidity). Business (~185k chars) and Risk Factors (~470k) are left out.
WANTED = {
    "Prospectus Summary": "招股說明書摘要", "Use of Proceeds": "募資用途",
    "Management’s Discussion and Analysis of Financial Condition and Results of Operations": "管理層討論與分析（營運結果與流動性）",
}
LABELS = {**WANTED, "Risk Factors": "風險因素", "Business": "業務"}  # titles for sections a caller may still ask for
CAPS = {"Risk Factors": 100000}  # only applies if Risk Factors is requested
EXCERPT_NOTE = "\n[Excerpt only: the rest of this section was not imported.]"


def allowed_filing_url(url: str) -> bool:
    parts = urlsplit(url)
    return (parts.scheme == "https" and (parts.hostname or "").lower() == "www.sec.gov"
            and parts.path.startswith("/Archives/edgar/data/") and parts.path.lower().endswith((".htm", ".html")))


def fetch_filing(url: str) -> str:
    if not allowed_filing_url(url):
        raise ValueError("URL is not an allowed SEC filing page")
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=90, follow_redirects=False) as client:
        response = client.get(url)
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError("Filing is larger than 30 MB")
        return response.text


def filing_text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", page, flags=re.S | re.I)
    page = re.sub(r"<ix:header>.*?</ix:header>", "", page, flags=re.S | re.I)
    page = re.sub(r"</(p|div|tr|h[1-6]|li|table)>|<br\s*/?>", "\n", page, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", page))
    text = re.sub(r"[ \t\r\f\v\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def filing_meta(page: str, url: str) -> dict:
    text = filing_text(page)
    entity = re.search(r"([^\n]+)\n\(Exact name of registrant", text)
    form = re.search(r"\bFORM\s+(S-1(?:/A)?|10-K|10-Q|8-K|424B4)\b", text)
    filed = re.search(r"filed with the Securities and Exchange Commission on ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    when = None
    if filed:
        from datetime import datetime
        when = datetime.strptime(filed.group(1), "%B %d, %Y").date()
    entity_name = entity.group(1).strip() if entity else "SEC filing"
    form_name = form.group(1) if form else "filing"
    return {"entity": entity_name, "form": form_name, "filed": when, "title": f"{entity_name} {form_name}"}


def _key(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("’", "'")).strip().casefold()


def split_sections(text: str, order=S1_ORDER) -> list[tuple[str, str]]:
    """Body of each section, in order. A heading is a line (or two joined lines) equal to a contents-page name that comes right
    after a "Table of Contents" page header, so the contents page itself and cross-references ("see 'Risk Factors'") never match."""
    lines = text.split("\n")
    offsets, position = [], 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    wanted = {_key(name): name for name in order}
    found, cursor, previous = [], 0, -1
    for name in order:
        target = _key(name)
        for index in range(cursor, len(lines)):
            if _key(lines[index]) != target and _key(f"{lines[index]} {lines[index + 1]}" if index + 1 < len(lines) else "") != target:
                continue
            header = _key(lines[index - 1]) if index else ""
            if header != "table of contents":
                continue
            span = 1 if _key(lines[index]) == target else 2
            found.append((name, offsets[index], offsets[index + span - 1] + len(lines[index + span - 1]) + 1))
            cursor, previous = index + span, offsets[index]
            break
    sections = []
    for number, (name, start, body_start) in enumerate(found):
        end = found[number + 1][1] if number + 1 < len(found) else len(text)
        sections.append((name, text[body_start:end].strip()))
    return sections


def plan_parts(sections, max_chars: int = PART_CHARS, caps=CAPS, wanted=WANTED) -> list[dict]:
    parts = []
    for name, body in sections:
        if name not in wanted:
            continue
        cap = caps.get(name)
        if cap and len(body) > cap:
            cut = body.rfind("\n", 0, cap)
            body = body[: cut if cut > 0 else cap] + EXCERPT_NOTE
        chunks, current = [], ""
        for line in body.split("\n"):
            while len(line) > max_chars:  # a single unbroken block longer than a part
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(line[:max_chars])
                line = line[max_chars:]
            if current and len(current) + len(line) + 1 > max_chars:
                chunks.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            chunks.append(current)
        parts.extend({"section": name, "index": number, "total": len(chunks), "text": chunk} for number, chunk in enumerate(chunks, 1))
    return parts


def part_title(base: str, part: dict) -> str:
    label = LABELS.get(part["section"], part["section"])
    return f"{base}｜{label}" + (f"（{part['index']}/{part['total']}）" if part["total"] > 1 else "")


def _pages(text: str) -> list[str]:
    pages, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > PAGE_CHARS:
            pages.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    return [*pages, current] if current else pages


def import_filing(db, url: str, owner: str, fetch=None) -> dict:
    if not allowed_filing_url(url):
        raise ValueError("URL is not an allowed SEC filing page")
    page = (fetch or fetch_filing)(url)
    meta = filing_meta(page, url)
    parts = plan_parts(split_sections(filing_text(page)))
    if not parts:
        raise ValueError("No readable sections found in this filing")
    created = known = 0
    for part in parts:
        source = f"來源：{url}\n申報：{meta['title']}，{meta['filed'] or ''}\n章節：{part['section']}（{part['index']}/{part['total']}）\n\n{part['text']}"
        _, duplicate = db.save_extracted(
            title=part_title(meta["title"], part), publisher=PUBLISHER, published_at=meta["filed"], visibility="public", uploaded_by=owner,
            digest=hashlib.sha256(f"sec:{url}:{part['section']}:{part['index']}".encode()).hexdigest(), pdf=b"",
            pages=_pages(source), source_url=url, status="claims_pending")
        known, created = (known + 1, created) if duplicate else (known, created + 1)
    return {"title": meta["title"], "filed": meta["filed"].isoformat() if meta["filed"] else None, "created": created, "known": known,
            "sections": sorted({part["section"] for part in parts}), "characters": sum(len(part["text"]) for part in parts)}
