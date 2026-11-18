"""2026-11-18: the dashboard's volume marks cover the same stocks as the Telegram volume alert, including stocks sold this week."""
from datetime import datetime
from zoneinfo import ZoneInfo

from maya_sawa.services import market_company_events as events

NOW = datetime(2026, 11, 18, 14, 0, tzinfo=ZoneInfo("Asia/Taipei"))   # a Wednesday


class FakeDb:
    def __init__(self, traded=None, fail=False):
        self.traded, self.fail, self.asked_since = traded or [], fail, None

    def latest_auto(self): return {"positions": [{"code": "2330", "productType": "stock"}]}
    def custom_symbols(self): return [{"code": "2454", "productType": "stock"}]
    def watch_symbols(self): return [{"code": "3037", "productType": "stock"}]

    def traded_since(self, since):
        self.asked_since = since
        if self.fail: raise RuntimeError("db down")
        return self.traded


def codes(items): return [item["code"] for item in items]


def test_a_stock_traded_this_week_but_no_longer_held_is_covered():
    db = FakeDb(traded=[{"code": "3443", "productType": "stock", "name": "創意"}])
    assert codes(events.event_symbols(db, NOW)) == ["2330", "2454", "3037", "3443"]
    assert db.asked_since.date().isoformat() == "2026-11-16"   # Monday of that week


def test_the_list_still_works_when_the_trade_history_is_unavailable():
    assert codes(events.event_symbols(FakeDb(fail=True), NOW)) == ["2330", "2454", "3037"]


def test_quote_selection_matches_what_the_refresh_caches():
    """The live quote cache is keyed by this exact list: Taiwan only, one entry per instrument."""
    from maya_sawa.services.shioaji_market import ShioajiMarketService
    items = [{"code": "3443", "productType": "stock", "market": "TW"}, {"code": "6857", "productType": "stock", "market": "JP"},
             {"code": "3443", "productType": "stock", "market": "TW", "name": "創意"}, {"code": "2330", "productType": "stock"}]
    assert [item["code"] for item in ShioajiMarketService.quote_selection(items)] == ["3443", "2330"]


def test_a_failed_volume_history_read_is_retried_not_remembered_for_the_day():
    from datetime import date, timedelta
    from maya_sawa.services.market_company_events import MarketCompanyEventsService
    today = date(2026, 11, 18)
    good = [((today - timedelta(days=i)).isoformat(), 1_000_000 + i) for i in range(1, 300)]
    calls = []

    def source(code, day):
        calls.append(code)
        if len(calls) == 1:
            raise RuntimeError("database busy")
        return good
    service = MarketCompanyEventsService()
    service.volume_history_source = source
    assert service._volume_events(["3443"], {}, {"3443": 9_000_000}, today) == []
    assert [e["code"] for e in service._volume_events(["3443"], {}, {"3443": 9_000_000}, today)] == ["3443"]
