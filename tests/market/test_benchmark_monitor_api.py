from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from maya_sawa.api import tw_benchmark as api


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(api.router)
    monkeypatch.setattr(api.market_dashboard_db, 'engine', None)
    return TestClient(app)


def test_monitor_unavailable_is_explicit(client):
    assert client.get('/market/benchmark/monitor').status_code == 503


def test_live_monitor_cannot_be_cached_across_portfolio_updates(client, monkeypatch):
    from maya_sawa.databases.market_industry_db import market_industry_db
    monkeypatch.setattr(market_industry_db, 'sessions', None)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value.scalars.return_value.all.return_value = []
    monkeypatch.setattr(api.market_dashboard_db, 'engine', engine)
    monkeypatch.setattr(api.benchmark_monitor, 'current_observations', lambda codes: {})
    monkeypatch.setattr(api.benchmark_monitor, 'snapshot', lambda *args, **kwargs: {'revision': 'new-holdings'})
    result = client.get('/market/benchmark/monitor')
    assert result.status_code == 200
    assert result.headers['cache-control'] == 'no-store'


def test_rule_cannot_be_written_anonymously(client):
    body = dict(code='2330', checks=[], holdings=[], reviewNote='已確認來源及定位，測試用審核紀錄', expectedRevision=0)
    assert client.put('/market/benchmark/monitor/2330', json=body).status_code == 401


def test_reviewed_rule_refuses_missing_or_wrong_report_evidence(client, monkeypatch):
    monkeypatch.setattr(api, '_verify_agent', lambda key: None)
    monkeypatch.setattr(api, 'benchmark_monitor_view', lambda: {'nodes': [dict(code='2330', claims=[])]})
    body = dict(code='2330', checks=[dict(code='3037', metric='monthly.yoyPercent', operator='gte',
        threshold=60, maxAgeDays=60, weight=1, reportId='made-up', page=1,
        evidence='not reviewed', rationale='代理指標門檻')], holdings=[], reviewNote='已確認來源及定位，測試用審核紀錄', expectedRevision=0)
    assert client.put('/market/benchmark/monitor/2330', json=body).status_code == 422
    assert client.put('/market/benchmark/monitor/2454', json=body).status_code == 422
