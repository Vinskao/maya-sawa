"""Read-only MCP access to published market research."""
import asyncio
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ..core.auth.keycloak import get_bearer_token, verify_resource_bearer_token
from ..core.config.config import Config
from ..databases.daily_maya_db import get_daily_maya_db
from ..databases.market_ai_analysis_db import market_ai_analysis_db
from ..services.market_macro import (
    CSP_SERIES, TAIEX_BIAS_SERIES, TWSE_MARGIN_CALL_SERIES, TWSE_MARGIN_SERIES, TWSE_MARKET_PE_SERIES,
)
from .daily_maya import default_title
from .market import analysis_target, get_market_macro_dashboard, list_macro_node_analyses
from .mcp_core import McpServer, Tool
from .tw_benchmark import benchmark_monitor_view

router = APIRouter(prefix='/market/research', tags=['research-mcp'])
RESOURCE = Config.RESEARCH_MCP_RESOURCE_URL
METADATA = RESOURCE.removesuffix('/mcp') + '/.well-known/oauth-protected-resource'
SCOPE = 'research.read'
TOOL = 'get_stock_analysis'
MAX_BODY = 24000
SERIES_GROUPS = {
    'taiex_bias': TAIEX_BIAS_SERIES.keys(),
    'valuation': TWSE_MARKET_PE_SERIES.keys(),
    'csp': CSP_SERIES.keys(),
    'leverage': TWSE_MARGIN_SERIES.keys() | TWSE_MARGIN_CALL_SERIES.keys(),
}


class Lookup(BaseModel):
    model_config = ConfigDict(extra='forbid')


class StockLookup(Lookup):
    market: Literal['TW']
    code: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        min_length=1, max_length=24, pattern=r'^[A-Za-z0-9]+$',
    )


class MacroLookup(Lookup):
    series: str | None = Field(default=None, max_length=64, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')


class BenchmarkLookup(Lookup):
    code: str | None = Field(default=None, max_length=24, pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]*$')


class DailyLookup(Lookup):
    date: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')

    @field_validator('date')
    @classmethod
    def validate_calendar_date(cls, value):
        if value is not None:
            date.fromisoformat(value)
        return value


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


async def lookup_macro(arguments: MacroLookup):
    dashboard, nodes = await asyncio.gather(get_market_macro_dashboard(), list_macro_node_analyses())
    if dashboard['status'] == 'unavailable':
        raise RuntimeError('Macro data unavailable')
    series = arguments.series
    codes = SERIES_GROUPS.get(series.lower(), {series.upper()}) if series else None
    indicators = [
        {key: value for key, value in item.items() if key != 'history'}
        for item in dashboard['indicators'] if codes is None or item['code'] in codes
    ]
    analyses = [
        item for item in nodes['analyses'] if codes is None or item['code'] == series.upper()
    ]
    return {
        'status': 'found' if indicators or analyses else 'not_found',
        'asOf': dashboard.get('asOf'), 'indicators': indicators, 'analyses': analyses,
    }


def lookup_benchmark(arguments: BenchmarkLookup):
    snapshot = benchmark_monitor_view()
    code = arguments.code.upper() if arguments.code else None
    fields = ('code', 'annual', 'claims', 'filing', 'validation')
    nodes = [
        {key: node[key] for key in fields}
        for node in snapshot['nodes'] if code is None or node['code'] == code
    ]
    return {
        'status': 'found' if nodes else 'not_found',
        'generatedAt': snapshot.get('generatedAt'), 'method': snapshot.get('method'), 'nodes': nodes,
    }


def lookup_daily(arguments: DailyLookup):
    rows = get_daily_maya_db().published(day=arguments.date, limit=1)
    if not rows:
        return {'status': 'not_found', 'date': arguments.date}
    row = rows[0]
    return {
        'status': 'found', 'date': row['day'], 'title': row['title'] or default_title(row['day']),
        'reading': row['reading'] or row['content'], 'sources': row['sources'],
    }


server = McpServer('TY Multiverse research', '1.1.0', [Tool(
    name=TOOL,
    description='Read the latest published analysis for a Taiwan stock code.',
    model=StockLookup,
    handler=lookup_stock,
    usage='Use market TW and an alphanumeric Taiwan stock code.',
    unavailable='Published analysis is temporarily unavailable.',
    narrow='Query the public stock analysis API for the full text.',
), Tool(
    name='get_macro_snapshot',
    description='Read latest macro indicator values and logic-chain analyses. Filter by series group, indicator code or node ID.',
    model=MacroLookup,
    handler=lookup_macro,
    usage='Omit series or use a group (taiex_bias, valuation, csp, leverage), indicator code or node ID.',
    unavailable='Macro research is temporarily unavailable.',
    narrow='Retry with a single series code or node ID, or query the public macro dashboard API.',
), Tool(
    name='get_benchmark_monitor',
    description='Read published semiconductor benchmark leader claims and validation. Optionally filter by leader code.',
    model=BenchmarkLookup,
    handler=lookup_benchmark,
    usage='Omit code or use a benchmark leader code, such as 2330.',
    unavailable='Benchmark research is temporarily unavailable.',
    narrow='Retry with a single leader code, or query the public benchmark monitor API.',
), Tool(
    name='get_daily_reading',
    description='Read the latest approved Maya market reading or select one by Taipei calendar date.',
    model=DailyLookup,
    handler=lookup_daily,
    usage='Omit date for the latest approved reading or use YYYY-MM-DD.',
    unavailable='Daily market readings are temporarily unavailable.',
    narrow='Select an episode by date, or use the public daily reading API for the full text.',
)], max_body=MAX_BODY)


@router.get('/mcp', include_in_schema=False, dependencies=[Depends(research_user)])
async def no_stream():
    return Response(status_code=405, headers={'Allow': 'POST'})


@router.post('/mcp', include_in_schema=False, dependencies=[Depends(research_user)])
async def mcp(request: Request):
    return await server.handle(request)
