from maya_sawa.services.overseas_financials import normalize_sec_facts


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
