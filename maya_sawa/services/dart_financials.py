"""Korea holdings' financials from OpenDART periodic reports (Financial Supervisory Service; key OPENDART_API_KEY).

fnlttSinglAcntAll returns each account with the reported quarter (thstrm_amount), year to date
(thstrm_add_amount), the same quarter and year to date a year earlier, and balance-sheet period ends. The
annual report has only the full year, so the fourth quarter is derived from the third-quarter year to date
(tdnet_financials.build_financials, marked derivedFromYtd). Amounts are KRW, not millions; EPS is KRW/share.
The key never leaves the request: it is not logged, stored or returned. Covered by tests/test_dart_financials.py.
"""
from __future__ import annotations

import asyncio
import calendar
import hashlib
import io
import json
import logging
import os
import re
import zipfile
from datetime import date, datetime, timedelta, timezone

from .tdnet_financials import build_financials as _merge

logger = logging.getLogger(__name__)

API = "https://opendart.fss.or.kr/api/"
SOURCE = "OpenDART (Korea Financial Supervisory Service)"
NOTES = ["All monetary amounts are KRW, not millions; EPS is KRW/share.",
         "Quarters are reported in Q1, half-year and Q3 reports; the fourth quarter is the annual report minus the "
         "third-quarter year to date (derivedFromYtd).",
         "Consolidated statements (CFS) when filed, otherwise separate (OFS)."]
REPORT_CODE = {"사업보고서": "11011", "반기보고서": "11012"}  # 분기보고서 is 11013 (Q1) or 11014 (Q3) by month
INCOME = {"revenue": ["ifrs-full_Revenue"], "costOfRevenue": ["ifrs-full_CostOfSales"], "grossProfit": ["ifrs-full_GrossProfit"],
          "operatingIncome": ["dart_OperatingIncomeLoss", "ifrs-full_ProfitLossFromOperatingActivities"],
          "netIncome": ["ifrs-full_ProfitLossAttributableToOwnersOfParent", "ifrs-full_ProfitLoss"],
          "epsBasic": ["ifrs-full_BasicEarningsLossPerShare"], "epsDiluted": ["ifrs-full_DilutedEarningsLossPerShare"]}
CASH = {"operatingCashFlow": ["ifrs-full_CashFlowsFromUsedInOperatingActivities"],
        "investingCashFlow": ["ifrs-full_CashFlowsFromUsedInInvestingActivities"],
        "capitalExpenditure": ["ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                               "ifrs-full_PurchaseOfPropertyPlantAndEquipment"]}
BALANCE = {"assets": ["ifrs-full_Assets"], "liabilities": ["ifrs-full_Liabilities"],
           "equity": ["ifrs-full_EquityAttributableToOwnersOfParent", "ifrs-full_Equity"],
           "inventory": ["ifrs-full_Inventories"], "cash": ["ifrs-full_CashAndCashEquivalents"],
           "currentAssets": ["ifrs-full_CurrentAssets"], "currentLiabilities": ["ifrs-full_CurrentLiabilities"]}
HISTORY_DAYS = 3 * 365
SCAN_INTERVAL_SECONDS = 12 * 3600


def corp_codes(archive: bytes) -> dict[str, str]:
    """stock_code -> corp_code for listed companies in OpenDART's corpCode.xml archive."""
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        xml = z.read(z.namelist()[0]).decode("utf-8")
    codes = {}
    for block in re.findall(r"<list>(.*?)</list>", xml, re.S):
        stock = re.search(r"<stock_code>\s*(\d{6})\s*</stock_code>", block)
        corp = re.search(r"<corp_code>\s*(\d{8})\s*</corp_code>", block)
        if stock and corp:
            codes[stock.group(1)] = corp.group(1)
    return codes


def periodic_filings(payload: dict) -> list[dict]:
    """Annual, half-year and quarterly reports with their period; an amendment replaces the original filing."""
    found: dict = {}
    for item in sorted(payload.get("list") or [], key=lambda row: row.get("rcept_no", "")):
        name = item.get("report_nm", "")
        period = re.search(r"\((\d{4})\.(\d{2})\)", name)
        kind = next((k for k in ("사업보고서", "반기보고서", "분기보고서") if k in name), None)
        if not period or not kind:
            continue
        year, month = period.groups()
        found[f"{year}-{month}"] = {"rceptNo": item["rcept_no"], "reportName": name, "periodEnd": f"{year}-{month}",
            "filedOn": f"{item['rcept_dt'][:4]}-{item['rcept_dt'][4:6]}-{item['rcept_dt'][6:]}", "kind": kind}
    # Quarterly reports are Q1 or Q3 by their month relative to the fiscal year end (the annual report's month).
    year_end = next((int(f["periodEnd"][5:]) for f in found.values() if f["kind"] == "사업보고서"), 12)
    for filing in found.values():
        month = int(filing["periodEnd"][5:])
        months_in = (month - year_end) % 12 or 12
        filing["reprtCode"] = REPORT_CODE.get(filing["kind"]) or ("11013" if months_in == 3 else "11014")
        # bsns_year is the year the fiscal year ends in.
        filing["bsnsYear"] = str(int(filing["periodEnd"][:4]) + (1 if month > year_end else 0))
        filing["fiscalYearEndMonth"] = year_end
    return sorted(found.values(), key=lambda f: f["periodEnd"])


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _shift_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _amount(text) -> float | None:
    if text in (None, "", "-"):
        return None
    try:
        return float(str(text).replace(",", ""))
    except ValueError:
        return None


def parse_statement(payload: dict, *, period_end: str, fiscal_year_end_month: int) -> dict:
    """One periodic report -> durations (quarter, year to date, a year earlier) and balance-sheet instants."""
    rows = payload.get("list") or []
    year, month = int(period_end[:4]), int(period_end[5:])
    end = _month_end(year, month)
    months_in = (month - fiscal_year_end_month) % 12 or 12
    ytd_start = date(*_shift_months(year, month, -months_in + 1), 1)
    quarter_start = date(*_shift_months(year, month, -2), 1)
    prior = lambda d: date(d.year - 1, d.month, calendar.monthrange(d.year - 1, d.month)[1] if d.day > 28 else d.day)
    annual = months_in == 12

    def pick(names, sections):
        for name in names:
            for section in sections:
                row = next((r for r in rows if r.get("account_id") == name and r.get("sj_div") == section), None)
                if row:
                    return row
        return None

    periods: dict = {}

    def put(start: date, stop: date, metric: str, value):
        if value is None:
            return
        periods.setdefault((start.isoformat(), stop.isoformat()), {})[metric] = value

    for metric, names in INCOME.items():
        row = pick(names, ("IS", "CIS"))
        if not row:
            continue
        if annual:
            put(ytd_start, end, metric, _amount(row.get("thstrm_amount")))
            put(prior(ytd_start - timedelta(days=1)) + timedelta(days=1), prior(end), metric, _amount(row.get("frmtrm_amount")))
        else:
            put(quarter_start, end, metric, _amount(row.get("thstrm_amount")))
            put(ytd_start, end, metric, _amount(row.get("thstrm_add_amount")))
            put(date(quarter_start.year - 1, quarter_start.month, 1), prior(end), metric, _amount(row.get("frmtrm_q_amount")))
            put(date(ytd_start.year - 1, ytd_start.month, 1), prior(end), metric, _amount(row.get("frmtrm_add_amount")))
    for metric, names in CASH.items():
        row = pick(names, ("CF",))
        if row:
            put(ytd_start, end, metric, _amount(row.get("thstrm_amount")))
            put(date(ytd_start.year - 1, ytd_start.month, 1), prior(end), metric, _amount(row.get("frmtrm_amount")))
    durations = []
    for (start, stop), values in sorted(periods.items()):
        entry = {"start": start, "end": stop, "durationDays": (date.fromisoformat(stop) - date.fromisoformat(start)).days,
                 **{metric: values.get(metric) for metric in (*INCOME, *CASH)}}
        if entry["grossProfit"] is None and entry["revenue"] is not None and entry["costOfRevenue"] is not None:
            entry["grossProfit"] = entry["revenue"] - entry["costOfRevenue"]
        durations.append(entry)
    instants: dict = {}
    previous_year_end = ytd_start - timedelta(days=1)
    for metric, names in BALANCE.items():
        row = pick(names, ("BS",))
        if not row:
            continue
        for stamp, field in ((end, "thstrm_amount"), (previous_year_end, "frmtrm_amount")):
            value = _amount(row.get(field))
            if value is not None:
                instants.setdefault(stamp.isoformat(), {"end": stamp.isoformat()})[metric] = value
    return {"standard": "K-IFRS", "durations": durations, "instants": sorted(instants.values(), key=lambda r: r["end"]), "forecasts": []}


def build_financials(releases: list[dict]) -> dict:
    return _merge([r for r in releases if not r.get("empty")], currency="KRW", source=SOURCE, notes=NOTES)


def _content_period(data) -> str:
    return "content-" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def collect(db, fetch, *, today: date | None = None) -> int:
    """Store new periodic reports for the Korea holdings and rebuild their financials. Returns reports saved."""
    holdings = await asyncio.to_thread(db.market_codes, "KR")
    if not holdings:
        return 0
    today = today or datetime.now(timezone(timedelta(hours=9))).date()
    mapping = None
    saved = 0
    for code in holdings:
        known = await asyncio.to_thread(db.latest, code, "KR", "dart_corp_code")
        corp = (known or {}).get("payload", {}).get("corpCode")
        conid = ((await asyncio.to_thread(db.latest, code, "KR", "profile")) or {}).get("conid") or 0
        if not corp:
            if mapping is None:
                mapping = corp_codes(await fetch("corpCode.xml", {}))
            corp = mapping.get(code)
            if not corp:
                logger.warning("OpenDART: no corp_code for %s", code)
                continue
            await asyncio.to_thread(db.save, code, "KR", conid, "dart_corp_code", {"corpCode": corp})
        listing = json.loads(await fetch("list.json", {"corp_code": corp, "bgn_de": (today - timedelta(days=HISTORY_DAYS)).strftime("%Y%m%d"),
                                                       "end_de": today.strftime("%Y%m%d"), "pblntf_ty": "A", "page_count": "100"}))
        if listing.get("status") not in ("000", "013"):
            raise RuntimeError(f"opendart_list_status_{listing.get('status')}")
        seen = {row["period"] for row in await asyncio.to_thread(db.history, code, "KR", "dart_release")}
        added = 0
        for filing in periodic_filings(listing):
            if filing["rceptNo"] in seen:
                continue
            release = None
            for fs_div in ("CFS", "OFS"):
                payload = json.loads(await fetch("fnlttSinglAcntAll.json", {"corp_code": corp, "bsns_year": filing["bsnsYear"],
                                                                             "reprt_code": filing["reprtCode"], "fs_div": fs_div}))
                if payload.get("status") == "000":
                    release = parse_statement(payload, period_end=filing["periodEnd"], fiscal_year_end_month=filing["fiscalYearEndMonth"])
                    release["consolidated"] = fs_div == "CFS"
                    break
                if payload.get("status") != "013":
                    raise RuntimeError(f"opendart_statement_status_{payload.get('status')}")
                await asyncio.sleep(0.2)
            release = release or {"empty": True}
            release.update(releasedAt=filing["filedOn"], title=filing["reportName"], rceptNo=filing["rceptNo"],
                           zipUrl=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={filing['rceptNo']}")
            await asyncio.to_thread(db.save, code, "KR", conid, "dart_release", release, period=filing["rceptNo"])
            if not release.get("empty"):
                saved += 1
            added += 1
            await asyncio.sleep(0.2)
        if added:
            releases = [row["payload"] for row in await asyncio.to_thread(db.history, code, "KR", "dart_release")]
            data = build_financials(releases)
            await asyncio.to_thread(db.save, code, "KR", conid, "financials", data, period=_content_period(data))
    return saved


class DartFinancialsCollector:
    """Background OpenDART collection for Korea holdings; off when OPENDART_API_KEY is unset."""

    def __init__(self, db=None):
        self._db = db
        self._task: asyncio.Task | None = None

    @property
    def db(self):
        if self._db is None:
            from ..databases.ibkr_research_db import get_ibkr_research_db
            self._db = get_ibkr_research_db()
        return self._db

    async def _fetch(self, path: str, params: dict) -> bytes:
        import httpx
        key = os.getenv("OPENDART_API_KEY", "")
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(API + path, params={**params, "crtfc_key": key})
                response.raise_for_status()
                return response.content
        except Exception as exc:
            # httpx errors carry the URL, which includes the key: re-raise without it.
            raise RuntimeError(f"opendart_request_failed:{path}:{type(exc).__name__}") from None

    async def _loop(self):
        while True:
            try:
                saved = await collect(self.db, self._fetch)
                if saved:
                    logger.info("OpenDART: stored %d new Korea reports", saved)
            except Exception as exc:
                logger.warning("OpenDART collection failed: %s", str(exc)[:120])
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def start(self):
        if not os.getenv("OPENDART_API_KEY"):
            logger.info("OpenDART collection off: OPENDART_API_KEY not set")
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="opendart-financials")

    async def close(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


dart_financials_collector = DartFinancialsCollector()
