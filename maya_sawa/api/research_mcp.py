"""Read-only MCP access to published Taiwan stock analyses."""
import asyncio
import json
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from ..core.auth.keycloak import get_bearer_token, verify_resource_bearer_token
from ..core.config.config import Config
from ..databases.market_ai_analysis_db import market_ai_analysis_db
from .market import analysis_target

router = APIRouter(prefix='/market/research', tags=['research-mcp'])
RESOURCE = Config.RESEARCH_MCP_RESOURCE_URL
METADATA = RESOURCE.removesuffix('/mcp') + '/.well-known/oauth-protected-resource'
SCOPE = 'research.read'
TOOL = 'get_stock_analysis'
MAX_BODY = 24000
PROTOCOLS = {'2025-03-26', '2025-06-18', '2025-11-25'}
logger = logging.getLogger(__name__)


class StockLookup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    market: Literal['TW']
    code: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        min_length=1, max_length=24, pattern=r'^[A-Za-z0-9]+$',
    )


async def research_user(request: Request):
    origin = request.headers.get('origin')
    if origin and origin != 'https://tymultiverse.cc':
        raise HTTPException(403, 'Origin not allowed')
    challenge = {'WWW-Authenticate': f'Bearer resource_metadata="{METADATA}", scope="{SCOPE}"'}
    token = get_bearer_token(request)
    if not token:
        raise HTTPException(401, 'Research sign-in required', headers=challenge)
    try:
        claims = verify_resource_bearer_token(token, RESOURCE)
    except HTTPException as exc:
        raise HTTPException(401, 'Research sign-in required', headers=challenge) from exc
    if SCOPE not in str(claims.get('scope', '')).split():
        raise HTTPException(403, 'Research scope required', headers=challenge)


@router.get('/.well-known/oauth-protected-resource', include_in_schema=False)
async def metadata():
    if not Config.KEYCLOAK_AUTH_SERVER_URL or not Config.KEYCLOAK_REALM:
        raise HTTPException(503, 'Research identity provider unavailable')
    issuer = Config.KEYCLOAK_AUTH_SERVER_URL.rstrip('/') + '/realms/' + Config.KEYCLOAK_REALM
    return {'resource': RESOURCE, 'authorization_servers': [issuer],
            'scopes_supported': [SCOPE], 'bearer_methods_supported': ['header']}


def lookup_stock(arguments: StockLookup):
    kind, code = analysis_target(arguments.code, 'stock')
    analysis = market_ai_analysis_db.read(kind, code)['analysis']
    identity = {'market': arguments.market, 'code': code}
    if analysis is None:
        return {**identity, 'status': 'not_found', 'message': 'No published Taiwan stock analysis found.'}
    return {
        **identity, 'status': 'found', 'analysis': analysis,
        'analysisId': f"stock:{code}:{analysis['revision']}",
        'analysisUrl': f'https://tymultiverse.cc/maya-sawa/market/dashboard/analysis/{code}',
    }


async def call_tool(params):
    if params.get('name') != TOOL:
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Unknown research tool'}]}
    try:
        arguments = StockLookup.model_validate(params.get('arguments', {}))
    except ValidationError:
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Use market TW and an alphanumeric Taiwan stock code.'}]}
    try:
        output = await asyncio.to_thread(lookup_stock, arguments)
    except Exception:
        logger.exception('Research stock analysis read failed')
        return {'isError': True, 'content': [{'type': 'text', 'text': 'Published analysis is temporarily unavailable.'}]}
    return {'content': [{'type': 'text', 'text': json.dumps(output, ensure_ascii=False)}], 'structuredContent': output}


@router.get('/mcp', include_in_schema=False, dependencies=[Depends(research_user)])
async def no_stream():
    return Response(status_code=405, headers={'Allow': 'POST'})


@router.post('/mcp', include_in_schema=False, dependencies=[Depends(research_user)])
async def mcp(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BODY:
            raise HTTPException(413, 'Request too large')
        body.extend(chunk)
    try:
        message = json.loads(body)
    except ValueError as exc:
        raise HTTPException(400, 'Invalid JSON-RPC request') from exc
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
        raise HTTPException(400, 'Invalid JSON-RPC request')
    method, params = message.get('method'), message.get('params', {})
    if not isinstance(method, str) or not isinstance(params, dict):
        raise HTTPException(400, 'Invalid JSON-RPC method or parameters')
    if 'id' not in message:
        if method.startswith('notifications/'):
            return Response(status_code=202)
        raise HTTPException(400, 'Invalid notification')

    envelope = {'jsonrpc': '2.0', 'id': message['id']}
    if method == 'initialize':
        version = params.get('protocolVersion')
        result = {
            'protocolVersion': version if isinstance(version, str) and version in PROTOCOLS else '2025-11-25',
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'TY Multiverse research', 'version': '1.0.0'},
        }
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': [{
            'name': TOOL, 'description': 'Read the latest published analysis for a Taiwan stock code.',
            'inputSchema': StockLookup.model_json_schema(),
            'annotations': {'readOnlyHint': True, 'destructiveHint': False, 'openWorldHint': False},
        }]}
    elif method == 'tools/call':
        result = await call_tool(params)
    else:
        return JSONResponse({**envelope, 'error': {'code': -32601, 'message': 'Method not found'}})
    return JSONResponse({**envelope, 'result': result})
