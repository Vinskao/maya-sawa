"""Read-only MCP access to published Taiwan stock analyses."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..core.auth.keycloak import get_bearer_token, verify_resource_bearer_token
from ..core.config.config import Config
from ..databases.market_ai_analysis_db import market_ai_analysis_db
from .market import analysis_target
from .mcp_core import McpServer, Tool

router = APIRouter(prefix='/market/research', tags=['research-mcp'])
RESOURCE = Config.RESEARCH_MCP_RESOURCE_URL
METADATA = RESOURCE.removesuffix('/mcp') + '/.well-known/oauth-protected-resource'
SCOPE = 'research.read'
TOOL = 'get_stock_analysis'
MAX_BODY = 24000


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


server = McpServer('TY Multiverse research', '1.0.0', [Tool(
    name=TOOL,
    description='Read the latest published analysis for a Taiwan stock code.',
    model=StockLookup,
    handler=lookup_stock,
    usage='Use market TW and an alphanumeric Taiwan stock code.',
    unavailable='Published analysis is temporarily unavailable.',
)], max_body=MAX_BODY)


@router.get('/mcp', include_in_schema=False, dependencies=[Depends(research_user)])
async def no_stream():
    return Response(status_code=405, headers={'Allow': 'POST'})


@router.post('/mcp', include_in_schema=False, dependencies=[Depends(research_user)])
async def mcp(request: Request):
    return await server.handle(request)
