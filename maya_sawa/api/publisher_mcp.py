"""Owner-authorized, stateless MCP tools for the Birch outbox; never a social credential proxy."""
import asyncio
import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.auth.keycloak import get_bearer_token, verify_resource_bearer_token
from ..core.config.config import Config
from ..databases.market_ai_analysis_db import market_ai_analysis_db
from ..databases.market_notification_db import market_notification_db
from ..services.social_publish_queue import publishing_queue, notify_pending

router = APIRouter(prefix='/market/publishing', tags=['publishing'])
RESOURCE = 'https://peoplesystem.tatdvsonorth.com/maya-sawa/market/publishing/mcp'
METADATA = RESOURCE.removesuffix('/mcp') + '/.well-known/oauth-protected-resource'
SCOPE = 'birch.publish'
logger = logging.getLogger(__name__)


async def publisher_user(request: Request):
    check_origin(request)
    challenge = {'WWW-Authenticate': f'Bearer resource_metadata="{METADATA}", scope="{SCOPE}"'}
    token = get_bearer_token(request)
    if not token:
        raise HTTPException(401, 'Publisher sign-in required', headers=challenge)
    try:
        claims = verify_resource_bearer_token(token, RESOURCE)
    except HTTPException as exc:
        raise HTTPException(401, 'Publisher sign-in required', headers=challenge) from exc
    if SCOPE not in str(claims.get('scope', '')).split() or Config.GIT_COMMIT_REQUIRED_ROLE not in claims.get('_roles', []):
        raise HTTPException(403, 'Publisher scope and owner role required', headers=challenge)
    return claims


@router.get('/.well-known/oauth-protected-resource', include_in_schema=False)
async def metadata():
    if not Config.KEYCLOAK_AUTH_SERVER_URL or not Config.KEYCLOAK_REALM:
        raise HTTPException(503, 'Publisher identity provider unavailable')
    return {'resource': RESOURCE, 'authorization_servers': [
        Config.KEYCLOAK_AUTH_SERVER_URL.rstrip('/') + '/realms/' + Config.KEYCLOAK_REALM],
        'scopes_supported': [SCOPE], 'bearer_methods_supported': ['header']}


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Job(Empty):
    id: str = Field(pattern=r'^(stock|macro):[A-Z0-9.-]{1,24}:[1-9][0-9]*$')


class Draft(Job):
    draft: str = Field(min_length=1, max_length=1800)


class Published(Job):
    url: str = Field(max_length=300)


class AuthRequired(Empty):
    reason: Literal['missing_connection', 'login_required', 'token_expired']


class Resume(Empty):
    verifiedAccount: Literal['birch_investments']
    verifiedConnection: Literal[True]


TOOLS = {
    'birch_status': (Empty, 'Read the durable Threads outbox and pending state; call before drafting or posting.', True),
    'birch_enqueue_draft': (Draft, 'Store a draft for an existing current public analysis revision. Same id is idempotent.', False),
    'birch_auth_required': (AuthRequired, 'Keep drafts pending and notify the owner once through Maya Sawa Telegram when Metricool/Threads needs login.', False),
    'birch_resume': (Resume, 'Resume pending_auth only after verifying Metricool connection and birch_investments Threads brand. Does not retry pending_review.', False),
    'birch_claim': (Job, 'Atomically claim one ready draft. Publish through Metricool only when claimed=true.', False),
    'birch_published': (Published, 'Record a verified live Threads post URL after publication or reconciliation. Never guess a URL.', False),
    'birch_pending_review': (Job, 'Mark an in-flight publication with unknown outcome for manual reconciliation; never automatically resend.', False),
    'birch_heartbeat': (Empty, 'Call on every scheduled run, including no-update runs. Three hours without heartbeat alerts the owner.', False),
}


def tool_list():
    return [{'name': name, 'description': description, 'inputSchema': model.model_json_schema(),
             'annotations': {'readOnlyHint': read_only, 'destructiveHint': False,
                             'openWorldHint': name in {'birch_auth_required', 'birch_pending_review', 'birch_enqueue_draft'}}}
            for name, (model, description, read_only) in TOOLS.items()]


def run_tool(name, raw_arguments):
    if name not in TOOLS:
        raise ValueError('Unknown publisher tool')
    arguments = TOOLS[name][0].model_validate(raw_arguments)
    queue = publishing_queue()
    if name == 'birch_status':
        return queue.status()
    if name == 'birch_enqueue_draft':
        kind, code, revision = arguments.id.split(':')
        current = market_ai_analysis_db.read(kind, code).get('analysis')
        if not current or current['revision'] != int(revision):
            raise ValueError('Draft must refer to the current public analysis revision')
        job = queue.enqueue(arguments.id, arguments.draft)
        if job['state'] == 'pending_auth':
            notify_pending(queue, history=market_notification_db.add)
        return job
    if name == 'birch_auth_required':
        queue.auth_required(arguments.reason)
        return {'state': 'pending_auth', 'notification': notify_pending(queue, history=market_notification_db.add)}
    if name == 'birch_resume':
        queue.resume()
        queue.heartbeat()
        return queue.status()
    if name == 'birch_claim':
        return {'id': arguments.id, 'claimed': queue.claim(arguments.id)}
    if name == 'birch_published':
        return queue.complete(arguments.id, arguments.url)
    if name == 'birch_pending_review':
        queue.review(arguments.id)
        return {'state': 'pending_review', 'notification': notify_pending(queue, history=market_notification_db.add)}
    queue.heartbeat()
    return {'received': True}


def check_origin(request):
    origin = request.headers.get('origin')
    if origin and origin not in {'https://chatgpt.com', 'https://tymultiverse.cc'}:
        raise HTTPException(403, 'Origin not allowed')


@router.get('/mcp', include_in_schema=False)
async def no_stream(request: Request, user=Depends(publisher_user)):
    check_origin(request)
    return Response(status_code=405, headers={'Allow': 'POST'})


@router.post('/mcp', include_in_schema=False)
async def mcp(request: Request, user=Depends(publisher_user)):
    check_origin(request)
    body = await request.body()
    if len(body) > 24000:
        raise HTTPException(413, 'Request too large')
    try:
        message = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(400, 'Invalid JSON-RPC request') from exc
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
        raise HTTPException(400, 'Invalid JSON-RPC request')
    method, params = message.get('method'), message.get('params') or {}
    if not isinstance(params, dict):
        raise HTTPException(400, 'Invalid JSON-RPC parameters')
    if 'id' not in message:
        if isinstance(method, str) and method.startswith('notifications/'):
            return Response(status_code=202)
        raise HTTPException(400, 'Invalid notification')
    result = None
    if method == 'initialize':
        supported = {'2025-03-26', '2025-06-18', '2025-11-25'}
        version = params.get('protocolVersion')
        result = {'protocolVersion': version if isinstance(version, str) and version in supported else '2025-11-25',
                  'capabilities': {'tools': {}}, 'serverInfo': {'name': 'Birch publishing queue', 'version': '1.0.0'}}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': tool_list()}
    elif method == 'tools/call':
        try:
            output = await asyncio.to_thread(run_tool, params.get('name'), params.get('arguments', {}))
            result = {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=False)}], 'structuredContent': output}
        except (ValidationError, ValueError) as exc:
            text = 'Invalid publisher tool arguments' if isinstance(exc, ValidationError) else str(exc)
            result = {'isError': True, 'content': [{'type': 'text', 'text': text}]}
        except Exception as exc:
            logger.warning('Publisher tool failed: %s', type(exc).__name__)
            result = {'isError': True, 'content': [{'type': 'text', 'text': 'Publishing state unavailable; do not publish or retry until verified.'}]}
    else:
        return JSONResponse({'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32601, 'message': 'Method not found'}})
    return JSONResponse({'jsonrpc': '2.0', 'id': message['id'], 'result': result})
