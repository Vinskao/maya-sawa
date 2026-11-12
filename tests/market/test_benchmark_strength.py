from datetime import date

import pytest

from maya_sawa.services.benchmark_strength import evaluate_checks, annual_strength, holding_identity


def test_evidence_percentages_keep_missing_and_stale_checks_in_denominator():
    checks = [dict(code='3037', metric='monthly.yoyPercent', period='2026-10',
                   operator='gte', threshold=60, maxAgeDays=60, weight=1)]
    observations = {'3037': {'monthly': {'period': '2026-10', 'yoyPercent': 67.62,
                                        'source': 'MOPS'}}}
    result = evaluate_checks(checks + [{**checks[0], 'code': 'missing'}], observations, date(2026, 11, 12))
    assert result['supportPercent'] == 50
    assert result['unknownPercent'] == 50
    assert result['headwindPercent'] == 0
    assert result['checks'][0]['value'] == 67.62
    observations['3037']['monthly']['period'] = '2025-10'
    assert evaluate_checks(checks, observations, date(2026, 11, 12))['unknownPercent'] == 100


def test_comparisons_do_not_treat_zero_as_missing_or_future_as_evidence():
    check = dict(code='2330', metric='monthly.yoyPercent', operator='gte', threshold=0,
                 maxAgeDays=60, weight=1)
    data = {'2330': {'monthly': {'period': '2026-10', 'yoyPercent': 0, 'source': 'MOPS'}}}
    assert evaluate_checks([check], data, date(2026, 11, 12))['supportPercent'] == 100
    data['2330']['monthly']['period'] = '2026-12'
    assert evaluate_checks([check], data, date(2026, 11, 12))['unknownPercent'] == 100


def test_unknown_is_not_neutral_and_annual_directions_are_not_current_validation():
    assert annual_strength([])['direction'] == 'unknown'
    assert annual_strength([{'direction': 'tailwind'}, {'direction': 'headwind'}])['direction'] == 'mixed'
    result = evaluate_checks([], {}, date(2026, 11, 12))
    assert result['supportPercent'] is None
    assert result['headwindPercent'] is None


def test_identity_and_nonfinite_or_untraceable_observations():
    assert holding_identity({'code': '6857', 'market': 'JP'}) == '6857-JP'
    assert holding_identity({'code': '6857', 'market': 'TW'}) == '6857'
    check = dict(code='2330', metric='monthly.yoyPercent', operator='gte', threshold=0,
                 maxAgeDays=60, weight=1)
    for value in [None, float('nan'), True]:
        data = {'2330': {'monthly': {'period': '2026-10', 'yoyPercent': value, 'source': 'MOPS'}}}
        assert evaluate_checks([check], data, date(2026, 11, 12))['unknownPercent'] == 100


def test_invalid_check_is_rejected_instead_of_silently_scoring():
    with pytest.raises(ValueError):
        evaluate_checks([dict(code='2330', metric='price', operator='gte', threshold=0,
                             maxAgeDays=60, weight=-1)], {}, date(2026, 11, 12))


def test_rule_requires_current_reviewed_page_and_threshold_reason():
    from maya_sawa.services.benchmark_monitor import validate_rule
    claim = dict(report_id='new', page=12, evidence='原始逐字引文')
    check = dict(code='3037', metric='monthly.yoyPercent', operator='gte', threshold=60,
                 maxAgeDays=60, weight=1, reportId='old', page=12,
                 evidence='原始逐字引文', rationale='總營收代理指標，非 AI 訂單直接證據')
    rule = dict(code='2330', checks=[check], holdings=[])
    with pytest.raises(ValueError, match='latest annual'):
        validate_rule(rule, [claim], {'2330'})
    check['reportId'] = 'new'
    validate_rule(rule, [claim], {'2330'})
    check['rationale'] = ''
    with pytest.raises(ValueError, match='threshold'):
        validate_rule(rule, [claim], {'2330'})


def test_quarterly_units_and_periods_are_kept_separate():
    check = dict(code='2330', metric='quarterly.grossMarginYoYPp', operator='gte', threshold=2,
                 maxAgeDays=180, weight=1)
    data = {'2330': {'quarterly': {'period': '2026Q3', 'grossMarginYoYPp': 1.5, 'source': 'MOPS'}}}
    assert evaluate_checks([check], data, date(2026, 11, 12))['headwindPercent'] == 100


def test_live_snapshot_changes_on_portfolio_updates_without_leaking_account_values():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from maya_sawa.services.benchmark_monitor import snapshot
    engine = MagicMock()
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.mappings.return_value.all.return_value = []
    connection.execute.return_value.mappings.return_value.__iter__.return_value = iter([])
    reports = MagicMock()
    portfolio = MagicMock()
    portfolio.latest_auto.return_value = {'snapshotAt': '2026-11-12T00:00:00Z', 'positions': [
        {'code': '6857', 'market': 'JP', 'name': '愛德萬', 'productType': 'stock',
         'quantity': 100, 'marketValue': 100000},
        {'code': 'BTC', 'market': 'CRYPTO', 'name': 'BTC', 'productType': 'crypto'}]}
    first = snapshot(engine, portfolio, reports)
    assert [row['code'] for row in first['holdings']] == ['6857-JP']
    assert 'quantity' not in str(first) and 'marketValue' not in str(first)
    assert all(row['annual']['direction'] == 'unknown' for row in first['nodes'])
    portfolio.latest_auto.return_value = {'snapshotAt': '2026-11-12T00:01:00Z', 'positions': []}
    second = snapshot(engine, portfolio, reports)
    assert second['holdings'] == []
    assert second['revision'] != first['revision']


def test_duplicate_metrics_cannot_inflate_evidence_percentage():
    check = dict(code='2330', metric='monthly.yoyPercent', operator='gte', threshold=0,
                 maxAgeDays=60, weight=1)
    with pytest.raises(ValueError, match='double count'):
        evaluate_checks([check, check], {}, date(2026, 11, 12))


def test_existing_industry_roles_position_holdings_without_inventing_supply_relationships():
    from maya_sawa.services.benchmark_strength import position_from_groups
    groups = [{'name': {'zh': '測試設備'}, 'members': [
        {'recordCode': '6857-JP', 'role': '半導體測試機'},
        {'recordCode': '2330', 'role': '晶圓代工'}]}]
    held = [{'code': '6857-JP', 'role': '尚未定位'}, {'code': '6857', 'role': '尚未定位'}]
    position_from_groups(held, groups, {'2330'})
    assert held[0]['role'] == '測試設備・半導體測試機'
    assert held[0]['benchmarks'] == ['2330']
    assert held[0]['positionSource'] == '既有產業分組，非供貨證據'
    assert held[1]['role'] == '尚未定位'


@pytest.mark.parametrize('nested', [False, True])
def test_overseas_verification_reads_the_correct_market_without_taiwan_fallback(monkeypatch, nested):
    from maya_sawa.services import benchmark_monitor, ibkr_research
    calls = []
    def read(code, market):
        calls.append((code, market))
        financials = {'source': 'SEC EDGAR companyfacts', 'quarterly': [
            {'end': '2025-09-30', 'revenue': 100, 'grossMarginPercent': 40},
            {'end': '2026-09-30', 'revenue': 120, 'grossMarginPercent': 42}]}
        return {'datasets': {'financials': {'payload': financials}}} if nested else {'financials': financials}
    monkeypatch.setattr(ibkr_research.ibkr_research_collector, 'read', read)
    result = benchmark_monitor.current_observations({'NVDA-US'})
    assert calls == [('NVDA', 'US')]
    assert result['NVDA-US']['quarterly']['revenueYoYPercent'] == 20
    assert result['NVDA-US']['quarterly']['grossMarginYoYPp'] == 2
