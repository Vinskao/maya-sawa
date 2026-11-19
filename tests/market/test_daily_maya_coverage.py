from maya_sawa.services.daily_maya_coverage import message, uncovered_holdings

POSITIONS = [{"code": "3443", "name": "創意", "market": "TW"}, {"code": "3661", "name": "世芯-KY", "market": "TW"},
             {"code": "2454", "name": "聯發科", "market": "TW"}, {"code": "6857", "name": "ADVANTEST", "market": "JP"}]
EVENTS = [
    {"code": "3443", "name": "創意", "type": "volume_spike", "highlight": True},
    {"code": "3661", "name": "世芯-KY", "type": "financial_report", "highlight": True},
    {"code": "2454", "name": "聯發科", "type": "volume_spike", "highlight": True},
    {"code": "6857", "name": "ADVANTEST", "type": "volume_spike", "highlight": True, "market": "JP"},
    {"code": "3037", "name": "欣興", "type": "volume_spike", "highlight": True},      # not held: never required
    {"code": "3443", "name": "創意", "type": "insider_buy", "highlight": True},        # not a required kind
]


def test_lists_held_taiwan_stocks_with_events_that_the_text_skips():
    assert uncovered_holdings("聯發科今天出貨轉強。", POSITIONS, EVENTS) == ["創意（成交量進入近一年前幾大）", "世芯（新一季財報）"]


def test_name_or_its_first_two_characters_counts_as_covered():
    assert uncovered_holdings("創意與世芯都談到了，聯發也是。", POSITIONS, EVENTS) == []


def test_quiet_events_and_foreign_or_unheld_names_are_never_required():
    events = [{**EVENTS[0], "highlight": False}, EVENTS[3], EVENTS[4]]
    assert uncovered_holdings("沒提任何個股。", POSITIONS, events) == []


def test_message_names_the_missing_holdings():
    assert "創意（成交量進入近一年前幾大）" in message(["創意（成交量進入近一年前幾大）"])


def test_draft_that_skips_a_held_stock_with_an_event_is_refused_with_the_names():
    from datetime import datetime, timezone
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from maya_sawa.api.daily_maya import make_router
    from maya_sawa.databases.daily_maya_db import DailyMayaDatabase

    db = DailyMayaDatabase(create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))

    class Analysis:
        def read(self, kind, code): return {'history': [{'revision': 2}]}

    async def check(content, day): return uncovered_holdings(content, POSITIONS, EVENTS)

    app = FastAPI()
    app.include_router(make_router(db, Analysis(), lambda request: True, lambda: datetime(2026, 11, 3, 2, tzinfo=timezone.utc), coverage_check=check))
    body = {'day': '2026-11-03', 'content': '聯發科十月營收年增百分之十二點五。今天的市場精讀到這裡，我們下次見。', 'sources': ['stock:2454:2']}
    response = TestClient(app).post('/market/daily-maya/proposals', json=body)
    assert response.status_code == 422 and '創意' in response.json()['detail'] and '世芯' in response.json()['detail']
