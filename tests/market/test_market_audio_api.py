from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from maya_sawa.databases.market_audio_db import MarketAudioDatabase
from maya_sawa.api.market_audio import make_router


def test_public_catalog_and_audio():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    db = MarketAudioDatabase(engine)
    db.save('macro', 'US', 10, '全文', b'ID3test', 'audio/mpeg', 'voice')
    db.save('daily', 'brief-1', 1, '每日完整精讀', b'daily-audio', 'audio/mpeg', 'voice')
    app = FastAPI()
    app.include_router(make_router(db))
    client = TestClient(app)
    catalog = client.get('/market/audio').json()
    items = catalog['items']
    assert catalog['presenterSettings']['maya']['videoFile'] == 'reporterMaya.mp4'
    assert catalog['presenterSettings']['uiobbeci']['voice'] == 'zh-CN-Xiaoxiao2:DragonHDFlashLatestNeural'
    assert any(item['productType'] == 'macro' and item['revision'] == 10 for item in items)
    response = client.get('/market/audio/macro/US/10')
    assert response.content == b'ID3test'
    assert response.headers['content-type'] == 'audio/mpeg'
    assert client.get('/market/audio/macro/US/11').status_code == 404
    assert client.get('/market/audio/daily/brief-1/1').content == b'daily-audio'
