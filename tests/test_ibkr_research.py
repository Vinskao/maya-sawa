import asyncio
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.databases.ibkr_research_db import IbkrResearchDatabase
from maya_sawa.services.ibkr_research import normalize_bars, public_quote, IbkrResearchCollector


def test_technical_summary_never_turns_missing_history_into_zero():
    from maya_sawa.services.ibkr_research import technical_summary
    assert technical_summary([])['ma60'] is None
    bars = [{'date': f'2026-{i:03}', 'close': i + 1, 'high': i + 2, 'low': i + .5} for i in range(60)]
    summary = technical_summary(bars)
    assert summary['ma60'] == 30.5
    assert summary['ma5'] == 58
    assert summary['rsi14Wilder'] == 100


def test_real_history_preserves_prices_volume_factor_timezone_and_drops_invalid_bars():
    raw = {'volumeFactor': 40, 'data': [
        {'t': 1792071000000, 'o': 725.86, 'h': 743.97, 'l': 715.58, 'c': 736.72, 'v': 242486.25},
        {'t': 1792071000000, 'o': 0, 'h': 0, 'l': 0, 'c': 0, 'v': 0}]}
    bars = normalize_bars(raw, 'US')
    assert len(bars) == 1
    assert bars[0]['date'] == '2026-10-15'
    assert bars[0]['close'] == 736.72  # OHLC already scaled; do not divide by priceFactor
    assert bars[0]['volume'] == 9699450
    assert bars[0]['rawVolume'] == 242486.25


def test_public_snapshot_handles_prefixes_missing_values_and_strips_account_fields():
    quote = public_quote({'31': 'C 1,234.50', '70': '-', '83': '-2.1%', '87': '2.5M',
                          '6509': 'DpB', '73': 'SECRET POSITION VALUE', '75': 'SECRET PNL'})
    assert quote['close'] == 1234.5
    assert quote['priceType'] == 'previousClose'
    assert quote['high'] is None
    assert quote['changePercent'] == -2.1
    assert quote['volume'] == 2500000
    assert quote['availability'] == 'DpB'
    assert 'SECRET' not in str(quote)


def test_durable_identity_and_failed_refresh_keep_last_success():
    engine = create_engine('sqlite://')
    db = IbkrResearchDatabase(engine=engine)
    db.save('6857', 'JP', 13905743, 'profile', {'company_name': 'ADVANTEST'}, period='2026-10-16')
    db.save('6857', 'TW', 1, 'profile', {'company_name': 'Taiwan company'}, period='2026-10-16')
    db.save('6857', 'JP', 13905743, 'profile', {'error': 'not entitled'}, status='unavailable')
    # A new DB object, without Redis/process memory, sees the last good value.
    replay = IbkrResearchDatabase(engine=engine)
    assert replay.latest('6857', 'JP', 'profile')['payload']['company_name'] == 'ADVANTEST'
    assert replay.latest('6857', 'TW', 'profile')['payload']['company_name'] == 'Taiwan company'
    assert replay.latest('6857', 'JP', 'profile', successful=False)['status'] == 'unavailable'
    assert len(replay.history('6857', 'JP', 'profile')) == 1


def test_due_retries_errors_without_refetching_cached_success():
    db = IbkrResearchDatabase(engine=create_engine('sqlite://'))
    collector = IbkrResearchCollector(db=db)
    db.save('META', 'US', 107113386, 'profile', {'company_name': 'META'})
    assert not collector.due('META', 'US', 'profile', 86400)
    assert collector.due('META', 'US', 'history_raw', 86400)


def test_positions_keep_broker_identity_for_collection():
    from maya_sawa.services.ibkr_market import IbkrMarketService
    rows = IbkrMarketService._build_positions([{'conid': 13905743, 'ticker': '6857', 'name': 'ADVANTEST',
        'assetClass': 'STK', 'currency': 'JPY', 'listingExchange': 'TSEJ', 'position': 1}], {'USD': 32, 'JPY': .2})
    assert rows[0]['conid'] == 13905743
    assert rows[0]['exchange'] == 'TSEJ'


def test_portfolio_survives_redis_loss(monkeypatch):
    import redis
    from maya_sawa.services import ibkr_market
    db = IbkrResearchDatabase(engine=create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False}))
    db.save('ACCOUNT', 'PRIVATE', 0, 'portfolio', {'positions': [{'code': 'META'}]})
    monkeypatch.setenv('IBKR_ENABLED', 'true')
    monkeypatch.setattr(ibkr_market, 'get_ibkr_research_db', lambda: db)
    service = ibkr_market.IbkrMarketService()
    def failed_read(*args):
        raise redis.ConnectionError('offline')
    monkeypatch.setattr(service, '_read_cached_payload', failed_read)
    assert asyncio.run(service.get_snapshot())['positions'][0]['code'] == 'META'


def test_collector_persists_all_three_sources_and_second_pass_uses_db_cache(monkeypatch):
    from maya_sawa.services import ibkr_research
    db = IbkrResearchDatabase(engine=create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False}))
    collector = IbkrResearchCollector(db=db)
    calls = []
    class Response:
        status_code = 200
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, params=None):
            calls.append(url)
            if url.endswith('/info'): return Response({'con_id': 107113386, 'company_name': 'META'})
            if url.endswith('/history'): return Response({'volumeFactor': 40, 'data': [
                {'t': 1792071000000, 'o': 725.86, 'h': 743.97, 'l': 715.58, 'c': 736.72, 'v': 242486.25}]})
            if calls.count(url) == 1: return Response([{'conid': 107113386}])
            return Response([{'conid': 107113386, '31': '736.72', '6509': 'DpB', '73': 'private'}])
    class Gateway:
        _base = 'https://broker/v1/api'
        def _client(self): return Client()
    async def no_sleep(*args): pass
    monkeypatch.setattr(ibkr_research.asyncio, 'sleep', no_sleep)
    positions = [{'code': 'META', 'currency': 'USD', 'conid': 107113386, 'assetClass': 'STK'}]
    asyncio.run(collector.collect(Gateway(), positions))
    assert len(calls) == 4  # profile, history, quote preflight, quote
    saved = collector.read('META', 'US')
    assert len(saved['daily']) == 1
    assert all(saved['datasets'].values())
    assert 'private' not in str(saved)
    asyncio.run(collector.collect(Gateway(), positions))
    assert len(calls) == 4
