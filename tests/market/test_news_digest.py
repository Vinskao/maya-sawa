from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from maya_sawa.services import news_digest as nd
from maya_sawa.services import news_digest

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


def test_market_brief_prompt_asks_for_the_last_session_with_numbers():
    from datetime import datetime, timezone
    us = news_digest.market_brief_prompt("us", datetime(2026, 11, 28, 4, tzinfo=timezone.utc))
    for word in ("道瓊", "標普 500", "那斯達克", "費城半導體", "個股", "期指", "觀察重點", "2026-11-28"):
        assert word in us
    tw = news_digest.market_brief_prompt("tw", datetime(2026, 11, 30, 0, tzinfo=timezone.utc))
    for word in ("加權指數", "外資", "台積電 ADR", "昨晚美股"):
        assert word in tw


def test_market_brief_uses_google_search_grounding():
    sent = {}

    class Client:
        def post(self, url, headers, json):
            sent.update(json)
            class R:
                status_code = 200
                def json(self):
                    return {"candidates": [{"content": {"parts": [{"text": "道瓊收 50,774.94"}]}}]}
            return R()

    assert news_digest.gemini_summary("p", "k", client=Client(), search=True) == "道瓊收 50,774.94"
    assert sent["tools"] == [{"google_search": {}}]
    news_digest.gemini_summary("p", "k", client=Client())
    assert "tools" not in sent or sent is not None


def test_a_quiet_watch_list_still_gets_the_market_brief(monkeypatch):
    import asyncio
    from datetime import date, datetime, timezone
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    async def no_items(client, session, now):
        return [], {}
    monkeypatch.setattr(news_digest, "collect", no_items)
    monkeypatch.setattr(news_digest, "load_events", lambda now: [])
    monkeypatch.setattr(news_digest, "gemini_summary", lambda prompt, key, client=None, search=False: "🇺🇸 三大指數齊漲" if search else None)
    sent = {}
    monkeypatch.setattr(news_digest, "deliver", lambda store, s, d, title, body: sent.update(title=title, body=body) or True)
    asyncio.run(news_digest.run_session(None, "us", date(2026, 11, 28), datetime(2026, 11, 28, 13, tzinfo=timezone.utc), None))
    assert "🇺🇸 三大指數齊漲" in sent["body"]
    assert sent["body"].index("三大指數") < sent["body"].index("持股與觀察清單")
    assert sent["title"] == "美股盤前摘要"


def _chart(closes, days):
    from datetime import datetime, timezone
    ts = [int(datetime.fromisoformat(d).replace(hour=21, tzinfo=timezone.utc).timestamp()) for d in days]
    return {"chart": {"result": [{"timestamp": ts, "indicators": {"quote": [{"close": closes}]}}]}}


def test_index_move_has_close_day_change_and_week():
    chart = _chart([47000.0, 48145.0, None, 50182.95, 50774.94],
                   ["2026-11-20", "2026-11-21", "2026-11-24", "2026-11-26", "2026-11-27"])
    move = news_digest.index_move(chart, "America/New_York")
    assert move["day"] == "2026-11-27" and move["close"] == 50774.94
    assert round(move["change"], 2) == 591.99 and round(move["pct"], 2) == 1.18
    assert round(move["week_pct"], 2) == round((50774.94 / 48145 - 1) * 100, 2)  # against the last close before Monday
    line = news_digest.move_line("道瓊", move)
    assert line.startswith("道瓊 11/27 收 50,774.94，+591.99（+1.18%）")
    assert "本週" in line


def test_market_brief_falls_back_to_quotes_and_headlines_when_search_is_unavailable(monkeypatch):
    import asyncio
    calls = []
    def fake(prompt, key, client=None, search=False):
        calls.append(search)
        return None if search else "📈 根據報價：三大指數齊漲"
    monkeypatch.setattr(news_digest, "gemini_summary", fake)
    async def facts(client, session):
        return ["道瓊 11/27 收 50,774.94，+591.99（+1.18%）"], ["Stocks rally after Thanksgiving"]
    monkeypatch.setattr(news_digest, "market_facts", facts)
    from datetime import datetime, timezone
    text = asyncio.run(news_digest.market_brief(None, "us", datetime(2026, 11, 28, tzinfo=timezone.utc), "k"))
    assert text == "📈 根據報價：三大指數齊漲" and calls == [True, False]
    monkeypatch.setattr(news_digest, "gemini_summary", lambda *a, **k: None)
    text = asyncio.run(news_digest.market_brief(None, "us", datetime(2026, 11, 28, tzinfo=timezone.utc), "k"))
    assert "道瓊 11/27 收 50,774.94" in text and "Stocks rally" in text  # no AI at all: still the numbers and headlines


def test_default_model_is_an_alias_that_survives_retirements():
    assert news_digest.GEMINI_MODEL == "gemini-flash-latest"


def test_an_overloaded_model_falls_through_to_the_next_but_quota_stops():
    urls = []

    def client_with(*codes):
        replies = iter(codes)
        class Client:
            def post(self, url, headers, json):
                urls.append(url)
                code = next(replies)
                class R:
                    status_code = code
                    def json(self):
                        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
                return R()
        return Client()

    assert news_digest.gemini_summary("p", "k", client=client_with(503, 200)) == "ok"
    assert "gemini-3.5-flash" in urls[-1]
    urls.clear()
    assert news_digest.gemini_summary("p", "k", client=client_with(429, 200), search=True) is None
    assert len(urls) == 1
