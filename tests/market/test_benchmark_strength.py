from datetime import date

import pytest

from maya_sawa.services.benchmark_strength import evaluate_checks, annual_strength, holding_identity


def test_evidence_percentages_keep_missing_and_stale_checks_in_denominator():
    checks = [dict(code='3037', metric='monthly.yoyPercent', period='2026-10',
                   operator='gte', threshold=60, maxAgeDays=60, weight=1)]
    observations = {'3037': {'monthly': {'period': '2026-10', 'yoyPercent': 67.62,
                                        'source': 'MOPS'}}}
    result = evaluate_checks(checks + [{**checks[0], 'code': 'missing'}, {**checks[0], 'code': 'gone'},
                                       {**checks[0], 'code': 'none'}], observations, date(2026, 11, 12))
    assert result['supportPercent'] == 25
    assert result['unknownPercent'] == 75
    assert result['headwindPercent'] == 0
    assert result['counts'] == {'support': 1, 'headwind': 0, 'unknown': 3, 'total': 4}
    assert result['checks'][0]['value'] == 67.62
    observations['3037']['monthly']['period'] = '2025-10'
    assert evaluate_checks(checks, observations, date(2026, 11, 12))['counts']['unknown'] == 1


def test_comparisons_do_not_treat_zero_as_missing_or_future_as_evidence():
    check = dict(code='2330', metric='monthly.yoyPercent', operator='gte', threshold=0,
                 maxAgeDays=60, weight=1)
    data = {'2330': {'monthly': {'period': '2026-10', 'yoyPercent': 0, 'source': 'MOPS'}}}
    assert evaluate_checks([check], data, date(2026, 11, 12))['counts']['support'] == 1
    data['2330']['monthly']['period'] = '2026-12'
    assert evaluate_checks([check], data, date(2026, 11, 12))['counts']['unknown'] == 1


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
        assert evaluate_checks([check], data, date(2026, 11, 12))['counts']['unknown'] == 1


def test_invalid_check_is_rejected_instead_of_silently_scoring():
    with pytest.raises(ValueError):
        evaluate_checks([dict(code='2330', metric='price', operator='gte', threshold=0,
                             maxAgeDays=60, weight=-1)], {}, date(2026, 11, 12))


def test_rule_requires_current_reviewed_page_and_threshold_reason():
    from maya_sawa.services.benchmark_monitor import validate_rule
    claim = dict(report_id='new', page=12, evidence='原始逐字引文')
    check = dict(code='3037', metric='monthly.yoyPercent', operator='gte', threshold=60,
                 maxAgeDays=60, weight=1, reportId='old', page=12,
                 evidence='原始逐字引文', rationale='總營收代理指標，非 AI 訂單直接證據',
                 theme='T1', relation='customer')
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
    assert evaluate_checks([check], data, date(2026, 11, 12))['counts']['headwind'] == 1


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


def test_new_reviewed_report_with_no_claims_does_not_revive_old_positive_claims():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from maya_sawa.services.benchmark_monitor import latest_reviewed_claims
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id='new-reviewed', claims=[])
    assert latest_reviewed_claims(session, '2330', {'sha256': 'pdf'}) == []
    assert session.query.call_count == 1


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


def test_few_checks_show_counts_not_a_percentage():
    """Two checks out of four is not '50% support': below three checks only counts are published."""
    check = dict(code='2330', metric='monthly.yoyPercent', operator='gte', threshold=0, maxAgeDays=60, weight=1)
    data = {'2330': {'monthly': {'period': '2026-10', 'yoyPercent': 5, 'source': 'MOPS'}}}
    result = evaluate_checks([check, {**check, 'code': 'x'}], data, date(2026, 11, 12))
    assert result['supportPercent'] is None and result['unknownPercent'] is None
    assert result['counts'] == {'support': 1, 'headwind': 0, 'unknown': 1, 'total': 2}


def test_checks_belong_to_an_outlook_theme_and_do_not_only_grade_the_company_by_itself():
    from maya_sawa.services.benchmark_monitor import validate_rule
    claim = dict(report_id='r', page=3, evidence='逐字')
    base = dict(metric='monthly.yoyPercent', operator='gte', threshold=10, maxAgeDays=60, weight=1,
                reportId='r', page=3, evidence='逐字', rationale='客戶營收印證上游需求主張')
    own = {**base, 'code': '2330', 'theme': 'T1', 'relation': 'self'}
    with pytest.raises(ValueError, match='theme'):
        validate_rule(dict(code='2330', checks=[{**own, 'theme': ''}], holdings=[]), [claim], {'2330'})
    with pytest.raises(ValueError, match='customer or supplier'):
        validate_rule(dict(code='2330', checks=[own, {**own, 'metric': 'quarterly.grossMarginYoYPp'}], holdings=[]),
                      [claim], {'2330'})
    validate_rule(dict(code='2330', checks=[own, {**base, 'code': 'NVDA-US', 'theme': 'T1', 'relation': 'customer'}],
                       holdings=[]), [claim], {'2330'})


def test_pace_compares_holding_growth_with_its_benchmark_for_the_same_period():
    from maya_sawa.services.benchmark_strength import pace_verdict
    bench = {'monthly': {'period': '2026-10', 'yoyPercent': 20.0}}
    assert pace_verdict({'monthly': {'period': '2026-10', 'yoyPercent': 45.0}}, bench)['verdict'] == 'ahead'
    assert pace_verdict({'monthly': {'period': '2026-10', 'yoyPercent': 5.0}}, bench)['verdict'] == 'behind'
    assert pace_verdict({'monthly': {'period': '2026-10', 'yoyPercent': 25.0}}, bench)['verdict'] == 'inline'
    # different months are not comparable, and missing data is unknown rather than in line
    assert pace_verdict({'monthly': {'period': '2026-09', 'yoyPercent': 45.0}}, bench)['verdict'] == 'unknown'
    assert pace_verdict({}, bench)['verdict'] == 'unknown'
    quarter = pace_verdict({'quarterly': {'period': '2026Q3', 'revenueYoYPercent': 8.0}},
                           {'quarterly': {'period': '2026Q3', 'revenueYoYPercent': 30.0}})
    assert quarter['verdict'] == 'behind' and quarter['gapPp'] == -22.0


def test_attach_pace_fetches_missing_observations_and_skips_self_comparison():
    from maya_sawa.services.benchmark_monitor import attach_pace
    holdings = [{'code': '8996', 'benchmarks': ['2308']}, {'code': '2330', 'benchmarks': ['2330']}]
    fetched = []
    def observe(codes):
        fetched.extend(codes)
        return {'8996': {'monthly': {'period': '2026-10', 'yoyPercent': 60.0}},
                '2308': {'monthly': {'period': '2026-10', 'yoyPercent': 30.0}}}
    attach_pace(holdings, {}, observe)
    assert sorted(fetched) == ['2308', '2330', '8996']
    assert holdings[0]['pace'][0]['benchmark'] == '2308' and holdings[0]['pace'][0]['verdict'] == 'ahead'
    assert holdings[1]['pace'] == []


def test_a_rule_update_that_forgets_an_existing_holding_mapping_is_detected():
    from maya_sawa.services.benchmark_monitor import dropped_holdings
    previous = {'holdings': [{'code': '8996', 'role': 'AI 液冷', 'evidence': 'x'}]}
    assert dropped_holdings(previous, {'holdings': []}) == ['8996']
    assert dropped_holdings(previous, {'holdings': [{'code': '8996'}, {'code': '3017'}]}) == []
    assert dropped_holdings(None, {'holdings': []}) == []
