import asyncio
import importlib
from datetime import datetime, timezone
from unittest.mock import Mock
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def history_module(monkeypatch):
    from maya_sawa.core.config.config import Config
    monkeypatch.setattr(Config, 'DB_CONNECTION_STRING', '')
    return importlib.import_module('maya_sawa.databases.portfolio_history_db')


def payload():
    return dict(balanceAvailable=True, accountErrors={},
                fetchedAt='2026-10-12T06:00:00+00:00', totalAssetsEstimated=300.25,
                cashBalance=50, stockMarketValue=200, futuresEquity=50.25, totalPnl=-5,
                source='Sinopac Shioaji')


def test_valuation_time_is_source_time_and_decimal_is_preserved(history_module):
    values = history_module.taiwan_history_values(payload())
    assert str(values['total_assets']) == '300.25'
    assert values['valued_at'] == datetime(2026, 10, 12, 6, tzinfo=timezone.utc)
    assert values['total_pnl'] == -5


@pytest.mark.parametrize('patch', [
    {'accountErrors': {'stock': 'unavailable'}}, {'balanceAvailable': False},
    {'totalAssetsEstimated': None}, {'totalAssetsEstimated': float('nan')},
    {'fetchedAt': '2026-10-12T06:00:00'}, {'fetchedAt': 'invalid'},
    {'ibkr': {'twd': {'netLiquidation': 100}}}, {'cashBalance': float('inf')},
])
def test_incomplete_or_merged_valuations_are_not_points(history_module, patch):
    assert history_module.taiwan_history_values(dict(payload(), **patch)) is None


def test_successful_refresh_records_without_a_page_request(history_module, monkeypatch):
    from maya_sawa.services.shioaji_market import ShioajiMarketService
    service = ShioajiMarketService()
    data = payload()
    async def fetch(_):
        return data
    monkeypatch.setattr(service, '_run_with_relogin', fetch)
    monkeypatch.setattr(service, '_write_cached_payload', Mock())
    record = Mock(return_value=True)
    monkeypatch.setattr(history_module.portfolio_history_db, 'record_taiwan', record)
    assert asyncio.run(service._refresh_payload('PORTFOLIO', object())) is True
    record.assert_called_once_with(data)


def test_history_failure_does_not_break_market_cache(history_module, monkeypatch):
    from maya_sawa.services.shioaji_market import ShioajiMarketService
    service = ShioajiMarketService()
    async def fetch(_):
        return payload()
    monkeypatch.setattr(service, '_run_with_relogin', fetch)
    write = Mock()
    monkeypatch.setattr(service, '_write_cached_payload', write)
    monkeypatch.setattr(history_module.portfolio_history_db, 'record_taiwan', Mock(side_effect=RuntimeError('DB down')))
    assert asyncio.run(service._refresh_payload('PORTFOLIO', object())) is True
    write.assert_called_once()


def test_history_can_read_five_calendar_years_of_saved_snapshots(history_module):
    db = history_module.PortfolioHistoryDatabase.__new__(history_module.PortfolioHistoryDatabase)
    context = MagicMock()
    query = context.__enter__.return_value.query.return_value.order_by.return_value
    query.limit.return_value.all.return_value = []
    db.get_session = Mock(return_value=context)
    assert db.history(1830) == []
    query.limit.assert_called_once_with(1830)
