"""Public Telegram channels (t.me/s/<channel>) recorded as library reports, one per post, with the source named."""
from datetime import date, datetime, timedelta, timezone
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


def test_each_post_becomes_one_report_naming_its_source(db):
    posts = tg.parse_channel_html(page("telegram_ieobserve.html"), "ieobserve")["posts"]
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    assert tg.record_posts(db, posts, channel_title="IEObserve 國際經濟觀察", now=now) == {"new": 3, "known": 0}
    assert len(db.list_reports(owner=None)) == 3  # public and listed (capped per channel, see the list test below)
    pending = db.pending_claims()  # the claim-extraction routine reads this queue
    assert len(pending) == 3
    micron = next(row for row in pending if "美光" in row["title"])
    assert micron["title"].startswith("[IEObserve 國際經濟觀察] 美光 Micron 再度交出超預期的財報")
    assert micron["publisher"] == "IEObserve 國際經濟觀察"
    assert micron["published_at"] == "2026-10-01"  # post time 00:11 UTC is 08:11 in Taipei
    assert micron["page_count"] == 1
    assert "來源：https://t.me/ieobserve/2312" in micron["text"] and "EPS $33.42" in micron["text"]
    full = db.get_report(micron["id"])[0]
    assert full["visibility"] == "public" and full["received_at"] and full["source_url"] == "https://t.me/ieobserve/2312"
    assert tg.record_posts(db, posts, channel_title="IEObserve 國際經濟觀察", now=now) == {"new": 0, "known": 3}  # re-reading adds nothing
    # Once the routine has extracted a claim, it is public with the channel and the post named as its source.
    db.replace_claims(micron["id"], [{"page": 1, "segment": "memory", "codes": ["MU-US"], "dimension": "cycle", "direction": "tailwind",
                                      "claim": "美光預期 2027、2028 年 DRAM 與 NAND 供需都比 2026 年更緊", "evidence": "營收年增 379%、毛利率 87%", "as_of": "2026-10-01"}], "routine")
    claims = db.list_claims()  # (the code filter uses a Postgres array operator, which SQLite lacks)
    assert [(c["publisher"], c["source_url"], c["published_at"]) for c in claims] == [("IEObserve 國際經濟觀察", "https://t.me/ieobserve/2312", "2026-10-01")]


def test_old_posts_wait_in_a_backlog_and_are_released_newest_first_in_daily_batches(db):
    posts = tg.parse_channel_html(page("telegram_ieobserve.html"), "ieobserve")["posts"]
    tg.record_posts(db, posts, channel_title="IEObserve", now=datetime(2026, 10, 16, tzinfo=timezone.utc))
    assert [row["published_at"] for row in db.pending_claims()] == ["2026-10-03"]  # only the post of the last 14 days is queued now
    assert db.promote_backlog(limit=1) == 1
    assert sorted(row["published_at"] for row in db.pending_claims()) == ["2026-10-01", "2026-10-03"]  # newest backlog post first
    assert db.promote_backlog(limit=10) == 1 and db.promote_backlog(limit=10) == 0


class FakeChannel:
    """A channel of three pages (ids 21-23, 11-13, 1-2) as t.me/s serves them: `?before=N` shows posts older than N."""

    def __init__(self):
        self.asked, self.fail_at = [], -1  # -1: never fails
        self.pages = {None: {"before": 20, "posts": [post(i) for i in (21, 22, 23)]},
                      20: {"before": 10, "posts": [post(i) for i in (11, 12, 13)]},
                      10: {"before": None, "posts": [post(i) for i in (1, 2)]}}
        self.pages[11] = self.pages[10]  # before=11 and before=10 both show ids 1-10 (there are no posts 3-10)

    def __call__(self, channel, before=None):
        self.asked.append(before)
        if before == self.fail_at:
            raise TimeoutError("t.me slow")
        return {"title": "Chan", **self.pages.get(before, {"before": None, "posts": []})}


def test_first_run_reads_the_whole_history_and_later_runs_read_one_page(db):
    fetch, now = FakeChannel(), datetime(2026, 10, 21, tzinfo=timezone.utc)
    assert tg.collect(db, ["chan"], fetch, now=now) == {"chan": {"new": 8, "known": 0}}
    assert fetch.asked == [None, 20, 10, 1]  # newest to oldest, then one look below the oldest recorded post
    fetch.asked.clear()
    fetch.pages[None] = {"before": 20, "posts": [post(i) for i in (21, 22, 23, 24)]}  # one new post since
    assert tg.collect(db, ["chan"], fetch, now=now) == {"chan": {"new": 1, "known": 3}}
    assert fetch.asked == [None, 1]  # stops at the first page that already holds recorded posts


def test_a_run_cut_short_resumes_below_the_oldest_recorded_post(db):
    fetch, now = FakeChannel(), datetime(2026, 10, 21, tzinfo=timezone.utc)
    fetch.fail_at = 10
    assert tg.collect(db, ["chan"], fetch, now=now) == {"chan": "error"}  # ids 11-13 and 21-23 are stored, 1-2 are not
    fetch.fail_at, fetch.asked = -1, []
    assert tg.collect(db, ["chan"], fetch, now=now) == {"chan": {"new": 2, "known": 3}}
    assert fetch.asked == [None, 11]  # newest page is all known, so it goes straight to the missing older posts


def post(post_id):
    return {"id": post_id, "channel": "chan", "posted_at": datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc),
            "text": f"第 {post_id} 則：台積電法說會提到先進製程需求，毛利率維持高檔。", "media": [], "links": [],
            "url": f"https://t.me/chan/{post_id}"}


def test_the_report_list_shows_the_latest_ten_posts_of_every_channel_whatever_their_status(db):
    """2026-10-27: the owner expected both channels in the report list, so a channel whose posts yielded no claims yet
    (or are still queued) must not vanish. Only the latest ten per channel are listed, so 200 backlog posts do not
    bury the PDF reports; older ones stay as data."""
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)  # every post is recent, so all go to the extraction queue
    claim = {"page": 1, "segment": "memory", "codes": ["MU-US"], "dimension": "cycle", "direction": "tailwind",
             "claim": "DRAM 供需偏緊", "evidence": "營收年增", "as_of": "2026-10-01"}
    for channel, title in [("Gooaye", "股癌"), ("ieobserve", "IEObserve")]:
        posts = [{"channel": channel, "id": number, "url": f"https://t.me/{channel}/{number}", "text": f"第 {number} 則：" + "內容" * 40,
                  "posted_at": datetime(2026, 9, 1, tzinfo=timezone.utc) + timedelta(days=number)} for number in range(1, 13)]
        tg.record_posts(db, posts, channel_title=title, now=now)
    for row in db.pending_claims():
        if row["publisher"] == "股癌" and "第 6 則" not in row["title"]:  # IEObserve is not extracted yet
            db.replace_claims(row["id"], [claim], "routine")
    listed = db.list_reports(owner=None)
    assert len(listed) == 20
    for title in ("股癌", "IEObserve"):
        mine = [row for row in listed if row["publisher"] == title]
        assert [row["title"].split("] ")[1].split("：")[0] for row in mine] == [f"第 {n} 則" for n in range(12, 2, -1)]
        assert all(row["source_url"].startswith("https://t.me/") for row in mine)
    assert {row["status"] for row in listed if row["publisher"] == "IEObserve"} == {"claims_pending"}
    assert [row["claim_count"] for row in listed if row["publisher"] == "股癌"][:4] == [1, 1, 1, 1]
    assert next(row for row in listed if row["title"].startswith("[股癌] 第 6 則"))["claim_count"] == 0


def test_the_latest_ten_posts_of_every_channel_are_released_to_extraction_even_when_another_channel_is_newer(db):
    """2026-10-28: the list shows each channel's latest ten posts, but the daily backlog release is newest-first across
    all channels, so a channel with older posts (IEObserve) sat at "0 claims" for weeks behind a busier one."""
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    for channel, title, start in [("Gooaye", "股癌", datetime(2026, 9, 1, tzinfo=timezone.utc)), ("ieobserve", "IEObserve", datetime(2026, 2, 1, tzinfo=timezone.utc))]:
        posts = [{"channel": channel, "id": number, "url": f"https://t.me/{channel}/{number}", "text": f"第 {number} 則：" + "內容" * 40,
                  "posted_at": start + timedelta(days=number)} for number in range(1, 16)]
        tg.record_posts(db, posts, channel_title=title, now=now)
    assert db.pending_claims() == []                                       # all 30 are older than 14 days: backlog
    assert db.promote_latest_per_channel(10) == 20
    queued = db.pending_claims()
    for title in ("股癌", "IEObserve"):
        mine = sorted(int(row["title"].split("第 ")[1].split(" 則")[0]) for row in queued if row["publisher"] == title)
        assert mine == list(range(6, 16))                                  # the newest ten, not the oldest
    assert db.promote_latest_per_channel(10) == 0                          # nothing left to release for the list
