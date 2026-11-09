from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from maya_sawa.api.daily_maya import make_router
from maya_sawa.databases.daily_maya_db import DailyMayaDatabase

NOW = datetime(2026, 11, 3, 2, tzinfo=timezone.utc)


class Analysis:
    def read(self, kind, code):
        return {'history': [{'revision': 2}] if (kind, code) == ('stock', '2330') else []}


def client_and_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db = DailyMayaDatabase(engine)
    app = FastAPI()
    app.include_router(make_router(db, Analysis(), lambda request: request.headers.get('x-market-agent-key') == 'test',
                                   lambda: NOW))
    return TestClient(app), db


def test_each_episode_keeps_its_title_after_approval():
    db = DailyMayaDatabase(create_engine('sqlite:///:memory:'))
    row, _ = db.submit('2026-11-03', '財報顯示需求改善。', ['stock:2330:2'], NOW, title='台積電財報後的需求觀察')
    assert row['title'] == '台積電財報後的需求觀察'
    assert db.review(row['id'], 'approved', '來源已核對', NOW)
    assert db.published()[0]['title'] == '台積電財報後的需求觀察'


def test_title_is_optional_for_legacy_callers_and_stored_as_none():
    db = DailyMayaDatabase(create_engine('sqlite:///:memory:'))
    row, _ = db.submit('2026-11-03', '舊流程沒有標題。', ['stock:2330:2'], NOW)
    assert row['title'] is None


def test_existing_table_without_title_column_is_upgraded_in_place():
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text(
            'CREATE TABLE maya_sawa_daily_maya_proposal (id TEXT PRIMARY KEY, day TEXT NOT NULL, digest TEXT NOT NULL,'
            ' content TEXT NOT NULL, sources TEXT NOT NULL, status TEXT NOT NULL, submitted_at TIMESTAMP NOT NULL,'
            ' reviewed_at TIMESTAMP, review_note TEXT)'))
        connection.execute(text(
            "INSERT INTO maya_sawa_daily_maya_proposal VALUES ('old-1', '2026-11-02', 'd', '舊稿', '[\"stock:2330:2\"]',"
            " 'approved', '2026-11-02 01:00:00', '2026-11-02 01:30:00', 'ok')"))
    db = DailyMayaDatabase(engine)
    old = db.get('old-1')
    assert old['content'] == '舊稿' and old['title'] is None
    db.submit('2026-11-03', '新稿', ['stock:2330:2'], NOW, title='新標題')
    assert db.pending()[0]['title'] == '新標題'


def test_api_accepts_a_title_and_publishes_it():
    client, _ = client_and_db()
    body = {'day': '2026-11-03', 'title': '  淨流動性與聯發科的出貨驗證  ', 'content': '內容。', 'sources': ['stock:2330:2']}
    created = client.post('/market/daily-maya/proposals', json=body).json()
    assert created['created']
    headers = {'x-market-agent-key': 'test'}
    assert client.get('/market/daily-maya/proposals', headers=headers).json()['proposals'][0]['title'] == '淨流動性與聯發科的出貨驗證'
    client.post('/market/daily-maya/proposals/' + created['id'] + '/review', headers=headers,
                json={'decision': 'approved', 'note': 'verified'})
    assert client.get('/market/daily-maya').json()['items'][0]['title'] == '淨流動性與聯發科的出貨驗證'


def test_missing_title_gets_a_dated_default_so_the_episode_is_never_untitled():
    client, _ = client_and_db()
    body = {'day': '2026-11-03', 'content': '沒有標題的稿。', 'sources': ['stock:2330:2']}
    created = client.post('/market/daily-maya/proposals', json=body).json()
    headers = {'x-market-agent-key': 'test'}
    proposal = client.get('/market/daily-maya/proposals', headers=headers).json()['proposals'][0]
    assert created['created'] and proposal['title'] == '每日市場精讀｜2026/11/03'


@pytest.mark.parametrize('title', ['', '   ', 'x' * 121, '第一行\n第二行', '# 標題', '**粗體**'])
def test_invalid_titles_are_rejected(title):
    client, _ = client_and_db()
    body = {'day': '2026-11-03', 'title': title, 'content': '內容。', 'sources': ['stock:2330:2']}
    assert client.post('/market/daily-maya/proposals', json=body).status_code == 422
