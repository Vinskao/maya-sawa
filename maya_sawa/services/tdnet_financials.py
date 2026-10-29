"""Japan holdings' financials from TDnet 決算短信 / 業績予想の修正 XBRL (TSE timely disclosure; free, no key).

TDnet keeps about a month of disclosures, so releases are stored as they appear and the quarterly view is
rebuilt from everything stored. Japan dropped statutory quarterly reports in 2024; 決算短信 still report
year-to-date figures each quarter, so a single quarter is either reported as three months (Q1) or derived
as the difference of two consecutive year-to-date releases (marked derivedFromYtd). Amounts are JPY, not
millions; EPS is JPY/share. Covered by tests/test_tdnet_financials.py with real TDnet fixtures.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import zipfile
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

TDNET_BASE = "https://www.release.tdnet.info/inbs/"
MAX_ZIP_BYTES = 10 * 1024 * 1024
SOURCE = "TDnet 決算短信 (Tokyo Stock Exchange timely disclosure)"

# Local XBRL names per metric, most specific first. Summary (tse-ed-t) and attachment (jppfs_cor / jpigp_cor)
# names are both listed; attachments are in thousands of yen or yen and take precedence over the summary's millions.
METRIC_NAMES = {
    "revenue": ["NetSales", "SalesIFRS", "NetSalesIFRS", "RevenueIFRS", "Revenue", "OperatingRevenue1", "NetSalesUS"],
    "costOfRevenue": ["CostOfSales", "CostOfSalesIFRS"],
    "grossProfit": ["GrossProfit", "GrossProfitIFRS"],
    "operatingIncome": ["OperatingIncome", "OperatingIncomeIFRS", "OperatingProfitLossIFRS", "OperatingIncomeUS"],
    "netIncome": ["ProfitAttributableToOwnersOfParent", "ProfitAttributableToOwnersOfParentIFRS",
                  "ProfitLossAttributableToOwnersOfParentIFRS", "NetIncomeUS"],
    "epsBasic": ["NetIncomePerShare", "BasicEarningsPerShareIFRS", "BasicEarningsLossPerShareIFRS"],
    "epsDiluted": ["DilutedNetIncomePerShare", "DilutedEarningsPerShareIFRS", "DilutedEarningsLossPerShareIFRS"],
    "operatingCashFlow": ["CashFlowsFromOperatingActivities", "CashFlowsFromOperatingActivitiesIFRS",
                          "NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesIFRS"],
    "investingCashFlow": ["CashFlowsFromInvestingActivities", "CashFlowsFromInvestingActivitiesIFRS",
                          "NetCashProvidedByUsedInInvestingActivities", "NetCashProvidedByUsedInInvestingActivitiesIFRS"],
    "assets": ["Assets", "AssetsIFRS", "TotalAssets", "TotalAssetsIFRS"],
    "liabilities": ["Liabilities", "LiabilitiesIFRS"],
    "equity": ["EquityAttributableToOwnersOfParentIFRS", "OwnersEquity", "ShareholdersEquity", "NetAssets", "TotalEquityIFRS"],
    "inventory": ["Inventories", "InventoriesIFRS", "InventoriesCAIFRS"],
    "cash": ["CashAndDeposits", "CashAndCashEquivalentsIFRS", "CashAndCashEquivalentsAtEndOfPeriodIFRS"],
    "currentAssets": ["CurrentAssets", "CurrentAssetsIFRS"],
    "currentLiabilities": ["CurrentLiabilities", "TotalCurrentLiabilitiesIFRS", "CurrentLiabilitiesIFRS"],
    # Shown as an outflow (sign="-"); stored positive like SEC and OpenDART capex.
    "capitalExpenditure": ["PurchaseOfPropertyPlantAndEquipmentInvCF", "PurchaseOfPropertyPlantAndEquipmentInvCFIFRS"],
}
INSTANT_METRICS = {"assets", "liabilities", "equity", "inventory", "cash", "currentAssets", "currentLiabilities"}
# Japan GAAP balance sheets often itemize inventory instead of reporting a total.
INVENTORY_PARTS = ["MerchandiseAndFinishedGoods", "WorkInProcess", "RawMaterialsAndSupplies", "Merchandise", "FinishedGoods", "RawMaterials", "Supplies"]
ADDITIVE = ("revenue", "costOfRevenue", "grossProfit", "operatingIncome", "netIncome", "operatingCashFlow", "investingCashFlow",
            "capitalExpenditure")
_NAME_RANK = {(metric, name): rank for metric, names in METRIC_NAMES.items() for rank, name in enumerate(names)}
_METRIC_OF = {}
for _metric, _names in METRIC_NAMES.items():
    for _name in _names:
        _METRIC_OF.setdefault(_name, []).append(_metric)


def tdnet_code(code: str) -> str:
    """TDnet lists securities by five characters: the four-character code plus a trailing 0."""
    return f"{code.strip().upper()}0"


def parse_list_page(html: str) -> tuple[list[dict], bool]:
    rows = []
    for raw in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        code = re.search(r'kjCode"[^>]*>\s*(\w+)', raw)
        title = re.search(r'kjTitle"[^>]*>\s*<a[^>]*>([^<]+)', raw)
        archive = re.search(r'href="([^"]+\.zip)"', raw)
        stamp = re.search(r'kjTime"[^>]*>\s*([0-9:]+)', raw)
        if code and title and archive:
            rows.append({"code": code.group(1), "title": title.group(1).strip(), "time": stamp.group(1) if stamp else None,
                         "zipUrl": archive.group(1) if archive.group(1).startswith("http") else TDNET_BASE + archive.group(1)})
    # Pager links to other pages of the same day, so a later page exists while more than one page is linked.
    return rows, len(set(re.findall(r"I_list_(\d{3})_\d{8}\.html", html))) > 1


def _number(text: str, attrs: str) -> float | None:
    if re.search(r'xsi:nil="true"', attrs):
        return None
    cleaned = re.sub(r"<[^>]+>", "", text).replace(",", "").replace("△", "").replace("▲", "").strip()
    if not cleaned or cleaned in ("-", "－", "―"):
        return None
    try:
        value = float(cleaned)
    except ValueError:
        return None
    scale = re.search(r'scale="(-?\d+)"', attrs)
    if scale:
        value *= 10 ** int(scale.group(1))
    if re.search(r'sign="-"', attrs):
        value = -value
    return round(value, 6) if abs(value) < 1e6 else round(value)


def _contexts(html: str) -> dict:
    found = {}
    for cid, body in re.findall(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', html, re.S):
        period = dict(re.findall(r"<xbrli:(startDate|endDate|instant)>\s*([^<\s]+)", body))
        dims = {axis.split(":")[-1]: member.split(":")[-1] for axis, member in re.findall(r'dimension="([^"]+)">\s*([^<\s]+)', body)}
        found[cid] = {"period": period, "dims": dims}
    return found


def _classify(dims: dict) -> tuple[str | None, str]:
    """(role, consolidation) for a context, or role None when the fact is not a company-wide figure we keep."""
    dims = dict(dims)
    scope = dims.pop("ConsolidatedNonconsolidatedAxis", "ConsolidatedMember")
    if dims.pop("PreviousCurrentAxis", "CurrentMember") != "CurrentMember":
        return None, scope  # a revision's superseded forecast
    role = {"ResultMember": "result", "ForecastMember": "forecast"}.get(dims.pop("ResultForecastAxis", "ResultMember"))
    if dims:  # segments, ranges (Upper/Lower) and any other breakdown
        return None, scope
    return role, scope


def parse_release(data: bytes) -> dict:
    archive = zipfile.ZipFile(io.BytesIO(data))
    pages = [archive.read(name).decode("utf-8", errors="replace") for name in archive.namelist() if name.endswith("ixbrl.htm")]
    contexts = {}
    for page in pages:
        contexts.update(_contexts(page))
    facts = []  # (metric_or_part, name_rank, from_attachment, role, scope, period key, value)
    standard = "JGAAP"
    for page in pages:
        attachment = 'name="tse-ed-t:' not in page  # statements, not the summary sheet
        # Blank (xsi:nil) facts are self-closing; matching them as open tags would swallow the facts after them.
        for attrs, text in re.findall(r"<ix:nonFraction((?:[^>/]|/(?!>))*)(?:/>|>(.*?)</ix:nonFraction>)", page, re.S):
            name = re.search(r'name="([^"]+)"', attrs)
            ref = re.search(r'contextRef="([^"]+)"', attrs)
            if not name or not ref or ref.group(1) not in contexts:
                continue
            local = name.group(1).split(":")[-1]
            if local.endswith("IFRS"):
                standard = "IFRS"
            elif local.endswith("US") and standard != "IFRS":
                standard = "USGAAP"
            metrics = _METRIC_OF.get(local, []) + (["inventoryPart:" + local] if local in INVENTORY_PARTS else [])
            if not metrics:
                continue
            context = contexts[ref.group(1)]
            role, scope = _classify(context["dims"])
            if role is None:
                continue
            value = _number(text, attrs)
            period = context["period"]
            key = ("instant", period["instant"]) if "instant" in period else ("duration", period.get("startDate"), period.get("endDate"))
            for metric in metrics:
                facts.append((metric, _NAME_RANK.get((metric, local), 0), attachment, role, scope, key, value))
    scopes = {fact[4] for fact in facts}
    scope = "ConsolidatedMember" if "ConsolidatedMember" in scopes else "NonConsolidatedMember"
    chosen: dict = {}
    for metric, rank, attachment, role, fact_scope, key, value in facts:
        if fact_scope != scope:
            continue
        slot = (role, key, metric)
        # The right concept first (owners' equity over net assets), then the more precise attachment.
        priority = (value is not None, -rank, attachment)
        if slot not in chosen or priority > chosen[slot][0]:
            chosen[slot] = (priority, value)
    rows: dict = {}
    for (role, key, metric), (_, value) in chosen.items():
        row = rows.setdefault((role, key), {})
        if metric.startswith("inventoryPart:"):
            row.setdefault("_parts", {})[metric.split(":", 1)[1]] = value
        else:
            row[metric] = value
    release = {"standard": standard, "consolidated": scope == "ConsolidatedMember", "durations": [], "instants": [], "forecasts": []}
    for (role, key), row in sorted(rows.items(), key=lambda item: item[0][1]):
        parts = row.pop("_parts", {})
        if key[0] == "instant":
            if row.get("inventory") is None and any(v is not None for v in parts.values()):
                row["inventory"] = sum(v for v in parts.values() if v is not None)
            values = {m: row.get(m) for m in INSTANT_METRICS}
            if role == "result" and any(v is not None for v in values.values()):
                release["instants"].append({"end": key[1], **values})
            continue
        start, end = key[1], key[2]
        if not start or not end:
            continue
        values = {m: row.get(m) for m in METRIC_NAMES if m not in INSTANT_METRICS}
        if not any(v is not None for v in values.values()):
            continue
        entry = {"start": start, "end": end, "durationDays": (date.fromisoformat(end) - date.fromisoformat(start)).days, **values}
        if entry["capitalExpenditure"] is not None:
            entry["capitalExpenditure"] = abs(entry["capitalExpenditure"])
        if entry["grossProfit"] is None and entry["revenue"] is not None and entry["costOfRevenue"] is not None:
            entry["grossProfit"] = entry["revenue"] - entry["costOfRevenue"]
        (release["durations"] if role == "result" else release["forecasts"]).append(entry)
    return release


def _with_margins(row: dict) -> dict:
    revenue = row.get("revenue")
    for key, metric in (("grossMarginPercent", "grossProfit"), ("operatingMarginPercent", "operatingIncome"), ("netMarginPercent", "netIncome")):
        value = row.get(metric)
        row[key] = round(value / revenue * 100, 4) if revenue and value is not None else None
    return row


JP_NOTES = ["All monetary amounts are JPY, not millions; EPS is JPY/share.",
            "Japan has no statutory quarterly reports since 2024: 決算短信 report year-to-date figures, and a single "
            "quarter after Q1 is the difference of two consecutive year-to-date releases (derivedFromYtd).",
            "TDnet keeps about one month of disclosures; earlier history is J-Quants (JPX) summaries, two years ending "
            "12 weeks back on the free plan, so a holding added mid-quarter can miss its latest quarter for a while.",
            "Forecasts are the company's own guidance, not analyst consensus."]


def build_financials(releases: list[dict], *, currency: str = "JPY", source: str = SOURCE, notes: list[str] | None = None) -> dict:
    """Merge stored releases (oldest first; later corrections win) into the SEC-shaped payload the page draws.

    Shared with OpenDART (dart_financials.py) and J-Quants (jquants_financials.py). Rows for the same period merge
    metric by metric, so a release that left a figure blank keeps the earlier value; at the same release time the
    higher `precedence` wins (TDnet's attachments over the J-Quants summary of the same 決算短信). A quarter
    reported as three months beats the same quarter derived from year-to-date differences."""
    durations: dict = {}
    instants: dict = {}
    forecasts: dict = {}
    ordered = sorted(releases, key=lambda release: ((release.get("releasedAt") or "")[:16], release.get("precedence", 1)))

    def merge(store, key, row, evidence):
        known = store.get(key, {})
        store[key] = {**known, **{k: v for k, v in row.items() if v is not None or k not in known},
                      "currency": currency, "evidence": evidence}

    for release in ordered:
        evidence = {"releasedAt": release.get("releasedAt"), "title": release.get("title"), "zipUrl": release.get("zipUrl")}
        for row in release.get("durations", []):
            merge(durations, (row["start"], row["end"]), row, evidence)
        for row in release.get("instants", []):
            merge(instants, row["end"], row, evidence)
        for row in release.get("forecasts", []):
            merge(forecasts, (row["start"], row["end"]), row, evidence)
    quarterly, cumulative, annual = [], [], []
    by_start: dict = {}
    for row in durations.values():
        by_start.setdefault(row["start"], []).append(row)
    for start, rows in by_start.items():
        rows.sort(key=lambda row: row["end"])
        for index, row in enumerate(rows):
            days = row["durationDays"]
            if days >= 330:
                annual.append(_with_margins(dict(row, periodType="annual")))
            elif days > 120:
                cumulative.append(_with_margins(dict(row, periodType="cumulative")))
            if days <= 120:
                quarterly.append(_with_margins(dict(row, periodType="quarterly")))
                continue
            previous = rows[index - 1] if index else None
            if previous and 75 <= days - previous["durationDays"] <= 105:
                quarter = {"start": (date.fromisoformat(previous["end"]) + timedelta(days=1)).isoformat(), "end": row["end"],
                           "durationDays": days - previous["durationDays"], "currency": currency, "periodType": "quarterly",
                           "derivedFromYtd": True, "evidence": row["evidence"], "epsBasic": None, "epsDiluted": None}
                for metric in ADDITIVE:
                    a, b = row.get(metric), previous.get(metric)
                    quarter[metric] = a - b if a is not None and b is not None else None
                quarterly.append(_with_margins(quarter))
    reported = {(row["start"], row["end"]) for row in quarterly if not row.get("derivedFromYtd")}
    quarterly = [row for row in quarterly if not row.get("derivedFromYtd") or (row["start"], row["end"]) not in reported]
    latest = ordered[-1] if ordered else {}
    # A forecast revision states no accounting standard; take the newest release that does.
    standard = next((release["standard"] for release in reversed(ordered) if release.get("standard")), None)
    return {
        "source": source, "standard": standard, "company": latest.get("company"),
        "sourceUrl": latest.get("zipUrl"),
        "quarterly": sorted(quarterly, key=lambda row: row["end"])[-20:],
        "annual": sorted(annual, key=lambda row: row["end"])[-5:],
        "cumulative": sorted(cumulative, key=lambda row: row["end"])[-10:],
        "balanceSheet": sorted(instants.values(), key=lambda row: row["end"])[-20:],
        "forecasts": sorted(forecasts.values(), key=lambda row: row["end"])[-4:],
        "notes": notes if notes is not None else JP_NOTES,
    }


def _content_period(data) -> str:
    return "content-" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def collect(db, fetch, *, days: list[str] | None = None, today: date | None = None) -> int:
    """Scan TDnet day lists for the Japan holdings and store new results releases. Returns releases saved."""
    holdings = {tdnet_code(code): code for code in await asyncio.to_thread(db.market_codes, "JP")}
    if not holdings:
        return 0
    if days is None:
        today = today or datetime.now(timezone(timedelta(hours=9))).date()
        days = [(today - timedelta(days=back)).isoformat() for back in range(0, 3)]
    saved = 0
    touched = set()
    seen: dict = {}
    for day in days:
        stamp = day.replace("-", "")
        for page in range(1, 30):
            try:
                html = (await fetch(f"{TDNET_BASE}I_list_{page:03d}_{stamp}.html")).decode("utf-8", errors="replace")
            except Exception:
                break  # no page (holiday, future page) ends the day
            rows, _ = parse_list_page(html)
            for row in rows:
                code = holdings.get(row["code"])
                if not code or not re.search(r"決算短信|業績予想|訂正", row["title"]):
                    continue
                release_id = row["zipUrl"].rsplit("/", 1)[-1].removesuffix(".zip")
                if code not in seen:
                    seen[code] = {row["period"] for row in await asyncio.to_thread(db.history, code, "JP", "tdnet_release")}
                if release_id in seen[code]:
                    continue
                try:
                    data = await fetch(row["zipUrl"])
                    if len(data) > MAX_ZIP_BYTES:
                        raise ValueError("TDnet archive too large")
                    release = parse_release(data)
                except Exception as exc:
                    logger.warning("TDnet release %s for %s unreadable: %s", release_id, code, type(exc).__name__)
                    continue
                release.update(releasedAt=f"{day}T{row['time'] or '00:00'}", title=row["title"], zipUrl=row["zipUrl"], releaseId=release_id)
                conid = ((await asyncio.to_thread(db.latest, code, "JP", "profile")) or {}).get("conid") or 0
                await asyncio.to_thread(db.save, code, "JP", conid, "tdnet_release", release, period=release_id)
                seen[code].add(release_id)
                touched.add((code, conid))
                saved += 1
            if f"I_list_{page + 1:03d}_{stamp}.html" not in html:
                break
            await asyncio.sleep(0.5)
    for code, conid in touched:
        await asyncio.to_thread(rebuild_japan, db, code, conid)
    return saved


JQUANTS_SOURCE = "J-Quants 決算短信サマリー (JPX)"


def rebuild_japan(db, code: str, conid) -> dict:
    """Financials from every stored TDnet release and J-Quants summary of one Japan holding."""
    tdnet = [row["payload"] for row in db.history(code, "JP", "tdnet_release")]
    jquants = [{**row["payload"], "precedence": 0} for row in db.history(code, "JP", "jquants_release") if row["payload"]]
    source = " + ".join(name for name, rows in ((SOURCE, tdnet), (JQUANTS_SOURCE, jquants)) if rows) or SOURCE
    data = build_financials(tdnet + jquants, source=source)
    db.save(code, "JP", conid, "financials", data, period=_content_period(data))
    return data


TDNET_RETENTION_DAYS = 31
SCAN_INTERVAL_SECONDS = 3 * 3600
SCAN_MARKER = ("_TDNET", "JP", "tdnet_scan")


def scan_days(last_through: str | None, today: date) -> list[str]:
    """Days to scan, newest first: a month on first run, otherwise from the day before the last scan (at least 3 days)."""
    if last_through is None:
        back = TDNET_RETENTION_DAYS - 1
    else:
        back = min(TDNET_RETENTION_DAYS - 1, max(2, (today - date.fromisoformat(last_through)).days + 1))
    return [(today - timedelta(days=offset)).isoformat() for offset in range(0, back + 1)]


class TdnetFinancialsCollector:
    """Background TDnet scan for Japan holdings; independent of the IBKR login."""

    def __init__(self, db=None):
        self._db = db
        self._task: asyncio.Task | None = None

    @property
    def db(self):
        if self._db is None:
            from ..databases.ibkr_research_db import get_ibkr_research_db
            self._db = get_ibkr_research_db()
        return self._db

    async def _fetch(self, url: str) -> bytes:
        import httpx
        async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; TYMultiverseResearch/1.0; +https://peoplesystem.tatdvsonorth.com)"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.content

    async def run_once(self) -> int:
        today = datetime.now(timezone(timedelta(hours=9))).date()
        marker = await asyncio.to_thread(self.db.latest, *SCAN_MARKER)
        days = scan_days((marker or {}).get("payload", {}).get("through"), today)
        saved = await collect(self.db, self._fetch, days=days)
        await asyncio.to_thread(self.db.save, *SCAN_MARKER[:2], 0, SCAN_MARKER[2], {"through": today.isoformat(), "saved": saved})
        return saved

    async def _loop(self):
        while True:
            try:
                saved = await self.run_once()
                if saved:
                    logger.info("TDnet: stored %d new Japan releases", saved)
            except Exception:
                logger.exception("TDnet financials scan failed")
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def start(self):
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="tdnet-financials")

    async def close(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


tdnet_financials_collector = TdnetFinancialsCollector()
