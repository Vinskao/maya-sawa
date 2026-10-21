"""Japan holdings' financial history from J-Quants /v2/fins/summary (JPX; key JQUANTS_API_KEY).

TDnet keeps only a month of disclosures, so a holding added today would have no history. J-Quants serves the
決算短信 summary of every listed company; the free plan covers two years and stops 12 weeks before today, and
TDnet covers what came after. Each summary is the year to date (Q1 is three months), the same shape TDnet
releases have, so both merge in tdnet_financials.build_financials. Every field is a string; "" is no value.
Amounts are JPY, EPS is JPY/share. The key goes in the x-api-key header and is never logged, stored or
returned. Covered by tests/test_jquants_financials.py with real responses.
"""
from __future__ import annotations

import asyncio
import calendar
import logging
import os
from datetime import date

from .tdnet_financials import METRIC_NAMES, INSTANT_METRICS, rebuild_japan

logger = logging.getLogger(__name__)

API = "https://api.jquants.com/v2/fins/summary"
SCAN_INTERVAL_SECONDS = 24 * 3600
REQUEST_GAP_SECONDS = 13  # free plan: 5 requests a minute
STANDARDS = {"JP": "JGAAP", "IFRS": "IFRS", "US": "USGAAP", "JMIS": "JMIS", "Foreign": "Foreign"}
DURATION_METRICS = [metric for metric in METRIC_NAMES if metric not in INSTANT_METRICS]
RESULT_FIELDS = {"revenue": "Sales", "operatingIncome": "OP", "netIncome": "NP", "epsBasic": "EPS", "epsDiluted": "DEPS",
                 "operatingCashFlow": "CFO", "investingCashFlow": "CFI"}
# Forecast field prefixes: this year's (F...), its first half (F...2Q) and next year's (NxF...).
FORECAST_FIELDS = {"revenue": "Sales", "operatingIncome": "OP", "netIncome": "NP", "epsBasic": "EPS"}


def _value(record: dict, field: str) -> float | None:
    text = (record.get(field) or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _days(start: str, end: str) -> int:
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _duration(start: str, end: str, values: dict) -> dict:
    return {"start": start, "end": end, "durationDays": _days(start, end),
            **{metric: values.get(metric) for metric in DURATION_METRICS}}


def _forecast(record: dict, start: str, end: str, prefix: str, suffix: str = "") -> dict | None:
    # Next year's profit is "NxFNp", not "NxFNP".
    names = {metric: prefix + (field if not (prefix == "NxF" and field == "NP") else "Np") + suffix
             for metric, field in FORECAST_FIELDS.items()}
    values = {metric: _value(record, name) for metric, name in names.items()}
    if not start or not end or not any(v is not None for v in values.values()):
        return None
    return _duration(start, end, values)


def _owners_equity(record: dict) -> float | None:
    """自己資本: Eq is net assets, which includes minority interests under Japan GAAP; the equity ratio is owners'."""
    total, ratio, equity = _value(record, "TA"), _value(record, "EqAR"), _value(record, "Eq")
    if total is None or ratio is None:
        return equity
    derived = total * ratio
    return equity if equity is not None and abs(equity - derived) <= total * 0.0005 else round(derived)


def parse_summary(record: dict) -> dict | None:
    """One /fins/summary record -> a release shaped like tdnet_financials.parse_release, or None to skip it."""
    doc = record.get("DocType", "")
    statements = "FinancialStatements" in doc
    if doc.startswith("REIT") or not (statements or doc == "EarnForecastRevision"):
        return None
    suffix = doc.rsplit("_", 1)[-1] if statements else ""
    release = {"standard": STANDARDS.get(suffix), "consolidated": "_NonConsolidated" not in doc,
               "durations": [], "instants": [], "forecasts": [],
               "releasedAt": f"{record.get('DiscDate')}T{(record.get('DiscTime') or '00:00')[:5]}",
               "title": doc, "releaseId": record.get("DiscNo"), "docType": doc}
    period_start, period_end = record.get("CurPerSt", ""), record.get("CurPerEn", "")
    year_start, year_end = record.get("CurFYSt", ""), record.get("CurFYEn", "")
    if statements and period_start and period_end:
        values = {metric: _value(record, field) for metric, field in RESULT_FIELDS.items()}
        if any(v is not None for v in values.values()):
            release["durations"].append(_duration(period_start, period_end, values))
        sheet = {"assets": _value(record, "TA"), "equity": _owners_equity(record), "cash": _value(record, "CashEq")}
        if any(v is not None for v in sheet.values()):
            release["instants"].append({"end": period_end, **{m: sheet.get(m) for m in INSTANT_METRICS}})
    half_end = None
    if year_start:  # the first half ends five months after the fiscal year's first month
        index = int(year_start[:4]) * 12 + int(year_start[5:7]) - 1 + 5
        y, m = index // 12, index % 12 + 1
        half_end = date(y, m, calendar.monthrange(y, m)[1]).isoformat()
    candidates = [_forecast(record, year_start, half_end, "F", "2Q") if half_end else None]
    if record.get("CurPerType") != "FY":
        candidates.append(_forecast(record, year_start, year_end, "F"))
    candidates.append(_forecast(record, record.get("NxtFYSt", ""), record.get("NxtFYEn", ""), "NxF"))
    release["forecasts"] = [row for row in candidates if row]
    return release


async def collect(db, fetch) -> int:
    """Store summaries not seen before for every Japan holding and rebuild its financials. Returns summaries saved."""
    holdings = await asyncio.to_thread(db.market_codes, "JP")
    saved = 0
    for code in holdings:
        seen = {row["period"] for row in await asyncio.to_thread(db.history, code, "JP", "jquants_release")}
        records, params = [], {"code": code}
        while True:
            page = await fetch(params)
            records.extend(page.get("data") or [])
            if not page.get("pagination_key"):
                break
            params = {"code": code, "pagination_key": page["pagination_key"]}
        conid = ((await asyncio.to_thread(db.latest, code, "JP", "profile")) or {}).get("conid") or 0
        for record in records:
            number = record.get("DiscNo")
            if not number or number in seen:
                continue
            release = parse_summary(record)
            # Skipped documents are stored empty so they are not parsed again.
            await asyncio.to_thread(db.save, code, "JP", conid, "jquants_release", release or {}, period=number)
            seen.add(number)
            saved += 1 if release else 0
        # Rebuilt every pass, not only on new summaries, so a merge-rule fix reaches stored history on the next deploy.
        await asyncio.to_thread(rebuild_japan, db, code, conid)
    return saved


class JquantsFinancialsCollector:
    """Daily J-Quants backfill for Japan holdings; off when JQUANTS_API_KEY is unset."""

    def __init__(self, db=None):
        self._db = db
        self._task: asyncio.Task | None = None

    @property
    def db(self):
        if self._db is None:
            from ..databases.ibkr_research_db import get_ibkr_research_db
            self._db = get_ibkr_research_db()
        return self._db

    async def _fetch(self, params: dict) -> dict:
        import httpx
        await asyncio.sleep(REQUEST_GAP_SECONDS)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(API, params=params, headers={"x-api-key": os.getenv("JQUANTS_API_KEY", "")})
        except Exception as exc:
            raise RuntimeError(f"jquants_request_failed:{type(exc).__name__}") from None
        if response.status_code != 200:
            raise RuntimeError(f"jquants_http_{response.status_code}")
        return response.json()

    async def _loop(self):
        while True:
            try:
                saved = await collect(self.db, self._fetch)
                if saved:
                    logger.info("J-Quants: stored %d new Japan summaries", saved)
            except Exception as exc:
                logger.warning("J-Quants collection failed: %s", str(exc)[:120])
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)

    async def start(self):
        if not os.getenv("JQUANTS_API_KEY"):
            logger.info("J-Quants collection off: JQUANTS_API_KEY not set")
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="jquants-financials")

    async def close(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


jquants_financials_collector = JquantsFinancialsCollector()
