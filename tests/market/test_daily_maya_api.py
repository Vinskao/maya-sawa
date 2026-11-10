from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api.daily_maya import make_router
from maya_sawa.databases.daily_maya_db import DailyMayaDatabase


class Analysis:
    def read(self, kind, code):
        return {'history': [{'revision': 2}] if (kind, code) == ('stock', '2330') else []}


def test_submit_review_authorization_and_source_revalidation():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db = DailyMayaDatabase(engine)
    analysis = Analysis()
    app = FastAPI()
    app.include_router(make_router(db, analysis, lambda request: request.headers.get('x-market-agent-key') == 'test',
                                   lambda: datetime(2026, 11, 3, 2, tzinfo=timezone.utc)))
    client = TestClient(app)
    body = {'day': '2026-11-03', 'content': '財報支持這個看法。', 'sources': ['stock:2330:2']}
    assert client.post('/market/daily-maya/proposals', json={**body, 'sources': ['stock:2330:3']}).status_code == 422
    row = client.post('/market/daily-maya/proposals', json=body).json()
    assert row['created'] and client.get('/market/daily-maya').json()['items'] == []
    assert client.get('/market/daily-maya/proposals').status_code == 401
    headers = {'x-market-agent-key': 'test'}
    assert len(client.get('/market/daily-maya/proposals', headers=headers).json()['proposals']) == 1
    assert client.post('/market/daily-maya/proposals/' + row['id'] + '/review', json={'decision': 'approved', 'note': 'verified'}).status_code == 401
    analysis.read = lambda *args: {'history': []}
    assert client.post('/market/daily-maya/proposals/' + row['id'] + '/review', headers=headers, json={'decision': 'approved', 'note': 'verified'}).status_code == 409
    assert client.get('/market/daily-maya').json()['items'] == []


def test_unspeakable_content_is_refused_at_submission_with_the_reason():
    """2026-11-10: a draft that the speech check would reject must fail at POST, not silently after approval."""
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    app = FastAPI()
    app.include_router(make_router(DailyMayaDatabase(engine), Analysis(), lambda request: False,
                                   lambda: datetime(2026, 11, 3, 2, tzinfo=timezone.utc)))
    client = TestClient(app)
    for content in ['需求改善；但成本上升。', '根據報告，需求穩健。', '**需求改善**：獲利下降。']:
        response = client.post('/market/daily-maya/proposals',
                               json={'day': '2026-11-03', 'content': content, 'sources': ['stock:2330:2']})
        assert response.status_code == 422, content
        assert 'content' in response.json()['detail'] and '朗讀' in response.json()['detail']
    ok = client.post('/market/daily-maya/proposals',
                     json={'day': '2026-11-03', 'content': '需求改善，獲利率卻下降。', 'sources': ['stock:2330:2']})
    assert ok.status_code == 200 and ok.json()['created']


def test_approval_publishes_once_and_identical_retry_is_idempotent():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db = DailyMayaDatabase(engine)
    queued = []
    app = FastAPI()
    app.include_router(make_router(db, Analysis(), lambda request: request.headers.get('x-market-agent-key') == 'test',
                                   lambda: datetime(2026, 11, 3, 2, tzinfo=timezone.utc),
                                   on_approved=lambda row: queued.append(row)))
    client = TestClient(app)
    body = {'day': '2026-11-03', 'content': '證據與影響。', 'sources': ['stock:2330:2']}
    first = client.post('/market/daily-maya/proposals', json=body).json()
    again = client.post('/market/daily-maya/proposals', json=body).json()
    assert first['id'] == again['id'] and not again['created']
    headers = {'x-market-agent-key': 'test'}
    path = '/market/daily-maya/proposals/' + first['id'] + '/review'
    assert client.post(path, headers=headers, json={'decision': 'approved', 'note': 'verified'}).status_code == 200
    assert client.post(path, headers=headers, json={'decision': 'approved', 'note': 'verified'}).status_code == 409
    assert client.get('/market/daily-maya').json()['items'][0]['id'] == first['id']
    assert len(queued) == 1 and queued[0]['content'] == body['content']
