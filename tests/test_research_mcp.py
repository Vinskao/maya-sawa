import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import market, publisher_mcp, research_mcp as api
from maya_sawa.core import security
from maya_sawa.core.errors.errors import register_exception_handlers
from tests.social.test_publisher_auth import token  # noqa: F401


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api.Config, 'KEYCLOAK_AUTH_SERVER_URL', 'https://issuer.test')
    monkeypatch.setattr(api.Config, 'KEYCLOAK_REALM', 'test')
    monkeypatch.setattr(api.Config, 'SECURITY_ENABLED', True)
    monkeypatch.setattr(security.SecurityMiddleware, '_rate_limited', lambda *args: False)
    app = FastAPI(root_path='/maya-sawa')
    register_exception_handlers(app)
    app.add_middleware(security.SecurityMiddleware)
    app.include_router(api.router)
    app.include_router(publisher_mcp.router)
    app.include_router(market.router)
    return TestClient(app)


PATH = '/market/research/mcp'


def rpc(client, method, params=None, bearer=None, path=PATH, **headers):
    if bearer:
        headers['Authorization'] = f'Bearer {bearer}'
    return client.post(path, headers=headers, json={
        'jsonrpc': '2.0', 'id': 7, 'method': method, 'params': params or {},
    })


def test_resource_discovery_and_signed_token_isolation(client, token):
    resource = 'https://tymultiverse.cc/maya-sawa/market/research/mcp'
    metadata = client.get('/market/research/.well-known/oauth-protected-resource').json()
    assert metadata['resource'] == resource
    assert metadata['scopes_supported'] == ['research.read']
    missing = rpc(client, 'tools/list')
    assert missing.status_code == 401
    assert resource.removesuffix('/mcp') + '/.well-known/oauth-protected-resource' in missing.headers['www-authenticate']
    assert rpc(client, 'tools/list', bearer=token(aud=resource)).status_code == 403
    assert rpc(client, 'tools/list', bearer=token(aud=publisher_mcp.RESOURCE, scope='research.read')).status_code == 401
    reader = token(aud=resource, azp='research', scope='research.read', sub='reader')
    assert rpc(client, 'tools/list', bearer=reader, path='/market/publishing/mcp').status_code == 401
    assert rpc(client, 'tools/list', bearer=reader, path=PATH + '/extra').status_code == 401
    assert client.put('/market/dashboard/analysis/2330', headers={'Authorization': f'Bearer {reader}'}, json={}).status_code == 401
    assert rpc(client, 'tools/list', bearer=reader, Origin='https://other.test').status_code == 403
    headers = {'Authorization': f'Bearer {reader}'}
    assert client.post(PATH, headers=headers, content=b'x' * 24001).status_code == 413
    assert client.get(PATH, headers=headers).status_code == 405
    assert client.post(PATH, headers=headers, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code == 202
    assert rpc(client, 'initialize', {'protocolVersion': '2025-11-25'}, reader).json()['result']['protocolVersion'] == '2025-11-25'
    tools = rpc(client, 'tools/list', bearer=reader).json()['result']['tools']
    assert [tool['name'] for tool in tools] == ['get_stock_analysis']
    assert tools[0]['annotations']['readOnlyHint'] is True


def test_lookup_reads_the_public_analysis_and_rejects_unsupported_codes(client, token, monkeypatch):
    analysis = {'revision': 5, 'updatedAt': '2026-11-19T02:00:00+00:00', 'model': 'fixture', 'content': '台積電分析'}
    reads = []

    def read(kind, code):
        reads.append((kind, code))
        return {'analysis': analysis if code == '2330' else None, 'history': [{'revision': 4}]}

    monkeypatch.setattr(api.market_ai_analysis_db, 'read', read)
    bearer = token(aud=api.RESOURCE, scope=api.SCOPE)

    def lookup(code, market_code='TW', name='get_stock_analysis'):
        return rpc(client, 'tools/call', {'name': name, 'arguments': {
            'market': market_code, 'code': code,
        }}, bearer).json()['result']

    result = lookup(' 2330 ')['structuredContent']
    assert result['analysis'] == analysis
    assert result['analysisId'] == 'stock:2330:5'
    assert result['analysisUrl'].endswith('/market/dashboard/analysis/2330')
    assert lookup('9999')['structuredContent']['status'] == 'not_found'
    assert lookup('AAPL', 'US')['isError']
    assert lookup('7203-JP')['isError']
    assert lookup('../2330')['isError']
    assert lookup('2330', name='birch_claim')['isError']
    assert reads == [('stock', '2330'), ('stock', '9999')]
    assert client.get('/market/dashboard/analysis/2330').json()['analysis'] == result['analysis']
