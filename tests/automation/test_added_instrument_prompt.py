"""2026-11-11: a newly added instrument got its first AI analysis but never a research map."""
import asyncio
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.services import market_automation as automation


def test_the_first_run_for_an_added_instrument_also_asks_for_its_research_map(monkeypatch):
    store = automation.AutomationStore(create_engine('sqlite://', connect_args={'check_same_thread': False},
                                                     poolclass=StaticPool))
    sent = []

    async def fire(run, text):
        sent.append(text)
        return 'https://example.com/session'

    async def collect(items):
        return None

    monkeypatch.setenv('MARKET_ROUTINE_TAIWAN_TOKEN', 'test')
    monkeypatch.setattr(automation, 'fire_routine', fire)
    result = asyncio.run(automation.analyze_added(store, [{'code': '3037', 'name': '欣興', 'productType': 'stock'}],
                                                  collect, datetime(2026, 11, 11, 2, tzinfo=timezone.utc)))
    assert result['state'] == 'fired'
    assert '研究圖' in sent[0] and 'productType=research' in sent[0]
