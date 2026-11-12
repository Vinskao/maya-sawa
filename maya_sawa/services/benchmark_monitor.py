"""Live benchmark evidence view, rebuilt from the current portfolio and reviewed rules."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .benchmark_strength import annual_strength, evaluate_checks, holding_identity, validate_check

SCHEMA = """CREATE TABLE IF NOT EXISTS benchmark_monitor_rule (
    code TEXT PRIMARY KEY, definition JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""


def validate_rule(rule, claims, companies):
    if rule.get('code') not in companies or not isinstance(rule.get('checks'), list) or len(rule['checks']) > 20:
        raise ValueError('Unknown benchmark or invalid checks')
    if not isinstance(rule.get('holdings'), list) or len(rule['holdings']) > 50:
        raise ValueError('Holdings mapping required')
    for mapping in rule['holdings']:
        if not all(isinstance(mapping.get(key), str) and mapping[key].strip() for key in ('code', 'role', 'evidence')):
            raise ValueError('Holding mapping needs identity, role and evidence')
    evaluate_checks(rule['checks'], {}, datetime.now(ZoneInfo('Asia/Taipei')).date())
    for check in rule['checks']:
        validate_check(check)
        if not any(check.get('reportId') == claim['report_id'] and check.get('page') == claim['page']
                   and check.get('evidence') == claim['evidence'] for claim in claims):
            raise ValueError('Check must cite a reviewed claim from the latest annual report')
        if not isinstance(check.get('rationale'), str) or not check['rationale'].strip():
            raise ValueError('Explain threshold and direction; proxy checks are not direct causal proof')


def snapshot(engine, portfolio_db, reports_db, observations=None):
    from maya_sawa.benchmark_versions import VERSIONS, members
    from maya_sawa.benchmark_evidence import PROFILE, UPLOADER

    lineup = members(VERSIONS[-1])
    with engine.connect() as connection:
        filings = connection.execute(text("""SELECT DISTINCT ON (code) code, sha256, fiscal_year,
            source_url, analysis_status FROM benchmark_filing WHERE kind='F'
            ORDER BY code, fiscal_year DESC, collected_at DESC""")).mappings().all()
        rules = {row['code']: row['definition'] for row in connection.execute(text(
            'SELECT code, definition FROM benchmark_monitor_rule')).mappings()}
    latest = {row['code']: dict(row) for row in filings}
    claims_by_code = {}
    with reports_db.sessions() as session:
        from maya_sawa.databases.market_reports_db import MarketReport, MarketReportClaim
        for code, filing in latest.items():
            rows = []
            for profile in (PROFILE, 'benchmark-evidence-v1'):
                digest = hashlib.sha256(f"{profile}:{code}:{filing['sha256']}".encode()).hexdigest()
                rows = session.query(MarketReportClaim, MarketReport).join(MarketReport).filter(
                    MarketReport.sha256 == digest, MarketReport.uploaded_by == UPLOADER,
                    MarketReport.status == 'ready', MarketReport.visibility == 'public').all()
                if rows:
                    break
            claims_by_code[code] = [dict(report_id=report.id, page=claim.page, evidence=claim.evidence,
                claim=claim.claim, direction=claim.direction, dimension=claim.dimension,
                source=filing['source_url'], year=filing['fiscal_year']) for claim, report in rows]
    portfolio = portfolio_db.latest_auto()
    holdings = [{ 'code': holding_identity(row), 'name': row.get('name', ''), 'role': '尚未定位'}
                for row in portfolio['positions'] if row.get('productType') == 'stock']
    today = datetime.now(ZoneInfo('Asia/Taipei')).date()
    nodes = []
    for company in lineup:
        code = company['code']
        claims = claims_by_code.get(code, [])
        rule = rules.get(code, {'code': code, 'checks': [], 'holdings': []})
        try:
            validate_rule(rule, claims, {item['code'] for item in lineup})
        except ValueError:
            rule = {'checks': [], 'holdings': []}
        validation = evaluate_checks(rule['checks'], observations or {}, today)
        for holding in holdings:
            mapping = next((item for item in rule['holdings'] if item['code'] == holding['code']), None)
            if mapping:
                holding['role'] = mapping['role']
                holding.setdefault('benchmarks', []).append(code)
            if holding['code'] == code:
                holding['role'] = company['segment']
                holding.setdefault('benchmarks', []).append(code)
        nodes.append({'code': code, 'annual': annual_strength(claims), 'claims': claims,
                      'filing': latest.get(code), 'validation': validation,
                      'configuration': {'checks': rule['checks'], 'holdings': rule['holdings']}})
    content = {'nodes': nodes, 'holdings': holdings, 'holdingsSnapshotAt': portfolio['snapshotAt']}
    revision = hashlib.sha256(json.dumps(content, sort_keys=True, default=str).encode()).hexdigest()[:16]
    return {**content, 'revision': revision, 'generatedAt': datetime.now(ZoneInfo('Asia/Taipei')).isoformat(),
            'method': '順風與逆風為已審核驗證條件的加權符合／不符占比，未知保留在分母，並非報酬率或機率。'}


def current_observations(codes):
    from .market_fundamentals import market_fundamentals_service, MarketFundamentalsService, build_fundamental_metrics
    result = {}
    for code in codes:
        if '-' in code:
            from .ibkr_research import ibkr_research_collector
            from .market_brief import summarize_overseas
            symbol, market = code.rsplit('-', 1)
            try:
                payload = ibkr_research_collector.read(symbol, market)
                financials = payload.get('financials') or ((payload.get('datasets') or {}).get('financials') or {}).get('payload') or {}
                payload = {**payload, 'financials': financials}
                quarterly = (summarize_overseas(symbol, market, payload).get('fundamentals') or {}).get('latestQuarter')
                source = financials.get('source')
                result[code] = {'quarterly': {**quarterly, 'source': source}} if quarterly and source else {}
            except (ValueError, RuntimeError):
                result[code] = {}
            continue
        if not code.isdigit() or len(code) != 4:
            continue
        monthly, income = market_fundamentals_service.cached_official(code)
        history = MarketFundamentalsService._finmind_history(code)
        metrics = build_fundamental_metrics(monthly, income, history)
        current = {}
        for group in ('monthly', 'quarterly'):
            rows = metrics.get(group) or []
            if rows:
                current[group] = {**rows[-1], 'source': 'TWSE / MOPS persisted fundamentals'}
                if group == 'quarterly':
                    for target, source in {'revenueYoYPercent': 'revenueYoY', 'grossMarginPercent': 'grossMargin',
                                           'grossMarginYoYPp': 'grossMarginYoY',
                                           'operatingMarginPercent': 'operatingMargin'}.items():
                        current[group][target] = rows[-1].get(source)
        if market_fundamentals_service._stale_sources:
            current = {}
        result[code] = current
    return result
