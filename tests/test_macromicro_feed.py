"""MacroMicro (財經M平方) market commentary from its public RSS feed, recorded as library reports.

Why the feed and not https://www.macromicro.me/quickie: the site pages sit behind a Cloudflare bot challenge (HTTP 403,
`cf-mitigated: challenge`, checked 2026-11-02) which the collector must not try to get around. https://www.macromicro.me/feed
is an open RSS feed (robots.txt does not disallow it) whose items carry a 600-2200 character excerpt each.
The fixture is a trimmed real response: three items, the real header, a real `&amp;amp;` double escape.
"""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.market_reports_db import COLLECTOR_UPLOADER, MarketReportsDatabase
from maya_sawa.services import macromicro_feed as mm

FEED = (Path(__file__).parent / "fixtures" / "macromicro_feed.xml").read_text(encoding="utf-8")
NOW = datetime(2026, 11, 2, 15, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    return MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'r.db'}"))


def item(title="【行情快報】測試標題", link="https://www.macromicro.me/blog/x", guid="post-1", pub="Sun, 01 Nov 2026 20:09:49 +0800",
         text="台積電上修全年營收成長至 44%，存貨週轉改善。" * 8, category="行情快報"):
    stamp = f"<pubDate>{pub}</pubDate>" if pub else ""
    return (f"<rss><channel><title>MacroMicro</title><item><title><![CDATA[{title}]]></title>"
            f"<description><![CDATA[ {text} ]]></description><link>{link}</link><guid>{guid}</guid>"
            f"<category><![CDATA[{category}]]></category>{stamp}</item></channel></rss>")


def test_parses_title_link_guid_category_and_the_taipei_publication_time():
    feed = mm.parse_feed(FEED)
    assert feed["title"] == "MacroMicro 財經M平方"
    assert len(feed["items"]) == 3
    first = feed["items"][0]
    assert first["title"].startswith("【MM一週盤前】")
    assert first["url"].startswith("https://www.macromicro.me/blog/")
    assert first["guid"] == "post-1592" and first["category"] == "一週盤前"
    assert first["published_at"] == datetime(2026, 11, 1, 12, 9, 49, tzinfo=timezone.utc)   # 20:09 +0800
    assert first["published_at"].astimezone(mm.TAIPEI).date() == date(2026, 11, 1)


def test_the_excerpt_is_plain_text_without_double_escaped_entities_or_blank_runs():
    text = mm.parse_feed(FEED)["items"][0]["text"]
    assert "美國 & 台灣製造業 PMI" in text and "&amp;" not in text and "<" not in text
    assert "\n\n\n" not in text and text == text.strip()


def test_unreadable_or_incomplete_feeds_give_no_items_instead_of_raising():
    assert mm.parse_feed("<html><title>Just a moment...</title></html>")["items"] == []   # the Cloudflare challenge page
    assert mm.parse_feed("")["items"] == []
    assert mm.parse_feed(item(pub=None))["items"] == []                                  # no date: cannot place it in time
    assert mm.parse_feed(item(link=""))["items"] == []                                   # no link: no source to name
    assert mm.parse_feed(item(pub="not a date"))["items"] == []


def test_each_item_becomes_one_public_report_naming_its_source_and_queued_for_extraction(db):
    counts = mm.record_items(db, mm.parse_feed(FEED)["items"], now=NOW)
    assert counts == {"new": 3, "known": 0, "skipped": 0}
    reports = db.list_reports(None)
    assert len(reports) == 3
    one = next(r for r in reports if r["title"].startswith("【MM一週盤前】"))
    assert one["publisher"] == mm.PUBLISHER == "MacroMicro 財經M平方"
    assert one["visibility"] == "public" and one["published_at"] == "2026-11-01"
    assert one["source_url"].startswith("https://www.macromicro.me/blog/")
    assert {r["status"] for r in reports} == {"claims_pending"}                          # the routine reads these at 20:30
    pending = db.pending_claims()
    assert len(pending) == 3 and all("來源：https://www.macromicro.me/blog/" in r["text"] for r in pending)
    assert all(r["uploaded_by"] == COLLECTOR_UPLOADER for r in [db.find_by_digest(mm.digest_for(i)) for i in mm.parse_feed(FEED)["items"]])


def test_a_second_run_stores_nothing_twice(db):
    items = mm.parse_feed(FEED)["items"]
    mm.record_items(db, items, now=NOW)
    assert mm.record_items(db, items, now=NOW) == {"new": 0, "known": 3, "skipped": 0}
    assert len(db.list_reports(None)) == 3


def test_a_stub_without_real_text_is_skipped_and_old_items_wait_in_the_backlog(db):
    stub = mm.parse_feed(item(text="短文", guid="post-2"))["items"]
    assert mm.record_items(db, stub, now=NOW) == {"new": 0, "known": 0, "skipped": 1}
    old = mm.parse_feed(item(guid="post-3", pub="Mon, 01 Jun 2026 10:00:00 +0800"))["items"]
    assert mm.record_items(db, old, now=NOW)["new"] == 1
    assert db.find_by_digest(mm.digest_for(old[0]))["status"] == "backlog"


def test_collect_reads_the_feed_once_and_a_failing_fetch_is_reported_not_raised(db):
    assert mm.collect(db, lambda: FEED, now=NOW) == {"new": 3, "known": 0, "skipped": 0}

    def blocked():
        raise RuntimeError("403")
    assert mm.collect(db, blocked, now=NOW) == "error"
    assert mm.collect(db, lambda: "<html>Just a moment...</html>", now=NOW) == "unreadable"   # a challenge page is not a feed


def test_the_feed_address_and_client_identity_are_the_documented_ones():
    assert mm.FEED_URL == "https://www.macromicro.me/feed"
    assert "maya-sawa" in mm.USER_AGENT and "mozilla" not in mm.USER_AGENT.lower()   # says who it is; no browser disguise


def test_the_telegram_collector_run_also_reads_macromicro(db, monkeypatch):
    """One daily collection pass covers every report source, so the daily extraction routine needs no change."""
    import asyncio

    from maya_sawa.databases import market_reports_db as module
    from maya_sawa.services import telegram_posts as tg

    monkeypatch.setattr(module, "market_reports_db", db)
    monkeypatch.setattr(tg, "collect", lambda *a, **k: {})
    monkeypatch.setattr(mm, "fetch_feed", lambda: FEED)
    counts = asyncio.run(tg.TelegramPostCollector().collect_now())
    assert counts["macromicro"] == {"new": 3, "known": 0, "skipped": 0}
    assert len(db.list_reports(None)) == 3
