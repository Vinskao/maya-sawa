"""Unified, low frequency market events from official public sources."""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from .market_fundamentals import market_fundamentals_service
from .market_insider_transfers import holding_events, insider_events, untransferred_events
from . import volume_rank

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Taipei")


def _today() -> date:
    return datetime.now(TZ).date()


TDCC_EVENTS_URL = "https://irplatform.tdcc.com.tw/ir/event/list?lang=zh&max=500&offset=1"


class _EventParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[dict[str, str]] = []
        self.depth = 0
        self.item: dict[str, str] | None = None
        self.capture: str | None = None
        self.buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = dict(attrs)
        classes = (attrs_map.get("class") or "").split()
        if tag == "div" and self.item is None and "active-box" in classes:
            self.item = {"title": "", "dateTime": "", "type": "", "url": ""}
            self.depth = 1
        elif self.item is not None and tag == "div":
            self.depth += 1
        if self.item is None:
            return
        if tag in ("h3", "time") or (tag == "span" and "meeting" in classes):
            self.capture = "type" if tag == "span" else ("dateTime" if tag == "time" else "title")
            self.buffer = []
        elif tag == "a" and attrs_map.get("href"):
            self.item["url"] = attrs_map["href"] or ""

    def handle_endtag(self, tag: str) -> None:
        if self.capture and ((tag == "h3" and self.capture == "title") or
                             (tag == "time" and self.capture == "dateTime") or
                             (tag == "span" and self.capture == "type")):
            if self.item is not None:
                self.item[self.capture] = " ".join("".join(self.buffer).split())
            self.capture = None
            self.buffer = []
        if self.item is not None and tag == "div":
            self.depth -= 1
            if self.depth == 0:
                if self.item.get("title") and self.item.get("dateTime"):
                    self.events.append(self.item)
                self.item = None

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.buffer.append(data)


def live_volumes_from_quotes(rows: list[dict], today: date) -> dict[str, float]:
    """Shares traded so far today, per stock, from quote rows; a quote stamped on an earlier day is yesterday's volume, not today's."""
    volumes: dict[str, float] = {}
    for row in rows:
        if row.get("productType") != "stock" or not row.get("volumeShares"):
            continue
        try:
            stamp = datetime.fromisoformat(str(row.get("timestamp")))
        except ValueError:
            continue
        if stamp.astimezone(TZ).date() == today:
            volumes[str(row.get("symbol", "")).strip()] = float(row["volumeShares"])
    return volumes


class MarketCompanyEventsService:
    def __init__(self) -> None:
        self._conference_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._conference_lock = asyncio.Lock()
        self._result_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
        # Set at startup to InsiderTransferDatabase.open_on; without a database no insider filings are shown.
        self.insider_source = lambda day: []
        # (untransferred filings, latest month's holding changes); set at startup like insider_source.
        self.insider_extra_source = lambda day: ([], [])
        # (code, today) -> [[date, shares], ...] for the trailing year; the intraday monitor's loader (database, else Yahoo).
        self.volume_history_source = None
        self._volume_histories: dict[tuple[str, str], list] = {}
        # (code, today) -> (history rows, today's running volume) for a Japanese stock; Yahoo's .T chart.
        self.japan_volume_source = None
        self._japan_volumes: dict[tuple[str, str], tuple[list, int | None]] = {}

    async def _conferences(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._conference_cache and now - self._conference_cache[0] < 900:
            return self._conference_cache[1]
        async with self._conference_lock:
            now = time.monotonic()
            if self._conference_cache and now - self._conference_cache[0] < 900:
                return self._conference_cache[1]

            def fetch() -> list[dict[str, Any]]:
                request = urllib.request.Request(TDCC_EVENTS_URL, headers={
                    "User-Agent": "TY-Multiverse-MarketDashboard/1.0",
                    "Accept": "text/html",
                })
                with urllib.request.urlopen(request, timeout=20) as response:
                    html = response.read().decode("utf-8", errors="replace")
                parser = _EventParser()
                parser.feed(html)
                output = []
                for row in parser.events:
                    if row.get("type", "").strip() != "\u6cd5\u8aaa\u6703":
                        continue
                    parts = row.get("title", "").split(maxsplit=1)
                    if not parts or not parts[0].isdigit() or len(parts[0]) != 4:
                        continue
                    output.append({"code": parts[0], "name": parts[1] if len(parts) > 1 else parts[0],
                                   "type": "investor_conference", "period": "", "dateTime": row["dateTime"],
                                   "date": row["dateTime"][:10].replace("/", "-"), "source": "TDCC IR Platform",
                                   "sourceUrl": row.get("url") or "https://irplatform.tdcc.com.tw/ir/event/list?lang=zh"})
                return output

            try:
                events = await asyncio.to_thread(fetch)
                self._conference_cache = (time.monotonic(), events)
                return events
            except Exception:
                logger.exception("TDCC investor-conference calendar unavailable")
                if self._conference_cache:
                    return self._conference_cache[1]
                return []

    def _volume_events(self, codes: list[str], names: dict[str, str], live: dict[str, float], today: date) -> list[dict]:
        """Stocks whose volume reached the yearly top 10 / top 5 on a day of this week (history read once per stock per day)."""
        source = self.volume_history_source
        if source is None:
            from .intraday_alerts import volume_history_for as source
        events = []
        week_start = today - timedelta(days=today.weekday())
        for code in codes:
            key = (code, today.isoformat())
            if key not in self._volume_histories:
                try:
                    self._volume_histories[key] = source(code, today)
                except Exception:
                    logger.warning("Volume history unavailable for %s", code, exc_info=True)
                    self._volume_histories[key] = []
            history = self._volume_histories[key]
            if len(volume_rank.trailing_volumes(history, today)) < volume_rank.MIN_HISTORY_DAYS:
                continue
            week = volume_rank.week_summary(history, today, week_start, live.get(code))
            event = volume_rank.volume_spike_event(code, names.get(code, code), week)
            if event:
                events.append(event)
        return events

    def _japan_volume_events(self, japan: list[dict], today: date) -> list[dict]:
        """The same weekly volume-rank mark for Tokyo-listed stocks, tagged market JP so it never lands on a Taiwan stock with the same digits."""
        source = self.japan_volume_source
        if source is None:
            from .intraday_alerts import japan_volume_history as source
        events = []
        week_start = today - timedelta(days=today.weekday())
        for item in japan:
            code = str(item.get("code", "")).strip().upper()
            key = (code, today.isoformat())
            if key not in self._japan_volumes:
                try:
                    self._japan_volumes[key] = source(code, today)
                except Exception:
                    logger.warning("Japan volume history unavailable for %s", code, exc_info=True)
                    self._japan_volumes[key] = ([], None)
            history, live = self._japan_volumes[key]
            if len(volume_rank.trailing_volumes(history, today)) < volume_rank.MIN_HISTORY_DAYS:
                continue
            event = volume_rank.volume_spike_event(code, item.get("name") or code, volume_rank.week_summary(history, today, week_start, live))
            if event:
                events.append({**event, "market": "JP"})
        return events

    async def get(self, codes: list[str], live_volumes: dict[str, float] | None = None, japan: list[dict] | None = None) -> dict[str, Any]:
        normalized = tuple(sorted({str(code).strip() for code in codes if str(code).strip().isdigit()
                                   and len(str(code).strip()) == 4}))
        japan = [item for item in (japan or []) if str(item.get("code", "")).strip()]
        now_mono = time.monotonic()
        cache_key = normalized + tuple(sorted("JP:" + str(item["code"]).strip().upper() for item in japan))
        cached = self._result_cache.get(cache_key)
        if cached and now_mono - cached[0] < 300:
            return cached[1]
        today = _today()
        releases = await market_fundamentals_service.published_events(list(normalized))
        conferences = await self._conferences()
        all_events: list[dict[str, Any]] = []
        for event in releases:
            try:
                event_day = date.fromisoformat(event["date"])
            except (TypeError, ValueError):
                continue
            age = (today - event_day).days
            if -1 <= age <= 7:
                all_events.append({**event, "status": "recent", "highlight": True})
        for event in conferences:
            if event["code"] not in normalized:
                continue
            try:
                event_day = date.fromisoformat(event["date"])
            except (TypeError, ValueError):
                continue
            days_until = (event_day - today).days
            if -1 <= days_until <= 21:
                all_events.append({**event,
                                   "date": event["date"],
                                   "status": "upcoming" if days_until >= 0 else "recent",
                                   "highlight": True})
        try:
            filings = await asyncio.to_thread(self.insider_source, today)
            all_events.extend(insider_events(filings, set(normalized), today))
            untransferred, changes = await asyncio.to_thread(self.insider_extra_source, today)
            all_events.extend(untransferred_events(untransferred, set(normalized), today))
            all_events.extend(holding_events(changes, set(normalized)))
        except Exception:
            logger.exception("Insider transfer filings unavailable")
        try:
            names = {event["code"]: event.get("name") or event["code"] for event in all_events}
            all_events.extend(await asyncio.to_thread(self._volume_events, list(normalized), names, live_volumes or {}, today))
        except Exception:
            logger.exception("Volume spikes unavailable")
        try:
            all_events.extend(await asyncio.to_thread(self._japan_volume_events, japan, today))
        except Exception:
            logger.exception("Japan volume spikes unavailable")
        all_events.sort(key=lambda event: (event["date"], event["code"], event["type"]))
        result = {"events": all_events, "checkedAt": datetime.now(TZ).isoformat(),
                  "sources": {"financialReleases": "TWSE OpenAPI / MOPS OTC", "conferences": "TDCC IR Platform",
                              "insiderTransfers": "TWSE OpenAPI t187ap12_L / TPEx OpenAPI mopsfin_t187ap12_O",
                              "volume": "TWSE / TPEx daily volume (database, else Yahoo), live volume from Shioaji"},
                  "highlightPolicy": {"releaseDays": 7, "conferenceDays": 21}}
        self._result_cache[cache_key] = (time.monotonic(), result)
        return result


market_company_events_service = MarketCompanyEventsService()
