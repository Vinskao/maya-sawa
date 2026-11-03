import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from maya_sawa.api import social_publishing as api
from maya_sawa.core.errors.errors import register_exception_handlers

import json

RESEARCH = {'productType': 'research', 'code': '2330', 'revision': 3, 'model': 'm', 'updatedAt': '2026-10-30T10:00:00+00:00',
            'content': json.dumps({'name': '台積電', 'summary': 'x', 'supplyChain': 'flowchart TB\n  A["a"] --> B["b"]',
                                   'technology': 'flowchart LR\n  C["c"] --> D["d"]'}, ensure_ascii=False)}
CURRENT = {'productType': 'stock', 'code': '2330', 'revision': 5, 'model': 'm',
           'updatedAt': '2026-10-30T10:00:00+00:00', 'content': '結論：中性'}


def _png():
    buffer = io.BytesIO()
    Image.new('RGB', (1080, 1350)).save(buffer, format='PNG')
    return buffer.getvalue()


CARD_PNG = _png()


@pytest.fixture
def client(monkeypatch):
    records = {('stock', '2330'): CURRENT, ('research', '2330'): RESEARCH}
    monkeypatch.setattr(api.market_ai_analysis_db, 'read', lambda kind, code: {'analysis': records.get((kind, code))})
    rendered = []
    monkeypatch.setattr(api, 'render_diagram_card', lambda title, source: rendered.append((title, source)) or CARD_PNG)
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


def test_diagram_images_come_from_the_current_research_record_in_field_order(client):
    first = client.get('/market/publishing/diagrams/2330/3/0.png')
    second = client.get('/market/publishing/diagrams/2330/3/1.png')
    assert first.status_code == second.status_code == 200
    assert first.headers['content-type'] == 'image/png' and 'max-age' in first.headers['cache-control']
    assert Image.open(io.BytesIO(first.content)).size == (1080, 1350)


@pytest.mark.parametrize('path', ['/market/publishing/diagrams/2330/2/0.png', '/market/publishing/diagrams/2330/3/2.png',
                                  '/market/publishing/diagrams/9999/1/0.png'])
def test_diagram_refuses_old_research_revisions_missing_diagrams_and_unknown_codes(client, path):
    assert client.get(path).status_code == 404


def test_diagram_titles_name_the_company_and_the_kind(client):
    from maya_sawa.services.social.diagram import diagram_title
    record = json.loads(RESEARCH['content'])
    assert diagram_title(record, 'supplyChain') == '台積電 · 供應鏈'
    assert diagram_title(record, 'technology') == '台積電 · 技術路線'
