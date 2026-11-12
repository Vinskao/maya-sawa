"""Traceable annual direction and deterministic verification of reviewed hypotheses."""
from calendar import monthrange
from datetime import date
from math import isfinite

METRICS = {'monthly.yoyPercent', 'quarterly.revenueYoYPercent', 'quarterly.grossMarginPercent',
           'quarterly.grossMarginYoYPp', 'quarterly.operatingMarginPercent'}


def holding_identity(holding):
    code = str(holding['code']).upper()
    market = str(holding.get('market') or 'TW').upper()
    return code if market == 'TW' else f'{code}-{market}'


def annual_strength(claims):
    counts = {kind: sum(row.get('direction') == kind for row in claims)
              for kind in ('tailwind', 'headwind', 'neutral')}
    active = [kind for kind, count in counts.items() if count]
    return {'direction': active[0] if len(active) == 1 else 'mixed' if active else 'unknown',
            'counts': counts, 'claimCount': len(claims)}


def position_from_groups(holdings, groups, benchmark_codes):
    for holding in holdings:
        if holding['role'] != '尚未定位':
            continue
        roles, related = [], set()
        for group in groups:
            member = next((row for row in group.get('members', []) if row.get('recordCode') == holding['code']), None)
            if member and member.get('role'):
                roles.append(f"{group['name']['zh']}・{member['role']}")
                related.update(row['recordCode'] for row in group['members'] if row['recordCode'] in benchmark_codes)
        if roles:
            holding['role'] = '；'.join(roles)
            holding['benchmarks'] = sorted(related)
            holding['positionSource'] = '既有產業分組，非供貨證據'


MIN_CHECKS_FOR_PERCENT = 3


def finite(value):
    return type(value) in (int, float) and isfinite(value)


def validate_check(check):
    if (check.get('metric') not in METRICS or check.get('operator') not in {'gte', 'lte'}
            or not finite(check.get('threshold')) or not finite(check.get('weight'))
            or not 0 < check['weight'] <= 100 or type(check.get('maxAgeDays')) is not int
            or not 1 <= check['maxAgeDays'] <= 550 or not isinstance(check.get('code'), str)
            or not check['code']):
        raise ValueError('Invalid benchmark check: metric, operator, threshold, weight, code and age required')


def evaluate_checks(checks, observations, today):
    totals = {'support': 0, 'headwind': 0, 'unknown': 0}
    results = []
    seen = set()
    for check in checks:
        validate_check(check)
        identity = (check['code'], check['metric'])
        if identity in seen:
            raise ValueError('Duplicate instrument metric would double count evidence')
        seen.add(identity)
        group, metric = check['metric'].split('.')
        row = observations.get(check['code'], {}).get(group) or {}
        value, period = row.get(metric), row.get('period')
        valid = finite(value) and bool(row.get('source'))
        try:
            if len(str(period)) == 6 and str(period)[4] == 'Q':
                year, quarter = int(period[:4]), int(period[5])
                if not 1 <= quarter <= 4:
                    raise ValueError('Invalid quarter')
                month = quarter * 3
                period_day = date(year, month, monthrange(year, month)[1])
            elif len(str(period)) == 7:
                year, month = map(int, period.split('-'))
                period_day = date(year, month, monthrange(year, month)[1])
            else:
                period_day = date.fromisoformat(str(period))
            valid = valid and 0 <= (today - period_day).days <= check['maxAgeDays']
        except (ValueError, TypeError):
            valid = False
        outcome = 'unknown'
        if valid:
            supported = value >= check['threshold'] if check['operator'] == 'gte' else value <= check['threshold']
            outcome = 'support' if supported else 'headwind'
        totals[outcome] += check['weight']
        results.append({**check, 'value': value if finite(value) else None, 'period': period,
                        'source': row.get('source'), 'outcome': outcome})
    denominator = sum(totals.values())
    counts = {key: sum(1 for item in results if item['outcome'] == key) for key in totals}
    # With one or two checks a percentage reads as far more certain than it is; publish the counts instead.
    shown = denominator and len(results) >= MIN_CHECKS_FOR_PERCENT
    return {**{key + 'Percent': round(value / denominator * 100, 2) if shown else None
               for key, value in totals.items()}, 'counts': {**counts, 'total': len(results)}, 'checks': results,
            'method': 'weighted-evidence-v1', 'denominator': denominator}
