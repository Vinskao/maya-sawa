"""Full text of the news articles a Telegram digest links to (TechNews posts are lists of headlines, each with a short link).

Only the sites a channel is known to link to are fetched, one request a second, with the collector's own User-Agent (it does
not pretend to be a browser). The owner chose to store these articles for personal, non-commercial research; the site shows
claims and a link to the original, not the text.
"""
import html
import re
import time
from datetime import date
from urllib.parse import urlsplit

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; maya-sawa-telegram-reader)"
ARTICLE_HOSTS = ("technews.tw",)   # the sites an article may live on (subdomains included)
SHORTENER_HOSTS = ("pse.is",)      # short links that redirect to them
MIN_TEXT = 100                     # a page with less story text than this is not an article
MAX_TEXT = 20000
NOISE = ("googletag", "${", "鼓勵", "咖啡贊助", "延伸閱讀", "推薦閱讀")


def _host_is(url: str, hosts) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme in ("http", "https") and any(host == name or host.endswith("." + name) for name in hosts)


def allowed(url: str) -> bool:
    """Where an article may live."""
    return _host_is(url, ARTICLE_HOSTS)


def allowed_start(url: str) -> bool:
    return allowed(url) or _host_is(url, SHORTENER_HOSTS)


def _plain(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", fragment, flags=re.S | re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def extract_article(page: str, final_url: str) -> dict | None:
    title = re.search(r'<meta property="og:title" content="([^"]*)"', page) or re.search(r'<h1[^>]*entry-title[^>]*>(.*?)</h1>', page, flags=re.S)
    parts = urlsplit(final_url)
    clean_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    when = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", parts.path)
    start = page.find('<div class="indent">')
    if start < 0:
        start = page.find("<article")
    if not title or start < 0:
        return None
    end = page.find("</article>", start)
    region = page[start:end if end > start else len(page)]
    paragraphs = []
    for fragment in re.findall(r"<p[^>]*>(.*?)</p>", region, flags=re.S):
        text = _plain(fragment)
        if text.startswith(("(首圖來源", "（首圖來源")):
            break  # everything after the lead-image credit is sharing and donation boilerplate
        if len(text) >= 15 and not any(marker in text for marker in NOISE):
            paragraphs.append(text)
    body = "\n\n".join(paragraphs)[:MAX_TEXT]
    if len(body) < MIN_TEXT:
        return None
    return {"title": html.unescape(_plain(title.group(1))), "url": clean_url, "text": body,
            "published_at": date(int(when.group(1)), int(when.group(2)), int(when.group(3))) if when else None}


def fetch_article(url: str, client=None, delay: float = 1.0) -> dict | None:
    """Follow a (short) link and return the article, or None when it is not an allowed, readable article."""
    if not allowed_start(url):
        return None
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
    try:
        response = client.get(url, follow_redirects=True)
        response.raise_for_status()
        final = str(response.url)
        return extract_article(response.text, final) if allowed(final) else None
    finally:
        if own:
            client.close()
        if delay:
            time.sleep(delay)
