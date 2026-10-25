"""Broker target prices for the dashboard's instruments.

Yahoo Finance quoteSummary is the automatic source: `upgradeDowngradeHistory` lists each broker's rating and target
(US listings only; measured 2026-10-25: LITE 351 actions, 2330.TW / 3081.TWO / 6857.T none) and `financialData`
gives the consensus mean/median/high/low and analyst count for every market. It is an unofficial endpoint that needs
a session cookie and crumb, so a failure is logged and retried the next day, never fatal. Taiwan and Japan per-broker
targets come from the scheduled AI routine (news with a source URL), written through PUT /dashboard/targets.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)
TAIPEI = ZoneInfo("Asia/Taipei")
NEW_YORK = ZoneInfo("America/New_York")  # Yahoo's broker history covers US listings: date it as the broker did
MARKET_CURRENCY = {"US": "USD", "TW": "TWD", "JP": "JPY", "KR": "KRW", "HK": "HKD"}
SUFFIXES = {"TW": [".TW", ".TWO"], "JP": [".T"], "KR": [".KS", ".KQ"], "HK": [".HK"], "US": [""]}
RUN_AT = (8, 30)  # Taipei: after the US close and the overnight broker notes; Asian consensus changes slowly
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def _raw(value):
    value = value.get("raw") if isinstance(value, dict) else value
    return float(value) if isinstance(value, (int, float)) and value == value else None


def _positive(value):
    number = _raw(value)
    return number if number is not None and number > 0 else None


def parse_yahoo_targets(payload: dict) -> dict:
    """Consensus and per-broker actions; Yahoo's 0.0 target and '' grade mean "none"."""
    result = ((payload.get("quoteSummary") or {}).get("result") or [None])[0] or {}
    financial = result.get("financialData") or {}
    consensus = None
    if _positive(financial.get("targetMeanPrice")) is not None:
        analysts = _raw(financial.get("numberOfAnalystOpinions"))
        consensus = {"mean": _positive(financial.get("targetMeanPrice")), "median": _positive(financial.get("targetMedianPrice")),
                     "high": _positive(financial.get("targetHighPrice")), "low": _positive(financial.get("targetLowPrice")),
                     "analysts": int(analysts) if analysts is not None else None,
                     "currency": financial.get("financialCurrency")}
    actions = []
    for row in (result.get("upgradeDowngradeHistory") or {}).get("history") or []:
        firm, stamp = str(row.get("firm") or "").strip(), row.get("epochGradeDate")
        if not firm or not isinstance(stamp, (int, float)):
            continue
        actions.append({"firm": firm, "date": datetime.fromtimestamp(stamp, NEW_YORK).date().isoformat(),
                        "action": row.get("priceTargetAction") or None, "rating": row.get("toGrade") or None,
                        "previousRating": row.get("fromGrade") or None, "target": _positive(row.get("currentPriceTarget")),
                        "previousTarget": _positive(row.get("priorPriceTarget"))})
    return {"consensus": consensus, "actions": actions}


def yahoo_symbols(code: str, market: str) -> list[str]:
    code = code.strip().upper()
    if market == "TW" and not (code.isdigit() and len(code) == 4):
        return []  # futures and options have no analyst targets
    return [code.replace(".", "-") + suffix for suffix in SUFFIXES.get(market, [])]


def collect(db, instruments: list[dict], fetch, today: date) -> dict[str, str]:
    """Store each stock's consensus snapshot and broker actions; a failed instrument is skipped, not fatal."""
    results = {}
    for item in instruments:
        code, market = str(item.get("code") or "").upper(), str(item.get("market") or "TW").upper()
        if item.get("productType", "stock") != "stock" or not (symbols := yahoo_symbols(code, market)):
            continue
        try:
            for symbol in symbols:
                parsed = parse_yahoo_targets(fetch(symbol))
                if parsed["consensus"] or parsed["actions"]:
                    break
            currency = MARKET_CURRENCY.get(market) or (parsed["consensus"] or {}).get("currency") or ""
            url = f"https://finance.yahoo.com/quote/{symbol}/analysis"
            if parsed["actions"]:
                db.save_actions(code, market, currency, parsed["actions"], source="yahoo", source_url=url)
            if parsed["consensus"]:
                db.save_consensus(code, market, today, {**parsed["consensus"], "currency": currency}, source="yahoo")
            results[code] = "ok" if parsed["consensus"] or parsed["actions"] else "no_data"
        except Exception as exc:
            logger.warning("Price targets for %s %s unavailable: %s", code, market, type(exc).__name__)
            results[code] = "error"
    return results


def validate_routine_actions(rows: list[dict], today: date) -> list[dict]:
    """Targets the AI routine found in news: each needs the firm, a past date, a positive target and its article."""
    clean = []
    for row in rows:
        firm, day, url = str(row.get("firm") or "").strip(), str(row.get("date") or ""), str(row.get("sourceUrl") or "")
        target = row.get("target")
        if not firm or len(firm) > 80:
            raise ValueError("firm is required")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) or date.fromisoformat(day) > today:
            raise ValueError("date must be YYYY-MM-DD and not in the future")
        if not isinstance(target, (int, float)) or isinstance(target, bool) or not target > 0:
            raise ValueError("target must be a positive number")
        if not re.match(r"https?://", url):
            raise ValueError("sourceUrl must be the article's http(s) URL")
        previous = row.get("previousTarget")
        clean.append({"firm": firm, "date": day, "action": row.get("action") or None, "rating": row.get("rating") or None,
                      "previousRating": row.get("previousRating") or None, "target": float(target),
                      "previousTarget": float(previous) if isinstance(previous, (int, float)) and previous > 0 else None,
                      "sourceUrl": url})
    return clean


class YahooTargets:
    """quoteSummary needs Yahoo's session cookie and a crumb; both are refreshed once on a 401."""

    def __init__(self):
        self.client = httpx.Client(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
        self.crumb = None

    def _refresh(self):
        self.client.get("https://fc.yahoo.com/")  # sets the session cookie; the 404 is expected
        response = self.client.get("https://query2.finance.yahoo.com/v1/test/getcrumb")
        response.raise_for_status()
        self.crumb = response.text.strip()

    def fetch(self, symbol: str) -> dict:
        for attempt in range(2):
            if not self.crumb:
                self._refresh()
            response = self.client.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                                       params={"modules": "upgradeDowngradeHistory,financialData", "crumb": self.crumb})
            if response.status_code == 401 and attempt == 0:
                self.crumb = None
                continue
            if response.status_code == 404:
                return response.json()  # unknown symbol: {"quoteSummary": {"result": null, "error": ...}}
            response.raise_for_status()
            return response.json()
        return {}


def watched_instruments() -> list[dict]:
    from .market_selection import current_selection
    return [item for item in current_selection()[1] if item.get("productType") == "stock"]


class PriceTargetCollector:
    def __init__(self):
        self._task: asyncio.Task | None = None

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def close(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def collect_now(self, instruments: list[dict] | None = None) -> dict[str, str]:
        from ..databases.market_price_target_db import market_price_target_db
        if not market_price_target_db.sessions:
            return {}
        items = instruments if instruments is not None else await asyncio.to_thread(watched_instruments)
        client = YahooTargets()
        try:
            return await asyncio.to_thread(collect, market_price_target_db, items, client.fetch, datetime.now(TAIPEI).date())
        finally:
            client.client.close()

    async def _loop(self):
        await asyncio.sleep(90)  # let the app settle; the first pass fills today's snapshot after a deploy
        while True:
            try:
                logger.info("Price targets collected: %s", await self.collect_now())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Price target collection failed")
            now = datetime.now(TAIPEI)
            run = now.replace(hour=RUN_AT[0], minute=RUN_AT[1], second=0, microsecond=0)
            await asyncio.sleep(((run if run > now else run + timedelta(days=1)) - now).total_seconds())


price_target_collector = PriceTargetCollector()
