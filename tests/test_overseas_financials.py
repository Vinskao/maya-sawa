from maya_sawa.services.overseas_financials import normalize_sec_facts


def test_unchanged_financial_payload_does_not_create_a_new_daily_archive():
    from maya_sawa.services.overseas_financials import financial_content_period
    assert financial_content_period({'a': 1, 'b': 2}) == financial_content_period({'b': 2, 'a': 1})
    assert financial_content_period({'a': 2}) != financial_content_period({'a': 1})


def fact(rows, unit='USD'):
    return {'units': {unit: rows}}


def test_sec_periods_keep_ytd_separate_and_use_latest_restatement():
    def row(value, start='2026-04-01', filed='2026-07-30'):
        return {'val': value, 'start': start, 'end': '2026-06-30', 'filed': filed, 'form': '10-Q', 'accn': 'test', 'fy': 2026, 'fp': 'Q2'}
    raw = {'cik': 1326801, 'entityName': 'Meta Platforms, Inc.', 'facts': {'us-gaap': {
        'RevenueFromContractWithCustomerExcludingAssessedTax': fact([row(100), row(110, filed='2026-08-01'), row(210, start='2026-01-01')]),
        'OperatingIncomeLoss': fact([row(44)]), 'NetIncomeLoss': fact([row(33)]),
        'EarningsPerShareDiluted': fact([row(2.5)], 'USD/shares'),
        'Assets': fact([{'end': '2026-06-30', 'val': 1000, 'filed': '2026-07-30', 'form': '10-Q'}])}}}
    data = normalize_sec_facts(raw)
    assert len(data['quarterly']) == 1
    q = data['quarterly'][0]
    assert q['revenue'] == 110
    assert q['operatingMarginPercent'] == 40
    assert q['netMarginPercent'] == 30
    assert q['epsDiluted'] == 2.5
    assert q['grossMarginPercent'] is None
    assert data['cumulative'][0]['revenue'] == 210
    assert data['balanceSheet'][0]['assets'] == 1000
    assert q['evidence']['revenue']['filed'] == '2026-08-01'


def test_missing_or_zero_revenue_never_creates_fake_margins():
    assert normalize_sec_facts({'facts': {}})['quarterly'] == []
    raw = {'facts': {'us-gaap': {'NetIncomeLoss': fact([
        {'start': '2026-04-01', 'end': '2026-06-30', 'val': -12, 'form': '10-Q', 'filed': '2026-07-30'}])}}}
    q = normalize_sec_facts(raw)['quarterly'][0]
    assert q['netMarginPercent'] is None
    assert q['netIncome'] == -12


def test_lumentum_debt_extinguishment_is_excluded_with_a_normalized_tax():
    """FY2026: GAAP net loss $6.94B from a one-time $7.76B convertible-note extinguishment loss (8-K 2026-08-11)."""
    import json
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / 'fixtures' / 'sec_lite_fy2026_one_time.json').read_text(encoding='utf-8'))
    data = normalize_sec_facts(raw)
    year = next(row for row in data['annual'] if row['end'] == '2026-06-27')
    assert year['netIncome'] == -6935100000 and year['epsDiluted'] == -92.96  # reported figures are kept
    assert year['oneTimeItems'] == -7762500000  # extinguishment -7,756.6M and induced conversion 5.9M
    # Pre-tax -7,172.8M without the one-time items is 589.7M; the $297M tax benefit that came with the charge is
    # replaced by the 21% US federal rate, rather than adding the charge back to after-tax income.
    assert year['netIncomeExcludingOneTime'] == 465863000
    q1 = next(row for row in data['quarterly'] if row['end'] == '2025-09-27')
    assert q1['oneTimeItems'] == -5900000 and q1['netIncomeExcludingOneTime'] == 8769000
    q3 = next(row for row in data['quarterly'] if row['end'] == '2026-03-28')
    assert q3['oneTimeItems'] == 0 and q3['netIncomeExcludingOneTime'] == 144200000  # zero impairment: as reported


def test_one_time_items_need_the_tax_line_to_be_adjusted():
    row = {'start': '2026-01-01', 'end': '2026-03-31', 'filed': '2026-05-01', 'form': '10-Q'}
    q = normalize_sec_facts({'facts': {'us-gaap': {
        'NetIncomeLoss': fact([{**row, 'val': -50}]), 'GoodwillImpairmentLoss': fact([{**row, 'val': 80}])}}})['quarterly'][0]
    assert q['oneTimeItems'] == -80 and q['netIncomeExcludingOneTime'] is None  # no tax line: no guess
    plain = normalize_sec_facts({'facts': {'us-gaap': {'NetIncomeLoss': fact([{**row, 'val': 7}])}}})['quarterly'][0]
    assert 'oneTimeItems' not in plain and plain['netIncomeExcludingOneTime'] == 7


def test_lumentum_including_tax_revenue_tag_is_supported():
    row = {'start': '2025-12-28', 'end': '2026-03-28', 'val': 808400000,
           'filed': '2026-05-06', 'form': '10-Q', 'fy': 2026, 'fp': 'Q3'}
    q = normalize_sec_facts({'facts': {'us-gaap': {
        'RevenueFromContractWithCustomerIncludingAssessedTax': fact([row])}}})['quarterly'][0]
    assert q['revenue'] == 808400000
    assert q['evidence']['revenue']['fp'] == 'Q3'


def test_sec_collection_persists_raw_and_normalized_then_skips_upstream(monkeypatch):
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from maya_sawa.databases.ibkr_research_db import IbkrResearchDatabase
    from maya_sawa.services.ibkr_research import IbkrResearchCollector
    from maya_sawa.services import overseas_financials as source
    calls = []
    raw = {'cik': 1326801, 'entityName': 'META', 'facts': {'us-gaap': {'Revenues': fact([
        {'start': '2026-04-01', 'end': '2026-06-30', 'val': 100, 'filed': '2026-07-30', 'form': '10-Q'}])}}}
    class Response:
        def raise_for_status(self): pass
        def json(self): return raw
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url): calls.append(url); return Response()
    monkeypatch.setattr(source.httpx, 'AsyncClient', Client)
    db = IbkrResearchDatabase(engine=create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False}))
    collector = IbkrResearchCollector(db=db)
    asyncio.run(source.collect_sec_financials(collector, 'META', 'US', 107113386))
    assert db.latest('META', 'US', 'sec_raw')['payload']['cik'] == 1326801
    assert db.latest('META', 'US', 'financials')['payload']['quarterly'][0]['revenue'] == 100
    asyncio.run(source.collect_sec_financials(collector, 'META', 'US', 107113386))
    assert len(calls) == 1


def test_inventory_is_kept_as_a_balance_sheet_instant():
    raw = {'facts': {'us-gaap': {'InventoryNet': fact([{'end': '2026-03-28', 'val': 512300000, 'filed': '2026-05-06', 'form': '10-Q'}])}}}
    assert normalize_sec_facts(raw)['balanceSheet'][0]['inventory'] == 512300000


def test_sec_normalizer_retains_five_years_of_quarters_and_balance_sheets():
    import calendar
    quarterly, assets = [], []
    for index in range(24):
        year, quarter = 2020 + index // 4, index % 4 + 1
        end_month = quarter * 3
        end = f"{year:04d}-{end_month:02d}-{calendar.monthrange(year, end_month)[1]:02d}"
        start_month = end_month - 2
        quarterly.append({'start': f"{year:04d}-{start_month:02d}-01", 'end': end, 'val': 100 + index,
                          'filed': end, 'form': '10-Q', 'fp': f'Q{quarter}'})
        assets.append({'end': end, 'val': 1000 + index, 'filed': end, 'form': '10-Q'})
    data = normalize_sec_facts({'facts': {'us-gaap': {
        'Revenues': fact(quarterly), 'Assets': fact(assets),
    }}})
    assert len(data['quarterly']) == len(data['balanceSheet']) == 20
    assert data['quarterly'][0]['end'] == data['balanceSheet'][0]['end'] == '2021-03-31'
