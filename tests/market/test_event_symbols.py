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
