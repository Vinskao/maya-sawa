import copy
import json
from pathlib import Path

import pytest

from maya_sawa.services.market_research import validate_research_content

FIXTURE = Path(__file__).parent / 'fixtures/research_etf_009811.json'


def record():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def validate(data):
    return validate_research_content(json.dumps(data, ensure_ascii=False))


def test_allocation_only_etf_needs_no_company_graph_or_direction():
    data = validate(record())
    assert data['kind'] == 'etf'
    assert 'lean' not in data and 'assessment' not in data and 'technology' not in data
    assert data['allocations'][0]['items'][0]['weightPercent'] == 11.52
    assert data['allocations'][0]['asOf'] != data['allocations'][1]['asOf']


def test_rejects_invalid_etf_review_date():
    data = record()
    data['asOf'] = '2026-02-30'
    with pytest.raises(ValueError): validate(data)


@pytest.mark.parametrize('problem', ['weight', 'nan', 'bool', 'date', 'source', 'duplicate', 'empty', 'coverage', 'dimension'])
def test_rejects_malformed_etf_allocation(problem):
    data = record()
    group = data['allocations'][0]
    if problem == 'weight': group['items'][0]['weightPercent'] = '11.52'
    if problem == 'nan': group['items'][0]['weightPercent'] = float('nan')
    if problem == 'bool': group['items'][0]['weightPercent'] = True
    if problem == 'date': group['asOf'] = '2026-02-30'
    if problem == 'source': group['sourceUrl'] = 'javascript:alert(1)'
    if problem == 'duplicate': group['items'].append(copy.deepcopy(group['items'][0]))
    if problem == 'empty': group['items'] = []
    if problem == 'coverage': group['coverage'] = 'unknown'
    if problem == 'dimension': group['dimension'] = 'not-a-dimension'
    with pytest.raises(ValueError): validate(data)


def test_keeps_leverage_and_negative_exposure_without_creating_fake_remainder():
    data = record()
    data['allocations'][2]['items'] = [{'name': 'Long', 'weightPercent': 150}, {'name': 'Hedge', 'weightPercent': -20}]
    assert validate(data)['allocations'][2]['items'] == data['allocations'][2]['items']


def test_theme_requires_an_explicit_theme_and_valid_research():
    data = record()
    data['theme'] = '電動車'
    with pytest.raises(ValueError): validate(data)
    data['themeResearch'] = json.loads((Path(__file__).parents[1] / 'maya_sawa/data/market_research/2330.json').read_text(encoding='utf-8'))
    assert validate(data)['theme'] == '電動車'
    del data['theme']
    with pytest.raises(ValueError): validate(data)
