"""Japan: five fiscal years per company from EDINET annual securities reports (有価証券報告書), FSA API v2.

Each annual report has a five-year table (主要な経営指標等の推移); `type=5` returns the XBRL as CSV, where those rows
are elements ending in SummaryOfBusinessResults with contexts CurrentYear… to Prior4Year…(Duration|Instant).
Consolidated figures win; parent-only (_NonConsolidatedMember) fill in only when no consolidated figure exists.
EDINET lists documents by day only, so the collector walks back day by day until every Japan holding's latest annual
report is found, and rechecks the last few days on later passes. The key (EDINET_API_KEY, a Jenkins credential)
is sent only as a request parameter and never stored or logged. Releases feed tdnet_financials.build_financials with
TDnet and J-Quants. Covered by tests/test_edinet_financials.py.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
import zipfile
from datetime import date, timedelta

logger = logging.getLogger(__name__)
API = "https://api.edinet-fsa.go.jp/api/v2"
VIEWER = "https://disclosure2.edinet-fsa.go.jp/WZEK0040.aspx?"
SOURCE = "EDINET 有価証券報告書 (FSA)"
ANNUAL_REPORT = "120"
SUFFIX = "SummaryOfBusinessResults"
# Element names without the jpcrp_cor: prefix and the SummaryOfBusinessResults suffix, best first per metric.
METRICS = {
    "revenue": ["RevenueIFRS", "NetSalesIFRS", "RevenuesUSGAAP", "NetSales", "OperatingRevenue1", "OperatingRevenue2"],
    "netIncome": ["ProfitLossAttributableToOwnersOfParentIFRS", "NetIncomeLossAttributableToOwnersOfParentUSGAAP",
                  "ProfitLossAttributableToOwnersOfParent", "NetIncomeLoss"],
    "epsBasic": ["BasicEarningsLossPerShareIFRS", "BasicEarningsLossPerShareUSGAAP", "BasicEarningsLossPerShare"],
    "epsDiluted": ["DilutedEarningsLossPerShareIFRS", "DilutedEarningsLossPerShareUSGAAP", "DilutedEarningsPerShare"],
    "operatingCashFlow": ["CashFlowsFromUsedInOperatingActivitiesIFRS", "CashFlowsFromUsedInOperatingActivitiesUSGAAP",
                          "CashFlowsFromUsedInOperatingActivities"],
    "investingCashFlow": ["CashFlowsFromUsedInInvestingActivitiesIFRS", "CashFlowsFromUsedInInvestingActivitiesUSGAAP",
                          "CashFlowsFromUsedInInvestingActivities"],
    "assets": ["TotalAssetsIFRS", "TotalAssetsUSGAAP", "TotalAssets"],
    "equity": ["EquityAttributableToOwnersOfParentIFRS", "EquityAttributableToOwnersOfParentUSGAAP", "NetAssets"],
    "cash": ["CashAndCashEquivalentsIFRS", "CashAndCashEquivalentsUSGAAP", "CashAndCashEquivalents"],
}
INSTANTS = {"assets", "equity", "cash"}
RELATIVE = {"CurrentYear": 0, "Prior1Year": 1, "Prior2Year": 2, "Prior3Year": 3, "Prior4Year": 4}


def annual_reports(listing: dict, codes: set[str]) -> list[dict]:
    """Annual securities reports in one day's document list for the given four-digit codes (secCode adds a 0)."""
    wanted = {f"{code}0" for code in codes}
    return [doc for doc in listing.get("results") or []
            if doc.get("docTypeCode") == ANNUAL_REPORT and doc.get("secCode") in wanted and doc.get("withdrawalStatus") == "0"]


def _shift_years(day: str, years: int) -> date:
    value = date.fromisoformat(day)
    try:
        return value.replace(year=value.year - years)
    except ValueError:                                   # 29 February
        return value.replace(year=value.year - years, day=28)


def parse_summary_csv(text: str, doc: dict) -> dict:
    """The five-year table of one annual report as a release for build_financials (amounts in yen, EPS yen/share)."""
    found: dict[tuple[str, int, bool], float] = {}       # (element, years back, consolidated) -> value
    rows = csv.reader(io.StringIO(text), delimiter="\t")
    next(rows, None)
    for row in rows:
        if len(row) < 9 or not row[0].endswith(SUFFIX):
            continue
        element = row[0].split(":", 1)[-1][: -len(SUFFIX)]
        context, consolidated = row[2], "_NonConsolidatedMember" not in row[2]
        base = context.split("_", 1)[0].removesuffix("Duration").removesuffix("Instant")
        try:
            value = float(row[8].replace(",", ""))
        except ValueError:
            continue
        if base in RELATIVE:
            found[(element, RELATIVE[base], consolidated)] = value
    period_start, period_end = doc["periodStart"], doc["periodEnd"]
    durations, instants = {}, {}
    for back in range(5):
        start, end = _shift_years(period_start, back), _shift_years(period_end, back)
        for metric, names in METRICS.items():
            value = next((found[(name, back, consolidated)] for consolidated in (True, False) for name in names
                          if (name, back, consolidated) in found), None)
            if value is None:
                continue
            if metric in INSTANTS:
                instants.setdefault(end.isoformat(), {"end": end.isoformat()})[metric] = value
            else:
                durations.setdefault(end.isoformat(), {"start": start.isoformat(), "end": end.isoformat(),
                                                       "durationDays": (end - start).days + 1})[metric] = value
    elements = {element for element, _, consolidated in found if consolidated}
    standard = "IFRS" if any("IFRS" in name for name in elements) else "USGAAP" if any("USGAAP" in name for name in elements) else "JGAAP"
    return {"standard": standard, "company": doc.get("filerName"), "consolidated": bool(elements),
            "durations": sorted(durations.values(), key=lambda row: row["end"]),
            "instants": sorted(instants.values(), key=lambda row: row["end"]), "forecasts": [],
            "releasedAt": (doc.get("submitDateTime") or "").replace(" ", "T")[:16], "title": doc.get("docDescription"),
            "zipUrl": VIEWER + doc["docID"], "releaseId": doc["docID"]}


async def collect(db, fetch_listing, fetch_document, *, today: date | None = None, max_days: int = 400, recent_days: int = 3) -> int:
    """Walk back day by day (at least recent_days, at most max_days) until every Japan holding has an annual report;
    store reports not seen before and rebuild the holding's financials. Returns reports saved."""
    from .tdnet_financials import rebuild_japan
    holdings = list(await asyncio.to_thread(db.market_codes, "JP"))
    if not holdings:
        return 0
    stored = {code: {row["period"] for row in await asyncio.to_thread(db.history, code, "JP", "edinet_release")} for code in holdings}
    covered = {code for code, docs in stored.items() if docs}
    today = today or date.today()
    saved, touched = 0, set()
    for back in range(max_days):
        if back >= recent_days and covered >= set(holdings):
            break
        day = (today - timedelta(days=back)).isoformat()
        for doc in annual_reports(await fetch_listing(day), set(holdings)):
            code = doc["secCode"][:4]
            covered.add(code)
            if doc["docID"] in stored[code]:
                continue
            try:
                release = parse_summary_csv(await fetch_document(doc["docID"]), doc)
            except Exception as exc:
                logger.warning("EDINET report %s for %s unreadable: %s", doc["docID"], code, type(exc).__name__)
                continue
            conid = ((await asyncio.to_thread(db.latest, code, "JP", "profile")) or {}).get("conid") or 0
            await asyncio.to_thread(db.save, code, "JP", conid, "edinet_release", release, period=doc["docID"])
            stored[code].add(doc["docID"])
            touched.add((code, conid))
            saved += 1
    for code, conid in touched:
        await asyncio.to_thread(rebuild_japan, db, code, conid)
    return saved


class EdinetFinancialsCollector:
    """Daily EDINET pass for Japan holdings; off when EDINET_API_KEY is unset."""
    INTERVAL_SECONDS = 24 * 3600

    def __init__(self, db=None):
        self._db = db
        self._task: asyncio.Task | None = None

    @property
    def db(self):
        if self._db is None:
            from ..databases.ibkr_research_db import get_ibkr_research_db
            self._db = get_ibkr_research_db()
        return self._db

    async def _get(self, path: str, params: dict) -> bytes:
        import httpx
        await asyncio.sleep(1)                           # one request a second keeps the day-by-day walk polite
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                response = await client.get(f"{API}{path}", params={**params, "Subscription-Key": os.getenv("EDINET_API_KEY", "")})
        except Exception as exc:                         # the exception text could carry the URL with the key
            raise RuntimeError(f"edinet_request_failed:{type(exc).__name__}") from None
        if response.status_code != 200:
            raise RuntimeError(f"edinet_http_{response.status_code}")
        return response.content

    async def _listing(self, day: str) -> dict:
        import json
        return json.loads(await self._get("/documents.json", {"date": day, "type": 2}))

    async def _document(self, doc_id: str) -> str:
        archive = zipfile.ZipFile(io.BytesIO(await self._get(f"/documents/{doc_id}", {"type": 5})))
        name = next(n for n in archive.namelist() if "jpcrp" in n and "-asr-" in n and n.endswith(".csv"))
        return archive.read(name).decode("utf-16")

    async def _loop(self):
        while True:
            try:
                saved = await collect(self.db, self._listing, self._document)
                if saved:
                    logger.info("EDINET: stored %d annual reports", saved)
            except Exception as exc:
                logger.warning("EDINET collection failed: %s", str(exc)[:120])
            await asyncio.sleep(self.INTERVAL_SECONDS)

    async def start(self):
        if not os.getenv("EDINET_API_KEY"):
            logger.info("EDINET collection off: EDINET_API_KEY not set")
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="edinet-financials")

    async def close(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


edinet_financials_collector = EdinetFinancialsCollector()
