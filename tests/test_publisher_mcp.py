import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from maya_sawa.core.security import SecurityMiddleware
from maya_sawa.core.errors.errors import register_exception_handlers

from maya_sawa.api import publisher_mcp as api
from maya_sawa.services.social_publish_queue import PublishQueue


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api.Config, 'KEYCLOAK_AUTH_SERVER_URL', 'https://issuer.test')
    monkeypatch.setattr(api.Config, 'KEYCLOAK_REALM', 'PeopleSystem')
    queue = PublishQueue(create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))
    monkeypatch.setattr(api, 'publishing_queue', lambda: queue)
    monkeypatch.setattr(api, 'notify_pending', lambda *a, **kw: {'sent': True})
    monkeypatch.setattr(api.market_ai_analysis_db, 'read', lambda kind, code: {'analysis': {'revision': 8}})
    monkeypatch.setattr(api.Config, 'SECURITY_ENABLED', True)
    monkeypatch.setattr(SecurityMiddleware, '_rate_limited', lambda *args: False)
    app = FastAPI(root_path='/maya-sawa')
    register_exception_handlers(app)
    app.add_middleware(SecurityMiddleware)
    app.include_router(api.router)
    return TestClient(app)


def rpc(client, method, params=None):
    return client.post('/market/publishing/mcp', json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}})


def test_unauthenticated_caller_gets_oauth_challenge_and_no_tools(client):
    response = rpc(client, 'tools/list')
    assert response.status_code == 401
    assert 'resource_metadata=' in response.headers['www-authenticate']
    assert client.get('/market/publishing/.well-known/oauth-protected-resource').status_code == 200


def authorize(client):
    client.app.dependency_overrides[api.publisher_user] = lambda: {'sub': 'owner'}


def test_stateless_handshake_notifications_and_scoped_tool_list(client):
    authorize(client)
    response = rpc(client, 'initialize', {'protocolVersion': '2025-11-25'})
    assert response.json()['result']['protocolVersion'] == '2025-11-25'
    assert client.post('/market/publishing/mcp', json={'jsonrpc': '2.0', 'method': 'notifications/initialized'}).status_code == 202
    tools = rpc(client, 'tools/list').json()['result']['tools']
    assert {tool['name'] for tool in tools} == {'birch_status', 'birch_enqueue_draft', 'birch_auth_required',
        'birch_resume', 'birch_claim', 'birch_published', 'birch_pending_review', 'birch_heartbeat'}
    assert client.get('/market/publishing/mcp').status_code == 405


def call(client, name, arguments):
    return rpc(client, 'tools/call', {'name': name, 'arguments': arguments}).json()['result']


def test_queue_tools_enforce_current_public_source_and_verified_resume(client):
    authorize(client)
    bad = call(client, 'birch_enqueue_draft', {'id': 'macro:US:7', 'draft': 'old source'})
    assert bad['isError']
    good = call(client, 'birch_enqueue_draft', {'id': 'macro:US:8', 'draft': 'public summary'})
    assert good['structuredContent']['state'] == 'pending_auth'
    assert call(client, 'birch_resume', {'verifiedAccount': 'someone', 'verifiedConnection': True})['isError']
    assert not call(client, 'birch_resume', {'verifiedAccount': 'birch_investments', 'verifiedConnection': True}).get('isError')
    assert call(client, 'birch_claim', {'id': 'macro:US:8'})['structuredContent']['claimed']
    assert not call(client, 'birch_claim', {'id': 'macro:US:8'})['structuredContent']['claimed']


def test_unknown_outcome_and_invalid_origin_do_not_allow_duplicate_publish(client):
    authorize(client)
    response = client.post('/market/publishing/mcp', headers={'Origin': 'https://evil.test'},
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert response.status_code == 403
    assert call(client, 'not_a_tool', {})['isError']


def test_missing_scope_or_resource_audience_is_rejected(client, monkeypatch):
    monkeypatch.setattr(api, 'verify_resource_bearer_token', lambda token, audience: {'sub': 'owner', '_roles': ['manage-users'], 'scope': ''})
    response = client.post('/market/publishing/mcp', headers={'Authorization': 'Bearer test'},
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert response.status_code == 403


def test_owner_with_publisher_scope_can_use_the_connector(client, monkeypatch):
    monkeypatch.setattr(api, 'verify_resource_bearer_token', lambda token, audience: {
        'sub': 'owner', '_roles': [api.Config.GIT_COMMIT_REQUIRED_ROLE], 'scope': api.SCOPE})
    response = client.post('/market/publishing/mcp', headers={'Authorization': 'Bearer test'},
        json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert response.status_code == 200


def test_general_middleware_is_not_bypassed_for_publisher_path_prefixes(client, monkeypatch):
    from fastapi import HTTPException
    from maya_sawa.core import security
    def reject(token):
        raise HTTPException(401, 'Invalid token audience')
    monkeypatch.setattr(security, 'verify_bearer_token', reject)
    response = client.post('/market/publishing/mcp/other', headers={'Authorization': 'Bearer publisher-only'}, json={})
    assert response.status_code == 401
