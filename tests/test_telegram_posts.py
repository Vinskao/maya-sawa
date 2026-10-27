"""Public Telegram channels (t.me/s/<channel>) recorded as private library reports, one per post."""
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.market_reports_db import MarketReportsDatabase
from maya_sawa.services import telegram_posts as tg


def page(name):
    return (Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8")


def test_parses_post_ids_utc_time_text_media_and_links():
    parsed = tg.parse_channel_html(page("telegram_ieobserve.html"), "ieobserve")
    assert [post["id"] for post in parsed["posts"]] == [2311, 2312, 2313]
    assert parsed["before"] == 2311  # the cursor for the next, older page
    assert parsed["title"] == "IEObserve 國際經濟觀察"
    link_post, photo_post = parsed["posts"][0], parsed["posts"][1]
    assert link_post["media"] == ["link_preview"]
    assert "https://patreon.com/ieo/posts/170882837" in link_post["links"]
    assert photo_post["posted_at"] == datetime(2026, 10, 1, 0, 11, 31, tzinfo=timezone.utc)
    assert photo_post["url"] == "https://t.me/ieobserve/2312"
    assert photo_post["media"] == ["photo"]
    assert photo_post["text"].startswith("美光 Micron 再度交出超預期的財報，本季營收年增379%至542億")
    assert "EPS $33.42" in photo_post["text"] and "$MU 現在預期" in photo_post["text"]  # &#036; is "$"
    assert "\n\n" in photo_post["text"] and "<br" not in photo_post["text"]
    assert "#下一季展望更強。美光預估Q4" in photo_post["text"]  # hashtag links keep their text


def test_posts_without_text_parse_but_are_not_worth_recording():
    parsed = tg.parse_channel_html(page("telegram_gooaye.html"), "Gooaye")
    assert [post["id"] for post in parsed["posts"]] == [6505, 6506]
    assert parsed["posts"][1]["text"] == "" and parsed["posts"][1]["media"] == ["photo"]
    assert tg.worth_recording(parsed["posts"][0]) and not tg.worth_recording(parsed["posts"][1])


@pytest.fixture
def db(tmp_path):
    return MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'reports.db'}"))


def test_each_post_becomes_one_private_report_dated_by_the_post_and_the_recording(db):
    posts = tg.parse_channel_html(page("telegram_ieobserve.html"), "ieobserve")["posts"]
    result = tg.record_posts(db, posts, channel_title="IEObserve 國際經濟觀察")
    assert result == {"new": 3, "known": 0}
    reports = db.list_reports(owner=None)
    assert reports == []  # private: not in the public list
    pending = db.pending_claims()  # the claim-extraction routine reads this queue
    assert len(pending) == 3
    micron = next(row for row in pending if "美光" in row["title"])
    assert micron["title"].startswith("[IEObserve 國際經濟觀察] 美光 Micron 再度交出超預期的財報")
    assert micron["publisher"] == "IEObserve 國際經濟觀察"
    assert micron["published_at"] == "2026-10-01"  # post time 00:11 UTC is 08:11 in Taipei
    assert micron["page_count"] == 1
    assert "來源：https://t.me/ieobserve/2312" in micron["text"] and "EPS $33.42" in micron["text"]
    full = db.get_report(micron["id"])[0]
    assert full["visibility"] == "private" and full["received_at"] and full["source_url"] == "https://t.me/ieobserve/2312"
    assert tg.record_posts(db, posts, channel_title="IEObserve 國際經濟觀察") == {"new": 0, "known": 3}  # re-reading adds nothing


def test_first_run_walks_back_through_older_pages_and_later_runs_stop_at_known_posts(db):
    pages = {None: {"before": 20, "posts": [post(i) for i in (21, 22, 23)]},
             20: {"before": 10, "posts": [post(i) for i in (11, 12, 13)]},
             10: {"before": None, "posts": [post(i) for i in (1, 2)]}}
    asked = []

    def fetch(channel, before=None):
        asked.append(before)
        return {"title": "Chan", **pages[before]}

    first = tg.collect(db, ["chan"], fetch, max_pages=5)
    assert first == {"chan": {"new": 8, "known": 0}} and asked == [None, 20, 10]
    asked.clear()
    pages[None] = {"before": 20, "posts": [post(i) for i in (21, 22, 23, 24)]}  # one new post since
    again = tg.collect(db, ["chan"], fetch, max_pages=5)
    assert again == {"chan": {"new": 1, "known": 3}} and asked == [None]  # stops: the page already had known posts
    asked.clear()
    assert tg.collect(db, ["chan"], lambda c, before=None: (_ for _ in ()).throw(TimeoutError("t.me slow")), max_pages=5) == {"chan": "error"}


def post(post_id):
    return {"id": post_id, "channel": "chan", "posted_at": datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
            "text": f"第 {post_id} 則：台積電法說會提到先進製程需求，毛利率維持高檔。" , "media": [], "links": [],
            "url": f"https://t.me/chan/{post_id}"}
