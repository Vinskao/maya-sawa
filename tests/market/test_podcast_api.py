import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api.market_audio import make_router as make_audio_router
from maya_sawa.api.podcast import make_router as make_podcast_router
from maya_sawa.databases.daily_maya_db import DailyMayaDatabase
from maya_sawa.databases.market_audio_db import MarketAudioDatabase

NOW = datetime(2026, 11, 3, 1, 30, tzinfo=timezone.utc)
CONFIG = {'title': 'Birch Investments 每日市場精讀', 'description': 'd', 'link': 'https://tymultiverse.cc/learn/',
          'language': 'zh-tw', 'author': 'Birch', 'ownerName': 'Birch', 'ownerEmail': 'tianyikao@tymultiverse.cc',
          'imageUrl': 'https://tymultiverse.cc/images/podcast-cover.jpg', 'category': 'Business',
          'subcategory': 'Investing', 'audioBaseUrl': 'https://tymultiverse.cc/api/market/audio', 'disclaimer': '非投資建議。'}


def build():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    daily = DailyMayaDatabase(engine)
    audio = MarketAudioDatabase(engine)
    approved, _ = daily.submit('2026-11-03', '已核准的稿。', ['stock:2330:2'], NOW, title='已核准的標題')
    daily.review(approved['id'], 'approved', 'ok', NOW)
    no_audio, _ = daily.submit('2026-11-02', '已核准但尚無語音。', ['stock:2330:2'], NOW, title='還沒有語音')
    daily.review(no_audio['id'], 'approved', 'ok', NOW)
    pending, _ = daily.submit('2026-11-03', '尚未核准的稿。', ['stock:2330:2'], NOW, title='尚未核准')
    audio.save('daily', approved['id'], 1, '已核准的稿。', b'ID3' + b'x' * 97, 'audio/mpeg', 'voice')
    audio.save('daily', pending['id'], 1, '尚未核准的稿。', b'ID3-unapproved', 'audio/mpeg', 'voice')
    audio.save('stock', '2330', 1, '個股全文', b'ID3-stock', 'audio/mpeg', 'voice')
    app = FastAPI()
    app.include_router(make_podcast_router(audio, daily, CONFIG))
    app.include_router(make_audio_router(audio, daily))
    return TestClient(app), approved


def test_feed_lists_only_approved_daily_episodes_that_have_audio():
    client, approved = build()
    response = client.get('/market/podcast.xml')
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/rss+xml')
    items = ET.fromstring(response.content).findall('channel/item')
    assert [i.find('guid').text for i in items] == [approved['id']]
    assert items[0].find('title').text == '已核准的標題'
    assert items[0].find('enclosure').get('length') == '100'


def test_audio_catalog_carries_the_title_for_daily_items():
    client, approved = build()
    items = client.get('/market/audio').json()['items']
    daily = next(item for item in items if item['code'] == approved['id'])
    assert daily['title'] == '已核准的標題' and daily['day'] == '2026-11-03'
    assert daily['sources'] == ['stock:2330:2']
    assert 'size' in daily


def test_feed_is_cacheable_for_a_short_time():
    client, _ = build()
    assert 'max-age' in client.get('/market/podcast.xml').headers['cache-control']
