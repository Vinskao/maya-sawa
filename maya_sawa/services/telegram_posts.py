"""Public Telegram channels recorded as library reports: one private report per post.

The public web preview (https://t.me/s/<channel>) needs no login: it lists the latest ~20 posts with their exact
UTC time, and `?before=<id>` pages back through older ones. Posts are stored as private text-only reports (no PDF,
`source_url` = the post), so the existing claim-extraction routine tags stocks in them and the claims show up as
views on the target-price timeline. Neither channel posts broker PDFs: ieobserve writes short earnings commentary,
Gooaye announces podcast episodes (and sells things).
"""
import asyncio
import hashlib
import html
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from ..databases.market_reports_db import COLLECTOR_LISTED_PER_CHANNEL, COLLECTOR_UPLOADER
from .web_articles import fetch_article

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
CHANNELS = ["ieobserve", "Gooaye", "technews_tw", "bloomberg"]
# Per channel: follow_links (store the full text of the articles a digest links to as reports of their own) and max_age_days
# (how far back to read; the first run of a busy news channel must not pull years of posts into the extraction queue).
CHANNEL_SETTINGS = {"technews_tw": {"follow_links": True, "max_age_days": 30}, "bloomberg": {"max_age_days": 60}}
MAX_PAGES = 500  # per direction; a channel of a few thousand posts is under 400 pages
PAGE_DELAY = 1.0
RECENT_DAYS = 14  # newer posts are queued for claim extraction at once, older ones wait in the backlog
BACKLOG_PER_DAY = 30  # backlog posts released to the claim-extraction routine each day
MIN_TEXT = 15  # a caption of a few words ("photo of a chart") is not worth a report
USER_AGENT = "Mozilla/5.0 (compatible; maya-sawa-telegram-reader)"
MEDIA = ("photo", "video", "document", "voice", "link_preview")


def _plain(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def parse_channel_html(page: str, channel: str) -> dict:
    """Posts of one preview page (oldest first as shown), the channel's display name and the cursor for older posts."""
    posts, title = [], channel
    for block in re.split(r'(?=<div class="tgme_widget_message_wrap)', page)[1:]:
        post_id = re.search(r'data-post="[^/"]+/(\d+)"', block)
        stamp = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        if not post_id or not stamp:
            continue
        owner = re.search(r'tgme_widget_message_owner_name"[^>]*><span[^>]*>([^<]*)</span>', block)
        title = html.unescape(owner.group(1)) if owner else title
        text_div = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, flags=re.S)
        links = re.findall(r'<a class="tgme_widget_message_link_preview" href="([^"]+)"', block)
        if text_div:
            links += [url for url in re.findall(r'<a href="(https?://[^"]+)"', text_div.group(1)) if url not in links]
        posts.append({
            "id": int(post_id.group(1)), "channel": channel,
            "posted_at": datetime.fromisoformat(stamp.group(1)),
            "text": _plain(text_div.group(1)) if text_div else "",
            "media": [kind for kind in MEDIA if f"tgme_widget_message_{kind}" in block],
            "links": links, "url": f"https://t.me/{channel}/{post_id.group(1)}",
        })
    cursor = re.search(r'data-before="(\d+)"', page)
    return {"title": title, "before": int(cursor.group(1)) if cursor else None, "posts": posts}


def worth_recording(post: dict) -> bool:
    return len(post.get("text", "").strip()) >= MIN_TEXT


def _record_articles(db, post: dict, *, channel_title: str, enrich, recent: bool) -> int:
    """Each readable article a digest links to becomes a report: title, date, full text and a link to the original."""
    stored, seen = 0, set()
    for link in post.get("links", []):
        if not link.startswith(("http://", "https://")) or link in seen:
            continue
        seen.add(link)
        try:
            article = enrich(link)
        except Exception as exc:  # one unreadable link must not lose the others
            logger.warning("Article %s unreadable: %s", link, type(exc).__name__)
            continue
        if not article:
            continue
        day = article.get("published_at") or post["posted_at"].astimezone(TAIPEI).date()
        body = f"來源：{article['url']}\n發布：{day.isoformat()}\n頻道貼文：{post['url']}\n\n{article['text']}"
        db.save_extracted(
            title=article["title"], publisher=channel_title, published_at=day, visibility="public", uploaded_by=COLLECTOR_UPLOADER,
            digest=hashlib.sha256(f"article:{article['url']}".encode()).hexdigest(), pdf=b"", pages=[body], source_url=article["url"],
            status="claims_pending" if recent else "backlog")
        stored += 1
    return stored


def record_posts(db, posts: list[dict], *, channel_title: str, now: datetime | None = None, enrich=None) -> dict:
    """Store each post once (keyed by channel and post id); posts without real text are skipped. Recent posts go straight
    to the claim-extraction queue, older ones wait in a backlog that is released in daily batches. With `enrich`, the
    articles a post links to are stored as reports too; a digest whose articles were stored is kept only as an index
    (status "digest": not listed, not extracted), so its headlines are not extracted twice."""
    now = now or datetime.now(timezone.utc)
    new = known = 0
    for post in posts:
        if not worth_recording(post):
            continue
        first_line = post["text"].strip().splitlines()[0][:60]
        body = f"來源：{post['url']}\n發布：{post['posted_at'].isoformat()}\n\n{post['text']}"
        digest = hashlib.sha256(f"telegram:{post['channel']}:{post['id']}".encode()).hexdigest()
        recent = now - post["posted_at"] <= timedelta(days=RECENT_DAYS)
        status = "claims_pending" if recent else "backlog"
        if enrich:
            existing = db.find_by_digest(digest)
            if existing:
                known += 1
                # Collected before link-following existed (or its links were unreadable): read the articles now, once they are in range.
                if existing["status"] in ("claims_pending", "backlog") and recent and _record_articles(
                        db, post, channel_title=channel_title, enrich=enrich, recent=True):
                    db.set_status_by_digest(digest, "digest")
                continue
            if _record_articles(db, post, channel_title=channel_title, enrich=enrich, recent=recent):
                status = "digest"
        _, duplicate = db.save_extracted(
            title=f"[{channel_title}] {first_line}", publisher=channel_title,
            published_at=post["posted_at"].astimezone(TAIPEI).date(), visibility="public",
            uploaded_by=COLLECTOR_UPLOADER, digest=digest, pdf=b"", pages=[body], source_url=post["url"], status=status)
        known, new = (known + 1, new) if duplicate else (known, new + 1)
    return {"new": new, "known": known}


def fetch_page(channel: str, before: int | None = None) -> dict:
    url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")
    response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
    response.raise_for_status()
    time.sleep(PAGE_DELAY)  # one request a second while walking the history
    return parse_channel_html(response.text, channel)


def collect(db, channels: list[str], fetch, max_pages: int = MAX_PAGES, now: datetime | None = None,
            settings: dict | None = None, enrich=None) -> dict:
    """Newest side: read pages from the newest until one already holds recorded posts (the first run therefore reads the
    whole history, a daily run one page). Older side: resume below the oldest recorded post, which completes a history walk
    that was cut short. A failing channel is reported, not fatal."""
    results = {}
    now = now or datetime.now(timezone.utc)
    settings = CHANNEL_SETTINGS if settings is None else settings
    for channel in channels:
        total = {"new": 0, "known": 0}
        config = settings.get(channel, {})
        cutoff = now - timedelta(days=config["max_age_days"]) if config.get("max_age_days") else None
        follow = enrich if config.get("follow_links") else None

        def read(before):
            page = fetch(channel, before)
            posts = [post for post in page["posts"] if cutoff is None or post["posted_at"] >= cutoff]
            counts = record_posts(db, posts, channel_title=page["title"], now=now, enrich=follow)
            for key in total:
                total[key] += counts[key]
            too_old = cutoff is not None and any(post["posted_at"] < cutoff for post in page["posts"])
            return page, counts, too_old

        try:
            if cutoff is not None:
                db.archive_backlog_before(channel, cutoff.astimezone(TAIPEI).date())
            before = None
            for _ in range(max_pages):
                page, counts, too_old = read(before)
                before = page["before"]
                if counts["known"] or not before or too_old:
                    break
            oldest = db.oldest_post_id(channel)
            before = oldest
            for _ in range(max_pages if oldest else 0):
                page, _counts, too_old = read(before)
                before = page["before"]
                if not before or not page["posts"] or too_old:
                    break
            results[channel] = total
        except Exception as exc:
            logger.warning("Telegram channel %s unavailable: %s", channel, type(exc).__name__)
            results[channel] = "error"
    return results


class TelegramPostCollector:
    """Reads the channels once a day; the first pass runs 2 minutes after start (and walks the whole history)."""

    def __init__(self):
        self._task: asyncio.Task | None = None

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def close(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def collect_now(self) -> dict:
        from ..databases.market_reports_db import market_reports_db
        if not market_reports_db.sessions:
            return {}
        await asyncio.to_thread(market_reports_db.make_collector_posts_public)  # repairs rows from the first (owner-only) version
        counts = await asyncio.to_thread(collect, market_reports_db, CHANNELS, fetch_page, enrich=fetch_article)
        # The report list shows each channel's latest posts, so those are extracted first; the rest drain daily.
        counts["released"] = (await asyncio.to_thread(market_reports_db.promote_latest_per_channel, COLLECTOR_LISTED_PER_CHANNEL)
                              + await asyncio.to_thread(market_reports_db.promote_backlog, BACKLOG_PER_DAY))
        return counts

    async def _loop(self):
        await asyncio.sleep(120)
        while True:
            try:
                logger.info("Telegram posts: %s", await self.collect_now())
            except Exception:
                logger.exception("Telegram post collection failed")
            await asyncio.sleep(86400)


telegram_post_collector = TelegramPostCollector()
