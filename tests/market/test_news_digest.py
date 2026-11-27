from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from maya_sawa.services import news_digest as nd

UTC = timezone.utc
TPE = ZoneInfo("Asia/Taipei")
NOW = datetime(2026, 11, 27, 0, 0, tzinfo=UTC)  # 08:00 Taipei
SINCE = NOW - timedelta(hours=24)

TWSE_ROWS = [  # real field names; note the trailing space in "主旨 "
    {"出表日期": "1151127", "發言日期": "1151126", "發言時間": "163005", "公司代號": "4979", "公司名稱": "華星光",
     "主旨 ": "公告本公司董事會決議\r\n現金增資", "符合條款": "第11款", "說明": "1.董事會決議日期:115/11/26"},
    {"出表日期": "1151127", "發言日期": "1151120", "發言時間": "70003", "公司代號": "4979", "公司名稱": "華星光",
     "主旨 ": "舊公告", "說明": ""},
    {"出表日期": "1151127", "發言日期": "1151126", "發言時間": "90000", "公司代號": "2072", "公司名稱": "世紀能源",
     "主旨 ": "不在名單", "說明": ""},
]
TPEX_ROWS = [{"Date": "1151127", "發言日期": "1151126", "發言時間": "180000", "SecuritiesCompanyCode": "3081",
              "CompanyName": "聯亞", "主旨": "代子公司公告取得設備", "說明": "金額..."}]

CNYES = {"items": {"data": [
    {"newsId": 1, "title": "聯亞毛利率下滑", "summary": "價格競爭", "publishAt": int((NOW - timedelta(hours=2)).timestamp()),
     "stock": ["3081"], "market": [{"code": "3081", "name": "聯亞"}]},
    {"newsId": 2, "title": "大盤收紅", "summary": "", "publishAt": int((NOW - timedelta(hours=1)).timestamp()), "stock": []},
    {"newsId": 3, "title": "太舊", "summary": "", "publishAt": int((NOW - timedelta(days=3)).timestamp()), "stock": ["3081"]},
]}}

GOOGLE = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Nvidia beats estimates - Reuters</title><link>https://news.google.com/a</link>
<pubDate>Thu, 26 Nov 2026 22:00:00 GMT</pubDate></item>
<item><title>Old story - CNBC</title><link>https://news.google.com/b</link><pubDate>Mon, 23 Nov 2026 22:00:00 GMT</pubDate></item>
</channel></rss>"""

SEC = {"filings": {"recent": {
    "form": ["8-K", "10-Q", "8-K"],
    "acceptanceDateTime": ["2026-11-26T16:05:12.000Z", "2026-11-26T16:00:00.000Z", "2026-11-01T16:00:00.000Z"],
    "accessionNumber": ["0001045810-26-000101", "0001045810-26-000100", "0001045810-26-000090"],
    "primaryDocument": ["nvda-8k.htm", "q.htm", "old.htm"],
    "items": ["2.02,9.01", "", "5.02"],
}}, "cik": "1045810"}


def test_taiwan_announcements_from_both_exchanges_filtered_by_code_and_time():
    items = nd.twse_announcements(TWSE_ROWS, {"4979"}, SINCE) + nd.tpex_announcements(TPEX_ROWS, {"3081"}, SINCE)
    assert [(i["code"], i["title"]) for i in items] == [("4979", "公告本公司董事會決議現金增資"), ("3081", "代子公司公告取得設備")]
    assert items[0]["published"] == datetime(2026, 11, 26, 16, 30, 5, tzinfo=TPE)
    assert items[0]["kind"] == "公告"


def test_cnyes_news_keeps_tagged_recent_stories_only():
    items = nd.cnyes_news(CNYES, {"3081"}, SINCE)
    assert [i["title"] for i in items] == ["聯亞毛利率下滑"]
    assert items[0]["code"] == "3081" and items[0]["link"].endswith("/1")


def test_google_news_for_one_ticker():
    items = nd.google_news(GOOGLE, "NVDA", SINCE)
    assert [i["title"] for i in items] == ["Nvidia beats estimates - Reuters"]


def test_sec_8k_with_item_meaning():
    items = nd.sec_8k(SEC, "NVDA", SINCE)
    assert len(items) == 1
    assert "8-K" in items[0]["title"] and "財報" in items[0]["title"]
    assert items[0]["link"] == "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000101/nvda-8k.htm"


def test_digest_sessions_are_taiwan_and_us_pre_open():
    assert nd.due_session(datetime(2026, 11, 27, 0, 0, 30, tzinfo=UTC)) == ("tw", datetime(2026, 11, 27).date())
    # 08:00 New York in winter = 13:00 UTC
    assert nd.due_session(datetime(2026, 11, 27, 13, 1, tzinfo=UTC)) == ("us", datetime(2026, 11, 27).date())
    assert nd.due_session(datetime(2026, 11, 27, 5, 0, tzinfo=UTC)) is None
    assert nd.due_session(datetime(2026, 11, 28, 0, 0, 30, tzinfo=UTC)) is None  # Saturday


def test_without_gemini_the_digest_still_lists_headlines():
    items = nd.cnyes_news(CNYES, {"3081"}, SINCE)
    text = nd.fallback_summary(items, {"3081": "聯亞"})
    assert "3081 聯亞" in text and "聯亞毛利率下滑" in text


def test_prompt_contains_only_given_items_and_rules():
    items = nd.cnyes_news(CNYES, {"3081"}, SINCE)
    prompt = nd.build_prompt(items, {"3081": "聯亞"})
    assert "聯亞毛利率下滑" in prompt and "只根據" in prompt and "大盤收紅" not in prompt


def test_digest_message_header_and_empty_case():
    assert nd.digest_title("tw", 3) == "台股盤前摘要（3 則）"
    assert nd.digest_title("us", 0) == "美股盤前摘要（0 則）"


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


def test_each_session_sends_once_a_day():
    store, sent = FakeStore(), []
    send = lambda kind, title, body: sent.append(title) or {"sent": True}
    day = datetime(2026, 11, 27).date()
    assert nd.deliver(store, "tw", day, "台股盤前摘要（1 則）", "x", send=send, history=lambda *a: None)
    assert not nd.deliver(store, "tw", day, "台股盤前摘要（1 則）", "x", send=send, history=lambda *a: None)
    assert sent == ["台股盤前摘要（1 則）"]


def test_fund_holding_filler_is_dropped_from_google_news():
    feed = """<rss><channel>
<item><title>NVIDIA Corporation $NVDA Shares Sold by Orange Investment Advisors Inc. - MarketBeat</title><link>a</link><pubDate>Thu, 26 Nov 2026 22:00:00 GMT</pubDate></item>
<item><title>Helium Advisors Acquires New Stake in NVIDIA - Some Site</title><link>b</link><pubDate>Thu, 26 Nov 2026 22:00:00 GMT</pubDate></item>
<item><title>Nvidia signs supply deal with Samsung - Reuters</title><link>c</link><pubDate>Thu, 26 Nov 2026 22:00:00 GMT</pubDate></item>
</channel></rss>"""
    assert [i["title"] for i in nd.google_news(feed, "NVDA", SINCE)] == ["Nvidia signs supply deal with Samsung - Reuters"]


def test_targets_put_japanese_holdings_in_the_overseas_session(monkeypatch):
    from maya_sawa.databases import market_dashboard_db as module

    class FakeDb:
        def latest_auto(self):
            return {"positions": [{"code": "6857", "market": "JP", "name": "ADVANTEST CORP"},
                                  {"code": "2330", "name": "台積電"}]}
        def custom_symbols(self):
            return [{"code": "NVDA", "market": "US", "name": "NVIDIA"}]
        def watch_symbols(self):
            return []

    monkeypatch.setattr(module, "market_dashboard_db", FakeDb())
    taiwan, overseas, names = nd.targets()
    assert taiwan == {"2330"} and overseas == {"6857-JP", "NVDA"}
    assert names["6857-JP"] == "ADVANTEST CORP"


def test_calendar_preview_lists_tonights_release_once_in_taipei_time():
    nfp = datetime(2026, 12, 4, 13, 30, tzinfo=UTC)
    events = [
        {"groupId": "employment", "title": "Nonfarm payrolls", "scheduledDate": nfp.date(), "scheduledAt": nfp, "consensusValue": None},
        {"groupId": "employment", "title": "US NFP", "scheduledDate": nfp.date(), "scheduledAt": nfp, "consensusValue": "+120K"},
        {"groupId": "claims", "title": "Claims", "scheduledDate": datetime(2026, 12, 10).date(),
         "scheduledAt": datetime(2026, 12, 10, 13, 30, tzinfo=UTC), "consensusValue": None},
    ]
    morning = datetime(2026, 12, 4, 0, 0, tzinfo=UTC)  # 08:00 Taipei
    upcoming = nd.upcoming_events(events, morning)
    assert len(upcoming) == 1
    assert nd.calendar_section(upcoming) == "📅 未來 24 小時經濟數據（台北時間）：\n・12/04 21:30 美國非農就業（預期 +120K）"


def test_calendar_preview_says_so_when_nothing_is_scheduled():
    assert nd.upcoming_events([], NOW) == []
    assert "沒有排定" in nd.calendar_section([])
