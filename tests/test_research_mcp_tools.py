import json

import pytest

from maya_sawa.api import research_mcp as api
from tests.test_research_mcp import client, rpc, token  # noqa: F401


@pytest.fixture
def call(client, token):
    bearer = token(aud=api.RESOURCE, scope=api.SCOPE)

    def invoke(name, arguments):
        return rpc(client, 'tools/call', {'name': name, 'arguments': arguments}, bearer).json()['result']

    return invoke


@pytest.fixture
def sources(monkeypatch):
    data = {
        'indicators': [{'code': 'CSP_CAPEX', 'value': 12, 'history': [1, 12]},
                       {'code': 'TW_MARKET_PE', 'value': 18}],
        'analyses': [{'code': 'NET-LIQUIDITY', 'content': '總經判讀'}],
        'nodes': [{'code': '2330', 'annual': {'direction': 'neutral'}, 'claims': [],
                   'filing': None, 'validation': {}, 'configuration': {'revision': 7, 'holdings': ['private']}}],
        'daily': {'day': '2026-11-19', 'title': '精讀', 'content': '朗讀稿', 'reading': '閱讀版',
                  'sources': ['https://example.com'], 'reviewNote': 'private', 'audio': 'private'},
    }

    async def macro():
        return {'status': 'ready', 'indicators': data['indicators'], 'asOf': '2026-11-19', 'configuration': {'private': True}}

    async def nodes():
        return {'analyses': data['analyses']}

    monkeypatch.setattr(api, 'get_market_macro_dashboard', macro)
    monkeypatch.setattr(api, 'list_macro_node_analyses', nodes)
    monkeypatch.setattr(api, 'benchmark_monitor_view', lambda: {'nodes': data['nodes'], 'holdings': ['private']})
    monkeypatch.setattr(api, 'get_daily_maya_db', lambda: type('DB', (), {
        'published': lambda self, day=None, limit=100: [
            data['daily']] if day in (None, data['daily']['day']) else [],
    })())
    return data


def test_macro_filters_alias_indicator_and_node(call, sources):
    assert call('get_macro_snapshot', {})['structuredContent']['analyses'] == sources['analyses']
    assert call('get_macro_snapshot', {'series': 'csp'})['structuredContent']['indicators'] == [
        {'code': 'CSP_CAPEX', 'value': 12},
    ]
    assert call('get_macro_snapshot', {'series': 'tw_market_pe'})['structuredContent']['indicators'][0]['value'] == 18
    assert call('get_macro_snapshot', {'series': 'net-liquidity'})['structuredContent']['analyses'] == sources['analyses']


def test_benchmark_returns_only_leader_research(call, sources):
    result = call('get_benchmark_monitor', {'code': '2330'})
    assert result['structuredContent']['nodes'] == [
        {key: value for key, value in sources['nodes'][0].items() if key != 'configuration'},
    ]
    assert 'private' not in json.dumps(result)


def test_daily_defaults_to_latest_and_prefers_reading_version(call, sources):
    result = call('get_daily_reading', {})
    assert result == call('get_daily_reading', {'date': '2026-11-19'})
    assert result['structuredContent']['reading'] == '閱讀版'
    assert 'private' not in json.dumps(result)
    sources['daily']['reading'] = None
    assert call('get_daily_reading', {})['structuredContent']['reading'] == '朗讀稿'


@pytest.mark.parametrize(('name', 'missing', 'invalid', 'collection'), [
    ('get_macro_snapshot', {'series': 'MISSING'}, {'series': '../x'}, 'analyses'),
    ('get_benchmark_monitor', {'code': '9999'}, {'code': 2330}, 'nodes'),
    ('get_daily_reading', {'date': '2025-01-01'}, {'date': '2026-02-30'}, 'daily'),
])
def test_tool_missing_invalid_and_oversize(call, sources, name, missing, invalid, collection):
    assert call(name, missing)['structuredContent']['status'] == 'not_found'
    assert call(name, invalid)['isError']
    assert call(name, {'extra': True})['isError']
    target = sources[collection]
    if isinstance(target, list):
        target = target[0]
    key = {'analyses': 'content', 'nodes': 'claims', 'daily': 'reading'}[collection]
    target[key] = '金"\n' * 24000
    result = call(name, {})
    assert result['structuredContent']['truncated'] is True
    assert json.loads(result['content'][0]['text']) == result['structuredContent']
    assert len(json.dumps(result, ensure_ascii=False, separators=(',', ':')).encode()) <= 24000
