"""Insiders' pre-filed share transfers (內部人持股轉讓事前申報) for TWSE and TPEx stocks.

The OpenAPI datasets list only the filings published on the latest business day, so a daily collector keeps them in
maya_sawa_insider_transfer and a stock is flagged while a filing's transfer window is open (docs/INSIDER_TRANSFERS.md).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, timedelta

logger = logging.getLogger(__name__)

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O"
SOURCE_PAGES = {"TWSE": "https://openapi.twse.com.tw/", "TPEx": "https://www.tpex.org.tw/openapi/"}
# Transfers that put shares on the market. 贈與 (gift), 信託 (trust) and similar move shares without selling them.
SALE_METHODS = ("一般交易", "盤後定價", "鉅額", "洽特定人", "拍賣", "標購", "公開招募")
UPCOMING_DAYS = 7


def roc_date(text: str | None) -> date | None:
    """ROC calendar YYYMMDD (1151116) -> 2026-11-16."""
    text = (text or "").strip()
    if len(text) != 7 or not text.isdigit():
        return None
    try:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:]))
    except ValueError:
        return None


def transfer_window(text: str | None) -> tuple[date | None, date | None]:
    parts = (text or "").split("~")
    if len(parts) != 2:
        return None, None
    return roc_date(parts[0]), roc_date(parts[1])


def _int(value) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def parse_filings(rows: Iterable[dict], market: str) -> list[dict]:
    """One shape for both markets (TWSE uses Chinese keys, TPEx English ones for the company columns)."""
    output = []
    for row in rows:
        code = str(row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
        filed = roc_date(row.get("出表日期") or row.get("Date"))
        start, end = transfer_window(row.get("有效轉讓期間"))
        if not code or not filed or not start or not end:
            continue
        method = str(row.get("預定轉讓方式及股數-轉讓方式") or "").strip()
        output.append({
            "market": market, "code": code, "name": str(row.get("公司名稱") or row.get("CompanyName") or code).strip(),
            "role": str(row.get("申報人身分") or row.get("申請人身分") or "").strip(),
            "holder": str(row.get("姓名") or "").strip(), "method": method,
            "sale": any(keyword in method for keyword in SALE_METHODS),
            "shares": _int(row.get("預定轉讓總股數-自有持股")) + _int(row.get("預定轉讓總股數-保留運用決定權信託股數")),
            "held": _int(row.get("目前持有股數-自有持股")) + _int(row.get("目前持有股數-保留運用決定權信託股數")),
            "filed": filed, "start": start, "end": end,
        })
    return output


def insider_events(filings: Iterable[dict], codes: set[str], today: date) -> list[dict]:
    """One company event per stock with an open (or soon to open) sale window, totalling every filer's planned shares."""
    grouped: dict[str, list[dict]] = {}
    for filing in filings:
        if (filing["code"] in codes and filing["sale"] and filing["end"] >= today
                and filing["start"] <= today + timedelta(days=UPCOMING_DAYS)):
            grouped.setdefault(filing["code"], []).append(filing)
    events = []
    for code, rows in grouped.items():
        rows.sort(key=lambda row: (row["start"], -row["shares"]))
        start, end = min(row["start"] for row in rows), max(row["end"] for row in rows)
        total = sum(row["shares"] for row in rows)
        methods = "、".join(dict.fromkeys(row["method"] for row in rows))
        who = f"{rows[0]['role']} {rows[0]['holder']}" if len(rows) == 1 else f"{len(rows)} 位內部人"
        period = f"{who} 預定轉讓 {total:,} 股（{methods}），{start:%m/%d}–{end:%m/%d}"
        events.append({"code": code, "name": rows[0]["name"], "type": "insider_transfer", "date": start.isoformat(),
                       "status": "active" if start <= today else "upcoming", "highlight": True, "period": period,
                       "shares": total, "endDate": end.isoformat(), "filers": len(rows),
                       "source": f"{rows[0]['market']} OpenAPI 內部人持股轉讓事前申報", "sourceUrl": SOURCE_PAGES[rows[0]["market"]]})
    return sorted(events, key=lambda event: (event["date"], event["code"]))


def fetch_json(url: str) -> list[dict]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; maya-sawa market dashboard)",
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def collect(save: Callable[[list[dict]], None]) -> int:
    """Fetch both markets' latest filings and store them; one market failing does not drop the other."""
    total = 0
    for market, url in (("TWSE", TWSE_URL), ("TPEx", TPEX_URL)):
        try:
            rows = parse_filings(fetch_json(url), market)
        except Exception as exc:
            logger.warning("Insider transfer filings from %s unavailable: %s", market, str(exc)[:80])
            continue
        if rows:
            save(rows)
        total += len(rows)
    return total
