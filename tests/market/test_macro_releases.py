import json
from datetime import datetime, timezone
from pathlib import Path

from maya_sawa.services import macro_releases as mr

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "macro"
UTC = timezone.utc

FED_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>FRB</title>
<item><title>Minutes of the Federal Open Market Committee, October 27-28, 2026</title>
<link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261118a.htm]]></link>
<pubDate>Wed, 18 Nov 2026 19:00:00 GMT</pubDate></item>
<item><title>Federal Reserve issues FOMC statement</title>
<link><![CDATA[https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm]]></link>
<pubDate>Wed, 28 Oct 2026 18:00:00 GMT</pubDate></item>
</channel></rss>"""

FED_PAGE = """<html><body><div id="article"><p>Recent indicators suggest that economic activity has been expanding.</p>
<p>The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent, in support of
the Federal Reserve's dual mandate. The Committee is continuing its policy of maintaining ample reserves.</p>
<p>Voting against the monetary policy action were Lisa D. Cook and Beth M. Hammack, who preferred to raise the target
range for the federal funds rate by 1/4 percentage point at this meeting.</p></div></body></html>"""

CBC_RSS = """<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>新聞稿</title>
<item><title><![CDATA[第21屆理事會第7次理監事聯席會議貨幣政策議事錄摘要]]></title>
<link>https://www.cbc.gov.tw/tw/cp-302-1.html</link><pubDate>Thu, 26 Nov 2026 08:00:00 GMT</pubDate></item>
<item><title><![CDATA[中央銀行理監事聯席會議決議]]></title><link>https://www.cbc.gov.tw/tw/cp-302-2.html</link>
<description><![CDATA[<p>一、國際經濟金融情勢。</p><p>本行重貼現率、擔保放款融通利率及短期融通利率分別維持年息2%、2.375%及4.25%不變。</p>]]></description>
<pubDate>Thu, 17 Dec 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_feed_reads_title_link_and_date():
    items = mr.parse_feed(FED_RSS)
    assert items[1]["title"] == "Federal Reserve issues FOMC statement"
    assert items[1]["link"].endswith("monetary20261028a.htm")
    assert items[1]["published"] == datetime(2026, 10, 28, 18, 0, tzinfo=UTC)


def test_only_decision_releases_match_not_minutes_or_speeches():
    fed = mr.SOURCES["fed"]
    assert [i["title"] for i in mr.parse_feed(FED_RSS) if fed.matches(i["title"])] == ["Federal Reserve issues FOMC statement"]
    cbc = mr.SOURCES["cbc"]
    assert [i["title"] for i in mr.parse_feed(CBC_RSS) if cbc.matches(i["title"])] == ["中央銀行理監事聯席會議決議"]
    assert mr.SOURCES["boe"].matches("Bank Rate maintained at 4% - November 2026")
    assert mr.SOURCES["ecb"].matches("Monetary policy decisions")
    assert not mr.SOURCES["ecb"].matches("Meeting of 28-29 October 2026")
    assert mr.SOURCES["boj"].matches("Statement on Monetary Policy")
    assert not mr.SOURCES["boj"].matches("Summary of Opinions at the Monetary Policy Meeting on October 29 and 30, 2026")


def test_fed_decision_sentence_is_pulled_from_the_statement():
    sentence = mr.decision_sentence(mr.SOURCES["fed"], FED_PAGE)
    assert sentence.startswith("The Committee decided to maintain the target range")
    assert "3-3/4 to 4 percent" in sentence and "Voting" not in sentence


def test_cbc_decision_sentence_comes_from_the_feed_description():
    item = [i for i in mr.parse_feed(CBC_RSS) if mr.SOURCES["cbc"].matches(i["title"])][0]
    assert "重貼現率" in mr.decision_sentence(mr.SOURCES["cbc"], item["description"])


def test_fresh_items_only_and_undated_items_wait_for_the_baseline():
    now = datetime(2026, 10, 28, 18, 1, tzinfo=UTC)
    assert mr.is_fresh({"published": datetime(2026, 10, 28, 18, 0, tzinfo=UTC)}, now, first_pass=True)
    assert not mr.is_fresh({"published": datetime(2026, 10, 27, 18, 0, tzinfo=UTC)}, now, first_pass=False)
    assert not mr.is_fresh({"published": None}, now, first_pass=True)
    assert mr.is_fresh({"published": None}, now, first_pass=False)


def test_burst_windows_follow_each_markets_local_clock():
    fed, bea, cbc = mr.SOURCES["fed"], mr.SOURCES["bea"], mr.SOURCES["cbc"]
    # FOMC 14:00 New York on a Wednesday (still EDT on 28 Oct 2026) -> 18:00 UTC
    assert mr.poll_seconds(datetime(2026, 10, 28, 18, 0, 30, tzinfo=UTC), fed) == fed.burst_seconds
    assert mr.poll_seconds(datetime(2026, 10, 28, 18, 0, 30, tzinfo=UTC), cbc) == cbc.normal_seconds
    # US data 08:30 New York in winter = 13:30 UTC (21:30 Taipei), Friday
    assert mr.poll_seconds(datetime(2026, 12, 11, 13, 30, 5, tzinfo=UTC), bea) == bea.burst_seconds
    assert mr.poll_seconds(datetime(2026, 12, 12, 13, 30, 5, tzinfo=UTC), bea) == bea.normal_seconds  # Saturday
    # Taiwan central bank 16:00 Taipei = 08:00 UTC on a Thursday of a quarter-end month
    assert mr.poll_seconds(datetime(2026, 12, 17, 8, 1, tzinfo=UTC), cbc) == cbc.burst_seconds
    assert mr.poll_seconds(datetime(2026, 11, 19, 8, 1, tzinfo=UTC), cbc) == cbc.normal_seconds  # November: no meeting
    # the big Taiwan feed is never polled often outside its window
    assert cbc.normal_seconds >= 30 * 60


def test_us_data_window_is_only_around_0830_new_york():
    assert mr.in_us_data_window(datetime(2026, 12, 11, 13, 31, tzinfo=UTC))
    assert not mr.in_us_data_window(datetime(2026, 12, 11, 13, 50, tzinfo=UTC))
    assert not mr.in_us_data_window(datetime(2026, 12, 12, 13, 31, tzinfo=UTC))  # Saturday


def test_bls_numbers_are_computed_without_ai():
    payload = json.loads((FIXTURES / "bls.json").read_text(encoding="utf-8"))
    releases = mr.bls_releases(payload)
    cpi, jobs = releases["cpi"], releases["jobs"]
    assert cpi["period"] == "2026-10" and jobs["period"] == "2026-10"
    # BLS never published October 2025 CPI (shutdown, value "-"), so the year-on-year rate is left out, not invented.
    assert "年增" not in cpi["body"] and "月增 0.4%" in cpi["body"]
    assert "非農就業" in jobs["body"] and "失業率 4.1%" in jobs["body"]


def test_bls_cpi_math():
    def series(sid, points):
        return {"seriesID": sid, "data": [{"year": y, "period": f"M{m:02d}", "value": str(v)} for y, m, v in points]}
    payload = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        series("CUUR0000SA0", [(2026, 10, 103.0), (2025, 10, 100.0)]),
        series("CUSR0000SA0", [(2026, 10, 102.0), (2026, 9, 101.0)]),
        series("CUUR0000SA0L1E", [(2026, 10, 104.0), (2025, 10, 100.0)]),
        series("CES0000000001", [(2026, 10, 1200), (2026, 9, 1000)]),
        series("LNS14000000", [(2026, 10, 4.3), (2026, 9, 4.2)]),
    ]}}
    releases = mr.bls_releases(payload)
    assert "CPI 年增 3.0%" in releases["cpi"]["body"]
    assert "核心 CPI 年增 4.0%" in releases["cpi"]["body"]
    assert "月增 1.0%" in releases["cpi"]["body"]
    assert "非農就業 +200 千人" in releases["jobs"]["body"]
    assert "失業率 4.3%（前值 4.2%）" in releases["jobs"]["body"]


class FakeStore:
    def __init__(self):
        self.claimed = set()

    def record(self, run, day, url):
        if (run, day) in self.claimed:
            return False
        self.claimed.add((run, day))
        return True

    def release(self, run, day):
        self.claimed.discard((run, day))


def test_announce_sends_once_and_keeps_a_bell_copy():
    store, sent, bell = FakeStore(), [], []
    send = lambda kind, title, body: sent.append((kind, title, body)) or {"sent": True}
    assert mr.announce(store, "k1", "美國 FOMC 利率決策", "維持", send=send, history=lambda *a: bell.append(a))
    assert not mr.announce(store, "k1", "美國 FOMC 利率決策", "維持", send=send, history=lambda *a: bell.append(a))
    assert sent == [("news", "美國 FOMC 利率決策", "維持")] and len(bell) == 1


def test_announce_retries_when_telegram_fails():
    store = FakeStore()
    assert not mr.announce(store, "k1", "t", "b", send=lambda *a: {"sent": False}, history=lambda *a: None)
    assert mr.announce(store, "k1", "t", "b", send=lambda *a: {"sent": True}, history=lambda *a: None)


def test_bea_matches_national_gdp_and_pce_only():
    bea = mr.SOURCES["bea"]
    assert bea.matches("GDP, (Second Estimate) and Corporate Profits, 3rd Quarter 2026")
    assert bea.matches("GDP (Advance Estimate), 4th Quarter and Year 2025")
    assert bea.matches("Personal Income and Outlays, October 2026")
    assert not bea.matches("GDP by State, 2nd Quarter 2026")
    assert not bea.matches("Gross Domestic Product for the U.S. Virgin Islands, 2022")
    assert not bea.matches("Personal Income by State, 2nd Quarter 2023")


def test_ecb_decision_sentence():
    page = "<p>Menu Press</p><p>The Governing Council today decided to lower the three key ECB interest rates by 25 basis points. In particular...</p>"
    assert mr.decision_sentence(mr.SOURCES["ecb"], page) == "The Governing Council today decided to lower the three key ECB interest rates by 25 basis points."
