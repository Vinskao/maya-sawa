"""2026-11-11: the spoken script (commas and full stops only, no paragraphs) is unreadable as page text.

A proposal now carries two versions of the same piece: content for speech synthesis and reading for the audience.
"""
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from maya_sawa.api.daily_maya import make_router
from maya_sawa.databases.daily_maya_db import DailyMayaDatabase
from maya_sawa.services.daily_maya_reading import InvalidReading, validate_reading
from maya_sawa.services.podcast_feed import build_podcast_rss

READING = ('## 總經：淨流動性轉寬\n\n聯準會資產負債表縮減放慢，淨流動性較上月增加 1.2%。這對評價倍數是支撐（但不是營收）。\n\n'
           '風險在於財政部帳戶回補，下一個驗證點是月底的準備金餘額。\n\n'
           '## 個股：聯發科\n\n10 月營收年增 12.5%、季增 3%，出貨驗證仍在軌道上；毛利率 48.1%。')
SPOKEN = '淨流動性較上月增加百分之一點二，這對評價倍數是支撐。聯發科十月營收年增百分之十二點五。'


def client_and_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db = DailyMayaDatabase(engine)

    class Analysis:
        def read(self, kind, code):
            return {'history': [{'revision': 2}]}

    app = FastAPI()
    app.include_router(make_router(db, Analysis(), lambda request: request.headers.get('x-market-agent-key') == 'test',
                                   lambda: datetime(2026, 11, 3, 2, tzinfo=timezone.utc)))
    return TestClient(app), db


def test_reading_version_keeps_paragraphs_headings_and_ordinary_punctuation():
    assert validate_reading('  ' + READING + '\n\n') == READING


@pytest.mark.parametrize('bad', [
    SPOKEN * 5,                                         # one glued block: the very problem being fixed
    '第一段。\n\n第二段。',                               # too few paragraphs to be a readable layout
    '第一段。\n\n<script>x</script>\n\n第三段。',          # markup
    '第一段。\n\n資料截點是昨天。\n\n第三段。',             # process wording is not for the audience either
    '第一段。\n\n' + '很長的一段，' * 150 + '\n\n第三段。',  # a wall of text inside one paragraph
    '',
])
def test_reading_version_refuses_text_that_is_not_reader_friendly(bad):
    with pytest.raises(InvalidReading):
        validate_reading(bad)


def test_proposal_stores_both_versions_and_publishes_them_together():
    client, _ = client_and_db()
    body = {'day': '2026-11-03', 'title': '淨流動性轉寬與聯發科出貨驗證', 'content': SPOKEN, 'reading': READING,
            'sources': ['stock:2454:2']}
    row = client.post('/market/daily-maya/proposals', json=body).json()
    headers = {'x-market-agent-key': 'test'}
    pending = client.get('/market/daily-maya/proposals', headers=headers).json()['proposals'][0]
    assert pending['content'] == SPOKEN and pending['reading'] == READING
    assert client.post(f"/market/daily-maya/proposals/{row['id']}/review", headers=headers,
                       json={'decision': 'approved', 'note': 'ok'}).status_code == 200
    item = client.get('/market/daily-maya').json()['items'][0]
    assert item['content'] == SPOKEN and item['reading'] == READING


def test_unreadable_reading_is_refused_with_the_reason_and_missing_reading_stays_allowed():
    client, _ = client_and_db()
    body = {'day': '2026-11-03', 'content': SPOKEN, 'sources': ['stock:2454:2']}
    refused = client.post('/market/daily-maya/proposals', json={**body, 'reading': SPOKEN * 5})
    assert refused.status_code == 422 and 'reading' in refused.json()['detail']
    assert client.post('/market/daily-maya/proposals', json=body).json()['created']


def test_same_script_with_a_corrected_reading_is_a_new_proposal():
    """A draft rejected for its reading version must be resubmittable without touching the spoken script."""
    client, _ = client_and_db()
    body = {'day': '2026-11-03', 'content': SPOKEN, 'sources': ['stock:2454:2']}
    first = client.post('/market/daily-maya/proposals', json=body).json()
    second = client.post('/market/daily-maya/proposals', json={**body, 'reading': READING}).json()
    assert second['created'] and second['id'] != first['id']
    assert not client.post('/market/daily-maya/proposals', json={**body, 'reading': READING}).json()['created']


def test_existing_table_gains_the_reading_column():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    DailyMayaDatabase(engine)
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE maya_sawa_daily_maya_proposal DROP COLUMN reading'))
    db = DailyMayaDatabase(engine)
    row, created = db.submit('2026-11-03', SPOKEN, ['stock:2454:2'], datetime(2026, 11, 3, tzinfo=timezone.utc),
                             reading=READING)
    assert created and db.get(row['id'])['reading'] == READING


def test_podcast_show_notes_use_the_reading_version_when_there_is_one():
    config = {'title': 't', 'description': 'd', 'link': 'https://example.com', 'language': 'zh-TW', 'author': 'a',
              'ownerName': 'o', 'ownerEmail': 'o@example.com', 'category': 'Business', 'explicit': False,
              'imageUrl': 'https://example.com/c.jpg', 'audioBaseUrl': 'https://example.com/audio',
              'disclaimer': '非投資建議'}
    episode = {'id': 'e1', 'revision': 1, 'day': '2026-11-03', 'title': 'T', 'content': SPOKEN, 'reading': READING,
               'sources': ['stock:2454:2'], 'createdAt': '2026-11-03T02:00:00+00:00', 'size': 10}
    try:
        rss = build_podcast_rss([episode], config)
    except KeyError:
        from maya_sawa.api.podcast import load_podcast_config
        rss = build_podcast_rss([episode], load_podcast_config())
    assert '總經：淨流動性轉寬' in rss and '年增 12.5%' in rss and '## ' not in rss
    assert '百分之十二點五' not in rss
