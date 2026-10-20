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
    assert public_quote({'31': '740.70', '70': '0.00', '71': '0.00'})['high'] is None


def test_dashboard_uses_persisted_quote_and_keeps_delay_and_source_time():
    from maya_sawa.services.ibkr_research import dashboard_quote
    quote = dashboard_quote({'code': 'META', 'name': 'META', 'lastPrice': 741.49, 'currency': 'USD'},
        '2026-10-16T11:00:00Z', {'fetchedAt': '2026-10-16T11:00:00Z', 'payload': {
            'close': 740.7, 'change': 3.98, 'changePercent': .54, 'high': None, 'low': None,
            'volume': 53311, 'availability': 'DPB', 'sourceUpdatedAt': 1792149084224}})
    assert quote['close'] == 740.7
    assert quote['availability'] == 'DPB'
    assert quote['changePercent'] == .54
    assert quote['high'] is None
    assert quote['timestamp'] != quote['fetchedAt']


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


def test_failed_attempts_are_retried_at_once_when_the_session_comes_back():
    db = IbkrResearchDatabase(engine=create_engine('sqlite://'))
    collector = IbkrResearchCollector(db=db)
    db.save('META', 'US', 107113386, 'history_raw', {'reason': 'HTTPStatusError'}, status='unavailable')
    db.save('META', 'US', 107113386, 'profile', {'company_name': 'META'})
    assert not collector.due('META', 'US', 'history_raw', 6 * 3600)  # normal backoff after an error
    assert collector.due('META', 'US', 'history_raw', 6 * 3600, retry_failed=True)
    assert not collector.due('META', 'US', 'profile', 86400, retry_failed=True)  # successes keep their cache


class GatewayResponse:
    def __init__(self, data, status_code=200):
        self.data, self.status_code = data, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.data


def test_market_data_session_is_recorded_from_gateway_auth_status(monkeypatch):
    from maya_sawa.services import ibkr_market
    db = IbkrResearchDatabase(engine=create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False}))
    monkeypatch.setattr(ibkr_market, 'get_ibkr_research_db', lambda: db)
    # Real /iserver/auth/status payload on 2026-10-20 (portfolio reads were still 200), then after a login.
    replies = iter([{'authenticated': False, 'established': False, 'competing': False, 'connected': False, 'MAC': 'b6:ee:b9:42:b1:78'},
                    {'authenticated': True, 'established': True, 'competing': False, 'connected': True, 'MAC': 'b6:ee:b9:42:b1:78'},
                    {'authenticated': True, 'established': True, 'competing': False, 'connected': True, 'MAC': 'b6:ee:b9:42:b1:78'}])
    posted = []

    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url):
            posted.append(url)
            return GatewayResponse(next(replies))

    service = ibkr_market.IbkrMarketService()
    monkeypatch.setattr(service, '_client', lambda: Client())
    assert asyncio.run(service.market_data_session()) == (False, False)
    assert db.latest('ACCOUNT', 'PRIVATE', 'iserver_session') is None
    assert asyncio.run(service.market_data_session()) == (True, True)  # live again: retry failed fetches now
    assert asyncio.run(service.market_data_session()) == (True, False)
    assert posted[0].endswith('/iserver/auth/status')
    assert 'MAC' not in str(db.latest('ACCOUNT', 'PRIVATE', 'iserver_session'))


def test_refresh_skips_market_data_while_logged_out_and_catches_up_after_login(monkeypatch):
    from maya_sawa.services import ibkr_market, market_automation
    service = ibkr_market.IbkrMarketService()
    collected, checks = [], []
    sessions = iter([(False, False), (True, True)])

    async def refreshed(): return True
    async def snapshot(): return {'positions': [{'code': 'META'}]}
    async def session(): return next(sessions)
    async def collect(gateway, positions, retry_failed=False): collected.append(retry_failed)
    async def check(store, source): checks.append(1)

    monkeypatch.setattr(service, 'refresh_cache_now', refreshed)
    monkeypatch.setattr(service, 'get_snapshot', snapshot)
    monkeypatch.setattr(service, 'market_data_session', session)
    monkeypatch.setattr(ibkr_market.ibkr_research_collector, 'collect', collect)
    monkeypatch.setattr(market_automation, 'check', check)
    monkeypatch.setattr(market_automation, 'automation_store', lambda: None)
    monkeypatch.setattr(market_automation, 'IbkrSource', lambda: None)
    asyncio.run(service.refresh_once())
    assert collected == []  # no /iserver calls that can only fail
    asyncio.run(service.refresh_once())
    assert collected == [True]
    assert len(checks) == 2  # routines are checked either way, so the status (and login prompt) stays current


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
    from maya_sawa.services import overseas_financials
    monkeypatch.setattr(overseas_financials, 'collect_sec_financials', no_sleep)
    positions = [{'code': 'META', 'currency': 'USD', 'conid': 107113386, 'assetClass': 'STK'}]
    asyncio.run(collector.collect(Gateway(), positions))
    assert len(calls) == 4  # profile, history, quote preflight, quote
    saved = collector.read('META', 'US')
    assert len(saved['daily']) == 1
    assert all(saved['datasets'][kind] for kind in ('profile', 'quote', 'history_raw'))
    assert 'private' not in str(saved)
    asyncio.run(collector.collect(Gateway(), positions))
    assert len(calls) == 4


def test_shioaji_background_refresh_keeps_overseas_selection_without_mutating_taiwan_source(monkeypatch):
    from maya_sawa.services.shioaji_market import ShioajiMarketService
    from maya_sawa.services.ibkr_market import ibkr_market_service
    from maya_sawa.databases.market_dashboard_db import market_dashboard_db
    from maya_sawa.databases.portfolio_history_db import portfolio_history_db
    service = ShioajiMarketService()
    payload = {'balanceAvailable': True, 'fetchedAt': '2026-10-16T11:00:00Z', 'cashBalance': 10,
               'totalAssetsEstimated': 100, 'totalPnl': 0, 'positions': []}
    async def fetch(*args): return payload
    async def ibkr(): return {'positions': [{'code': 'META', 'assetClass': 'STK', 'currency': 'USD'}],
        'twd': {'cashBalance': 0, 'netLiquidation': 10, 'grossPositionValue': 10, 'unrealizedPnl': 0},
        'usd': {'netLiquidation': 10, 'grossPositionValue': 10}, 'usdTwdRate': 32}
    recorded = []
    monkeypatch.setattr(service, '_run_with_relogin', fetch)
    monkeypatch.setattr(service, '_read_cached_payload', lambda *args: {'symbol': 'TXF'})
    monkeypatch.setattr(service, '_write_cached_payload', lambda *args: None)
    monkeypatch.setattr(ibkr_market_service, 'get_snapshot', ibkr)
    monkeypatch.setattr(portfolio_history_db, 'record_taiwan', lambda *args: None)
    monkeypatch.setattr(market_dashboard_db, 'record_portfolio', lambda value, *args: recorded.append(value))
    assert asyncio.run(service._refresh_payload('PORTFOLIO', None))
    assert recorded[0]['ibkr']['positions'][0]['code'] == 'META'
    assert 'ibkr' not in payload
