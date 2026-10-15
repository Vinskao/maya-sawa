"""Unified, low frequency market events from official public sources."""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from typing import Any
from zoneinfo import ZoneInfo

from .market_fundamentals import market_fundamentals_service

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Taipei")
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


class MarketCompanyEventsService:
    def __init__(self) -> None:
        self._conference_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._conference_lock = asyncio.Lock()
        self._result_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}

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

    async def get(self, codes: list[str]) -> dict[str, Any]:
        normalized = tuple(sorted({str(code).strip() for code in codes if str(code).strip().isdigit()
                                   and len(str(code).strip()) == 4}))
        now_mono = time.monotonic()
        cached = self._result_cache.get(normalized)
        if cached and now_mono - cached[0] < 300:
            return cached[1]
        today = datetime.now(TZ).date()
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
        all_events.sort(key=lambda event: (event["date"], event["code"], event["type"]))
        result = {"events": all_events, "checkedAt": datetime.now(TZ).isoformat(),
                  "sources": {"financialReleases": "TWSE OpenAPI / MOPS OTC", "conferences": "TDCC IR Platform"},
                  "highlightPolicy": {"releaseDays": 7, "conferenceDays": 21}}
        self._result_cache[normalized] = (time.monotonic(), result)
        return result


market_company_events_service = MarketCompanyEventsService()
