"""MacroMicro (財經M平方) market commentary recorded as library reports, from its public RSS feed.

Not https://www.macromicro.me/quickie: the site's pages are behind a Cloudflare bot challenge (HTTP 403,
`cf-mitigated: challenge`), which this collector must not try to get around. https://www.macromicro.me/feed is an open RSS
feed (robots.txt does not disallow it) with the latest ten posts (行情快報, MM 一週盤前, 創辦人撰文) and a 600-2200 character
excerpt of each. Every item becomes one public report that names its source and links to the original; the daily
claim-extraction routine tags stocks and macro views in it, and the site shows only the claims and the link.
"""
import hashlib
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

from ..databases.market_reports_db import COLLECTOR_UPLOADER

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
FEED_URL = "https://www.macromicro.me/feed"
PUBLISHER = "MacroMicro 財經M平方"
USER_AGENT = "maya-sawa-macromicro-reader (+https://tymultiverse.cc)"  # says who it is; no browser disguise
MIN_TEXT = 100  # an excerpt shorter than this has nothing to extract
RECENT_DAYS = 14  # newer items go straight to claim extraction, older ones wait in the backlog


def _plain(fragment: str) -> str:
    """Excerpts arrive HTML-escaped, some twice (`&amp;amp;`); return readable text with single blank lines."""
    text = fragment
    for _ in range(3):  # unescape until stable: a double escape is the feed's quirk, not the author's text
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    lines = [line.strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def parse_feed(xml_text: str) -> dict:
    """Items with a title, link, date and text; anything unreadable (a challenge page, an undated item) is left out."""
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return {"title": "", "items": []}
    channel = root.find("channel")
    if channel is None:
        return {"title": "", "items": []}
    items = []
    for node in channel.findall("item"):
        text = lambda tag: (node.findtext(tag) or "").strip()
        link, stamp = text("link"), text("pubDate")
        try:
            published = parsedate_to_datetime(stamp).astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        if not link.startswith(("https://", "http://")):
            continue
        items.append({"title": _plain(text("title")), "url": link, "guid": text("guid") or link, "category": text("category"),
                      "published_at": published, "text": _plain(text("description"))})
    return {"title": _plain((channel.findtext("title") or "")), "items": items}


def digest_for(item: dict) -> str:
    return hashlib.sha256(f"macromicro:{item['guid']}".encode()).hexdigest()


def record_items(db, items: list[dict], *, now: datetime | None = None) -> dict:
    """Store each item once (keyed by the feed's guid). Recent items are queued for claim extraction at once."""
    now = now or datetime.now(timezone.utc)
    new = known = skipped = 0
    for item in items:
        if len(item["text"]) < MIN_TEXT:
            skipped += 1
            continue
        recent = now - item["published_at"] <= timedelta(days=RECENT_DAYS)
        day = item["published_at"].astimezone(TAIPEI).date()
        body = f"來源：{item['url']}\n發布：{item['published_at'].isoformat()}\n分類：{item['category']}\n\n{item['text']}"
        _, duplicate = db.save_extracted(
            title=item["title"], publisher=PUBLISHER, published_at=day, visibility="public", uploaded_by=COLLECTOR_UPLOADER,
            digest=digest_for(item), pdf=b"", pages=[body], source_url=item["url"],
            status="claims_pending" if recent else "backlog")
        known, new = (known + 1, new) if duplicate else (known, new + 1)
    return {"new": new, "known": known, "skipped": skipped}


def fetch_feed() -> str:
    response = httpx.get(FEED_URL, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=False)
    response.raise_for_status()  # a Cloudflare challenge is a 403: reported, never worked around
    return response.text


def collect(db, fetch=fetch_feed, now: datetime | None = None):
    """One pass over the feed. Returns the counts, 'unreadable' for a response that is not a feed, or 'error'."""
    try:
        body = fetch()
    except Exception as exc:  # the collector must not fail the daily run because one source is down or blocking
        logger.warning("MacroMicro feed unavailable: %s", type(exc).__name__)
        return "error"
    feed = parse_feed(body)
    if not feed["items"]:
        logger.warning("MacroMicro feed had no readable items")
        return "unreadable"
    return record_items(db, feed["items"], now=now)
