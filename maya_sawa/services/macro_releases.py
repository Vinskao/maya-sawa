"""Real-time Telegram notices for central-bank rate decisions and the main US data releases (docs/MACRO_RELEASES.md).

Official sources only, no AI: the decision sentence is cut from the statement itself and the BLS numbers are computed
from the official series. Each source is polled slowly most of the time and every few seconds inside its own release
window (local time of that market), so a 14:00 New York FOMC statement or an 08:30 New York CPI print reaches the owner
within seconds. Every release is announced once (AutomationStore key), with a copy in the site's notification bell.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TICK_SECONDS = 5
FRESH_HOURS = 12
BLS_SECONDS = 15
_DAY = date(1970, 1, 3)  # stable primary-key date for release dedupe in AutomationStore
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Window:
    tz: str
    start: time
    end: time
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    months: tuple[int, ...] | None = None

    def contains(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(self.tz))
        if local.weekday() not in self.weekdays or (self.months and local.month not in self.months):
            return False
        return self.start <= local.time() <= self.end


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    url: str
    title_pattern: str
    normal_seconds: int
    burst_seconds: int
    windows: tuple[Window, ...] = ()
    sentence_pattern: str | None = None   # sentence to quote from the statement as the summary
    sentence_from: str = "page"           # 'page' (fetch the link) or 'description' (feed item text)
    exclude_pattern: str | None = None

    def matches(self, title: str) -> bool:
        if self.exclude_pattern and re.search(self.exclude_pattern, title, re.I):
            return False
        return re.search(self.title_pattern, title, re.I) is not None


SOURCES: dict[str, Source] = {s.key: s for s in (
    Source("fed", "美國 Fed 利率決策", "https://www.federalreserve.gov/feeds/press_monetary.xml",
           r"issues FOMC statement", 120, 5,
           (Window("America/New_York", time(13, 59), time(14, 20), (2,)),),
           sentence_pattern=r"The Committee decided to [^.]{0,300}?federal funds rate[^.]*?percent"),
    Source("ecb", "歐洲央行利率決策", "https://www.ecb.europa.eu/rss/press.html",
           r"^\s*Monetary policy decisions", 300, 10,
           (Window("Europe/Berlin", time(14, 14), time(14, 35), (3,)),),
           sentence_pattern=r"The Governing Council (?:today )?decided to [^.]{0,400}\."),
    Source("boe", "英國央行利率決策", "https://www.bankofengland.co.uk/rss/news",
           r"^\s*Bank Rate (maintained|increased|reduced|cut|raised)", 300, 10,
           (Window("Europe/London", time(11, 59), time(12, 20), (3,)),)),
    Source("boj", "日本央行利率決策", "https://www.boj.or.jp/en/rss/whatsnew.xml",
           r"Statement on Monetary Policy", 300, 20,
           (Window("Asia/Tokyo", time(11, 30), time(13, 30)),)),
    Source("cbc", "台灣央行利率決策", "https://www.cbc.gov.tw/tw/rss-302-1.xml",  # ~1.7 MB gzip: poll gently
           r"理監事聯席會議決議", 30 * 60, 20,
           (Window("Asia/Taipei", time(15, 59), time(16, 30), (3,), (3, 6, 9, 12)),),
           sentence_pattern=r"[^。：>]{0,120}重貼現率[^。]*。", sentence_from="description", exclude_pattern=r"議事錄"),
    Source("bea", "美國 GDP／PCE", "https://apps.bea.gov/rss/rss.xml",
           r"^\s*(GDP[ ,(]|Personal Income and Outlays)", 10 * 60, 10,
           (Window("America/New_York", time(8, 29), time(8, 40)),),
           exclude_pattern=r"\bby (State|County|Industry|Metropolitan)"),
)}

BLS_SERIES = ("CUUR0000SA0", "CUSR0000SA0", "CUUR0000SA0L1E", "CES0000000001", "LNS14000000")
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


def poll_seconds(now: datetime, source: Source) -> int:
    return source.burst_seconds if any(w.contains(now) for w in source.windows) else source.normal_seconds


def in_us_data_window(now: datetime) -> bool:
    local = now.astimezone(NY)
    # 08:29:45-08:33 every 15 s is 14 calls a day with the baseline: inside BLS's 25/day keyless limit.
    return local.weekday() < 5 and time(8, 29, 45) <= local.time() <= time(8, 33)


def _bls_baseline_time(now: datetime) -> bool:
    local = now.astimezone(NY)
    return local.weekday() < 5 and time(8, 20) <= local.time() < time(8, 29, 45)


# ---------- parsing ----------

def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        value = parsedate_to_datetime(text)
    except (TypeError, ValueError, IndexError):
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """RSS 2.0 / RSS 1.0 / Atom items as {title, link, description, published}."""
    root = ET.fromstring(xml_text.lstrip("﻿").strip().encode("utf-8"))
    items = []
    for node in root.iter():
        if _local(node.tag) not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        for child in node:
            name = _local(child.tag)
            if name == "link" and child.get("href"):
                fields.setdefault("link", child.get("href", ""))
            elif child.text:
                fields.setdefault(name, child.text.strip())
        items.append({"title": html.unescape(fields.get("title", "")).strip(),
                      "link": fields.get("link", "").strip(),
                      "description": fields.get("description") or fields.get("summary") or fields.get("content") or "",
                      "published": _date(fields.get("pubdate") or fields.get("date") or fields.get("updated")
                                         or fields.get("published"))})
    return items


def _text(markup: str) -> str:
    markup = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", markup))).strip()


def decision_sentence(source: Source, markup: str) -> str | None:
    """First sentence of the statement that names the policy rate; None when the source has no rule or no match."""
    if not source.sentence_pattern or not markup:
        return None
    match = re.search(source.sentence_pattern, _text(markup), re.I)
    return re.sub(r"^[\s、，一二三四五六七八九十]+", "", match.group(0)).strip()[:400] if match else None


def is_fresh(item: dict, now: datetime, first_pass: bool) -> bool:
    """Dated items count for FRESH_HOURS. Undated ones are claimed silently on the first pass (the baseline)."""
    published = item.get("published")
    if published is None:
        return not first_pass
    return timedelta(0) <= now - published <= timedelta(hours=FRESH_HOURS) or published > now


# ---------- BLS (CPI, jobs) ----------

def _bls_points(payload: dict) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for series in (payload.get("Results") or {}).get("series", []):
        points = {}
        for row in series.get("data", []):
            period = str(row.get("period", ""))
            if not re.fullmatch(r"M(0[1-9]|1[0-2])", period):
                continue
            try:
                points[f"{row['year']}-{period[1:]}"] = float(row["value"])
            except (KeyError, TypeError, ValueError):
                continue
        result[series.get("seriesID", "")] = points
    return result


def _shift(period: str, months: int) -> str:
    year, month = int(period[:4]), int(period[5:7])
    index = year * 12 + month - 1 - months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _pct(now: float | None, before: float | None) -> float | None:
    return None if now is None or not before else (now / before - 1) * 100


def bls_releases(payload: dict) -> dict[str, dict[str, str]]:
    """{'cpi': {period, title, body}, 'jobs': {...}} from one BLS API response; numbers only, no interpretation."""
    points = _bls_points(payload)
    releases: dict[str, dict[str, str]] = {}
    cpi, cpi_sa, core = points.get("CUUR0000SA0", {}), points.get("CUSR0000SA0", {}), points.get("CUUR0000SA0L1E", {})
    if cpi:
        period = max(cpi)
        parts = []
        yoy = _pct(cpi.get(period), cpi.get(_shift(period, 12)))
        if yoy is not None:
            prior = _pct(cpi.get(_shift(period, 1)), cpi.get(_shift(period, 13)))
            parts.append(f"CPI 年增 {yoy:.1f}%" + (f"（前值 {prior:.1f}%）" if prior is not None else ""))
        core_yoy = _pct(core.get(period), core.get(_shift(period, 12)))
        if core_yoy is not None:
            prior = _pct(core.get(_shift(period, 1)), core.get(_shift(period, 13)))
            parts.append(f"核心 CPI 年增 {core_yoy:.1f}%" + (f"（前值 {prior:.1f}%）" if prior is not None else ""))
        mom = _pct(cpi_sa.get(period), cpi_sa.get(_shift(period, 1)))
        if mom is not None:
            parts.append(f"季調後月增 {mom:.1f}%")
        if parts:
            releases["cpi"] = {"period": period, "title": f"美國 CPI（{period}）", "body": "；".join(parts)}
    jobs, unemployment = points.get("CES0000000001", {}), points.get("LNS14000000", {})
    if jobs:
        period = max(jobs)
        parts = []
        if jobs.get(_shift(period, 1)) is not None:
            parts.append(f"非農就業 {jobs[period] - jobs[_shift(period, 1)]:+,.0f} 千人")
        if unemployment.get(period) is not None:
            prior = unemployment.get(_shift(period, 1))
            parts.append(f"失業率 {unemployment[period]:.1f}%" + (f"（前值 {prior:.1f}%）" if prior is not None else ""))
        if parts:
            releases["jobs"] = {"period": period, "title": f"美國就業報告（{period}）", "body": "；".join(parts)}
    return releases


# ---------- announcing ----------

def release_key(*parts: str) -> str:
    return "macro:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def announce(store, key: str, title: str, body: str, send: Callable | None = None, history: Callable | None = None) -> bool:
    """Telegram 'news' message plus a bell copy, once per key. A failed send is released for the next poll."""
    if not store.record(key, _DAY, ""):
        return False
    if send is None:
        from . import telegram_notify
        send = telegram_notify.send
    result = send("news", title, body)
    if not result.get("sent"):
        store.release(key, _DAY)
        return False
    try:
        if history is None:
            from ..databases.market_notification_db import market_notification_db
            history = lambda t, b: market_notification_db.add("update", t, b)
        history(title, body)
    except Exception:
        logger.exception("Macro release bell copy failed")
    return True


# ---------- loop ----------

@dataclass
class MacroReleaseMonitor:
    store: Any = None
    next_poll: dict[str, datetime] = field(default_factory=dict)
    first_pass: set[str] = field(default_factory=lambda: set(SOURCES))
    bls_baseline_day: date | None = None
    bls_next: datetime | None = None
    _task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        import httpx
        if self.store is None:
            from .market_automation import automation_store
            self.store = automation_store()
        async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 (maya-sawa macro releases)"}) as client:
            while True:
                now = datetime.now(timezone.utc)
                for source in SOURCES.values():
                    if now >= self.next_poll.get(source.key, now):
                        self.next_poll[source.key] = now + timedelta(seconds=poll_seconds(now, source))
                        try:
                            await self.poll_source(client, source, now)
                        except Exception as exc:
                            logger.warning("Macro feed %s failed: %s", source.key, type(exc).__name__)
                try:
                    await self.poll_bls(client, now)
                except Exception as exc:
                    logger.warning("BLS release check failed: %s", type(exc).__name__)
                await asyncio.sleep(TICK_SECONDS)

    async def poll_source(self, client, source: Source, now: datetime) -> None:
        response = await client.get(source.url)
        response.raise_for_status()
        first = source.key in self.first_pass
        for item in parse_feed(response.text):
            if not item["title"] or not source.matches(item["title"]):
                continue
            key = release_key(source.key, item["link"] or item["title"])
            if not is_fresh(item, now, first):
                if first and item.get("published") is None:
                    await asyncio.to_thread(self.store.record, key, _DAY, "")  # baseline, never announced
                continue
            markup = item["description"]
            if source.sentence_from == "page" and source.sentence_pattern and item["link"]:
                try:
                    page = await client.get(item["link"])
                    markup = page.text
                except Exception:
                    markup = ""
            sentence = decision_sentence(source, markup)
            body = "\n".join(part for part in (sentence or item["title"], item["link"]) if part)
            await asyncio.to_thread(announce, self.store, key, source.label, body)
        self.first_pass.discard(source.key)

    async def poll_bls(self, client, now: datetime) -> None:
        today = now.astimezone(NY).date()
        baseline = _bls_baseline_time(now) and self.bls_baseline_day != today
        window = in_us_data_window(now) and self.bls_baseline_day == today
        if not (baseline or window) or (window and self.bls_next and now < self.bls_next):
            return
        self.bls_next = now + timedelta(seconds=BLS_SECONDS)
        body = {"seriesid": list(BLS_SERIES), "startyear": str(today.year - 2), "endyear": str(today.year)}
        if os.environ.get("BLS_API_KEY", "").strip():
            body["registrationkey"] = os.environ["BLS_API_KEY"].strip()
        response = await client.post(BLS_URL, json=body)
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "REQUEST_SUCCEEDED":
            logger.warning("BLS API: %s", payload.get("message"))
            return
        for name, release in bls_releases(payload).items():
            key = release_key("bls", name, release["period"])
            if baseline:
                await asyncio.to_thread(self.store.record, key, _DAY, "")  # what is already out is not news
            else:
                await asyncio.to_thread(announce, self.store, key, release["title"], release["body"])
        if baseline:
            self.bls_baseline_day = today


macro_release_monitor = MacroReleaseMonitor()
