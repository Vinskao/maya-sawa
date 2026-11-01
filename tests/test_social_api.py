import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from maya_sawa.api import social_publishing as api
from maya_sawa.core.errors.errors import register_exception_handlers

CURRENT = {'productType': 'stock', 'code': '2330', 'revision': 5, 'model': 'm',
           'updatedAt': '2026-10-30T10:00:00+00:00', 'content': '結論：中性'}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api.market_ai_analysis_db, 'read',
                        lambda kind, code: {'analysis': CURRENT if (kind, code) == ('stock', '2330') else None})
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(api.router)
    return TestClient(app)


def test_card_for_the_current_public_revision_is_a_cacheable_png(client):
    response = client.get('/market/publishing/cards/stock/2330/5.png')
    assert response.status_code == 200
    assert response.headers['content-type'] == 'image/png'
    assert 'max-age' in response.headers['cache-control']
    assert Image.open(io.BytesIO(response.content)).size == (1080, 1350)


@pytest.mark.parametrize('path', ['/market/publishing/cards/stock/2330/4.png', '/market/publishing/cards/stock/9999/1.png',
                                  '/market/publishing/cards/research/2330/5.png', '/market/publishing/cards/macro/JP/1.png'])
def test_card_refuses_old_revisions_unknown_codes_and_non_public_kinds(client, path):
    assert client.get(path).status_code == 404


def test_status_and_manual_run_require_the_owner(client):
    assert client.get('/market/publishing/social/status').status_code == 401
    assert client.post('/market/publishing/social/run').status_code == 401
