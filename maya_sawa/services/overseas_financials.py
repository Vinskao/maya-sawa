"""Free official SEC company facts. Preserve original filing periods and units.

Quarterly durations are kept separate from YTD and annual totals; never present
a cumulative nine-month income/cash-flow figure as a single quarter.
"""
from __future__ import annotations

import asyncio
import math
import os
import hashlib
import json
from datetime import date, datetime, timezone

import httpx

SEC_CIK = {'META': '0001326801', 'LITE': '0001633978'}


def financial_content_period(data):
    return 'content-' + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

METRICS = {
    'revenue': ('USD', ['RevenueFromContractWithCustomerExcludingAssessedTax', 'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet', 'SalesRevenueGoodsNet', 'Revenues']),
    'grossProfit': ('USD', ['GrossProfit']),
    'costOfRevenue': ('USD', ['CostOfRevenue', 'CostOfGoodsAndServicesSold']),
    'operatingIncome': ('USD', ['OperatingIncomeLoss']),
    'netIncome': ('USD', ['NetIncomeLoss']),
    'incomeTax': ('USD', ['IncomeTaxExpenseBenefit']),
    'epsDiluted': ('USD/shares', ['EarningsPerShareDiluted']),
    'operatingCashFlow': ('USD', ['NetCashProvidedByUsedInOperatingActivities']),
    'capitalExpenditure': ('USD', ['PaymentsToAcquirePropertyPlantAndEquipment']),
    'assets': ('USD', ['Assets']), 'liabilities': ('USD', ['Liabilities']),
    'equity': ('USD', ['StockholdersEquity']),
    'cash': ('USD', ['CashAndCashEquivalentsAtCarryingValue']),
    'inventory': ('USD', ['InventoryNet']),
    'longTermDebtCurrent': ('USD', ['LongTermDebtCurrent']),
    'longTermDebtNoncurrent': ('USD', ['LongTermDebtNoncurrent']),
}

# Pre-tax items that do not recur, with the sign of their effect on income (a "gain/loss" tag is already signed;
# an expense or impairment tag is reported positive). Restructuring is left in: some companies record it every year.
ONE_TIME_ITEMS = {
    'debtExtinguishmentGainLoss': (1, ['GainsLossesOnExtinguishmentOfDebt']),
    'inducedConversionExpense': (-1, ['InducedConversionOfConvertibleDebtExpense']),
    'goodwillImpairment': (-1, ['GoodwillImpairmentLoss']),
    'intangibleImpairment': (-1, ['ImpairmentOfIntangibleAssetsExcludingGoodwill', 'ImpairmentOfIntangibleAssetsFinitelived']),
    'businessDisposalGainLoss': (1, ['DisposalGroupNotDiscontinuedOperationGainLossOnDisposal']),
}
METRICS.update({key: ('USD', tags) for key, (_, tags) in ONE_TIME_ITEMS.items()})
NORMALIZED_TAX_RATE = 0.21  # US federal statutory rate


def _exclude_one_time(row):
    """Net income without one-time items. A one-time charge usually carries its own tax effect (Lumentum FY2026: a
    $297M benefit with a $7.76B debt-extinguishment loss), so the period's pre-tax income without those items is taxed
    at the statutory rate instead of adding the pre-tax charge back to after-tax income. No tax line: no figure."""
    items = [sign * row[key] for key, (sign, _) in ONE_TIME_ITEMS.items() if row.get(key) is not None]
    net = row.get('netIncome')
    if not items:
        row['netIncomeExcludingOneTime'] = net
        return
    row['oneTimeItems'] = total = sum(items)
    if not total or net is None:
        row['netIncomeExcludingOneTime'] = net
    elif row.get('incomeTax') is None:
        row['netIncomeExcludingOneTime'] = None
    else:
        row['netIncomeExcludingOneTime'] = round((net + row['incomeTax'] - total) * (1 - NORMALIZED_TAX_RATE))


def normalize_sec_facts(raw):
    groups, instants = {}, {}
    facts = raw.get('facts', {}).get('us-gaap', {})
    for metric, (unit, tags) in METRICS.items():
        for priority, tag in enumerate(tags):
            for fact in facts.get(tag, {}).get('units', {}).get(unit, []):
                value = fact.get('val')
                if fact.get('form') not in ('10-Q', '10-K', '10-Q/A', '10-K/A') or not isinstance(value, (int, float)) or not math.isfinite(value):
                    continue
                end, start = fact.get('end'), fact.get('start')
                if not end:
                    continue
                if start:
                    try:
                        duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
                    except ValueError:
                        continue
                    if duration < 60:
                        continue
                    key = (start, end)
                    row = groups.setdefault(key, {'start': start, 'end': end, 'currency': 'USD',
                        'durationDays': duration, 'periodType': 'quarterly' if duration <= 120 else 'annual' if duration >= 330 else 'cumulative', 'evidence': {}})
                else:
                    row = instants.setdefault(end, {'end': end, 'currency': 'USD', 'evidence': {}})
                old = row['evidence'].get(metric, {})
                rank = (fact.get('filed', ''), -priority)
                if old and rank <= (old.get('filed', ''), -old.get('tagPriority', 0)):
                    continue
                row[metric] = value
                row['evidence'][metric] = {k: fact.get(k) for k in ('filed', 'accn', 'form', 'fy', 'fp', 'frame')}
                row['evidence'][metric].update(tag=tag, unit=unit, tagPriority=priority)
    for row in groups.values():
        revenue = row.get('revenue')
        gross = row.get('grossProfit')
        if gross is None and revenue is not None and row.get('costOfRevenue') is not None:
            gross = revenue - row['costOfRevenue']
            row['grossProfit'] = gross
            row['grossProfitCalculated'] = True
        for key, value in [('grossMarginPercent', gross), ('operatingMarginPercent', row.get('operatingIncome')), ('netMarginPercent', row.get('netIncome'))]:
            row[key] = round(value / revenue * 100, 4) if revenue and value is not None else None
        _exclude_one_time(row)
    durations = sorted(groups.values(), key=lambda row: (row['end'], row['start']))
    return {'source': 'SEC EDGAR companyfacts', 'cik': raw.get('cik'), 'company': raw.get('entityName'),
        **{kind: [row for row in durations if row['periodType'] == kind][-12:] for kind in ('quarterly', 'annual', 'cumulative')},
        'balanceSheet': sorted(instants.values(), key=lambda row: row['end'])[-12:],
        'notes': ['All monetary amounts are USD, not millions; EPS is USD/share.',
                  'Calendar end/start and fiscal fy/fp are retained; fiscal years may differ from calendar years.',
                  'Only explicitly reported quarterly durations are shown; missing fourth-quarter facts are not fabricated.',
                  'netIncomeExcludingOneTime removes debt extinguishment, induced conversion, impairments and business '
                  'disposals (oneTimeItems, pre-tax) and applies a 21% tax to that period; other periods are as reported.',
                  'Cash flow may be cumulative YTD and is kept in its own period group. No analyst consensus included.']}


async def collect_sec_financials(collector, code, market, conid):
    if market != 'US' or code not in SEC_CIK or not await asyncio.to_thread(collector.due, code, market, 'financials', 86400):
        return
    cik = SEC_CIK[code]
    url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
    try:
        async with httpx.AsyncClient(timeout=30, headers={'User-Agent': os.getenv('SEC_USER_AGENT',
                'TYMultiverseResearch/1.0 (https://peoplesystem.tatdvsonorth.com)')}) as client:
            response = await client.get(url)
            response.raise_for_status()
            raw = response.json()
        if str(raw.get('cik')).zfill(10) != cik:
            raise ValueError('SEC company identity mismatch')
        data = normalize_sec_facts(raw)
        if not data['quarterly']:
            raise ValueError('No reported quarterly facts')
        data['sourceUrl'] = url
        period = financial_content_period(raw)
        await asyncio.to_thread(collector.db.save, code, market, conid, 'sec_raw', raw, period=period)
        await asyncio.to_thread(collector.db.save, code, market, conid, 'financials', data, period=period)
        collector._read_cache.pop((code, market), None)
    except Exception as exc:
        await asyncio.to_thread(collector.db.save, code, market, conid, 'financials',
            {'reason': type(exc).__name__, 'sourceUrl': url}, status='unavailable')
