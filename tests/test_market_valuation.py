import json
from pathlib import Path

import pytest
from maya_sawa.services.market_history_collector import MarketHistoryCollector, parse_exchange_valuation


def fixture(name):
    return json.loads((Path(__file__).parent / 'fixtures' / name).read_text(encoding='utf-8'))


def test_real_twse_pe_and_loss_making_placeholder():
    rows = parse_exchange_valuation(fixture('twse-pe-20261022.json'))
    assert rows[0]['code'] == '1101'
    assert 'pe_ratio' not in rows[0]['values']
    assert rows[1]['values']['pe_ratio'] == 10.65


def test_real_tpex_fields_and_trimmed_company_name():
    rows = parse_exchange_valuation(fixture('tpex-pe-20261022.json'))
    assert rows[0] == {'code': '1240', 'name': '茂生農經', 'values': {'pe_ratio': 9.98}}


@pytest.mark.parametrize('value', ['-', '.', 'N/A', '', None, '0', '-2', 'NaN', 'Infinity'])
def test_unavailable_or_nonpositive_pe_is_not_plotted(value):
    assert parse_exchange_valuation({'fields': ['證券代號', '證券名稱', '本益比'],
                                     'data': [['2330', '台積電', value]]})[0]['values'] == {}


def test_empty_and_registered_sources():
    assert parse_exchange_valuation({}) == []
    for source in ['twse:valuation', 'tpex:valuation']:
        assert source in MarketHistoryCollector.SOURCES
        assert source in MarketHistoryCollector.SOURCE_CONFIG
        assert MarketHistoryCollector._parse_source(source, {}) == []
