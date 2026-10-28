import asyncio
import hashlib
import hmac
import time
from urllib.parse import parse_qsl

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.databases.ibkr_research_db import IbkrResearchDatabase
from maya_sawa.services.binance_account import (
    BinanceAccountService, build_snapshot, merge_binance_into_portfolio, sign_query, usdt_prices,
)

# Shapes follow the Binance docs: GET /api/v3/account, POST /sapi/v1/asset/get-funding-asset,
# GET /sapi/v1/asset/wallet/balance?quoteAsset=USDT and GET /api/v3/ticker/price.
SPOT = {"uid": 354937868, "accountType": "SPOT", "canTrade": True, "permissions": ["SPOT"], "balances": [
    {"asset": "BTC", "free": "0.01000000", "locked": "0.00500000"},
    {"asset": "LDUSDT", "free": "100.00000000", "locked": "0.00000000"},  # Simple Earn flexible shows as LD*
    {"asset": "DUST", "free": "3.00000000", "locked": "0.00000000"},      # no USDT/BTC market
    {"asset": "ETH", "free": "0.00000000", "locked": "0.00000000"},
]}
FUNDING = [{"asset": "USDT", "free": "50", "locked": "0", "freeze": "0", "withdrawing": "0", "btcValuation": "0.0006"}]
WALLETS = [{"activate": True, "balance": "1350.00", "walletName": "Spot"},
           {"activate": True, "balance": "50.00", "walletName": "Funding"},
           {"activate": True, "balance": "300.00", "walletName": "Earn"},
           {"activate": False, "balance": "0", "walletName": "USDⓈ-M Futures"}]
PRICES = [{"symbol": "BTCUSDT", "price": "80000.00"}, {"symbol": "ETHUSDT", "price": "2300.00"},
          {"symbol": "SOLBTC", "price": "0.002"}]


def memory_db():
    return IbkrResearchDatabase(create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))


def test_signature_is_hmac_sha256_of_the_exact_query():
    # Example key/secret from the Binance signed-endpoint documentation.
    secret = 'NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j'
    query = sign_query({'symbol': 'LTCBTC', 'side': 'BUY', 'type': 'LIMIT', 'timeInForce': 'GTC', 'quantity': '1',
                        'price': '0.1', 'recvWindow': '5000', 'timestamp': '1499827319559'}, secret)
    assert query.endswith('&signature=c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71')
    payload, signature = query.rsplit('&signature=', 1)
    assert signature == hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def test_prices_cover_usdt_pairs_btc_crosses_and_stablecoins():
    prices = usdt_prices(PRICES)
    assert prices['BTC'] == 80000.0
    assert prices['SOL'] == pytest.approx(160.0)
    assert prices['USDT'] == 1.0 and prices['USDC'] == 1.0


def test_snapshot_values_wallets_positions_and_never_keeps_account_identity():
    snap = build_snapshot(SPOT, FUNDING, WALLETS, usdt_prices(PRICES), 32.0, 'live', '2026-10-28T15:00:00+00:00')
    assert snap['usdt']['total'] == 1700.0
    assert snap['twd']['total'] == 54400.0
    assert snap['usdt']['wallets'] == {'Spot': 1350.0, 'Funding': 50.0, 'Earn': 300.0}
    rows = {(p['asset'], p['wallet']): p for p in snap['positions']}
    assert rows[('BTC', 'Spot')]['quantity'] == 0.015 and rows[('BTC', 'Spot')]['valueUsdt'] == 1200.0
    assert rows[('USDT', 'Earn')]['valueUsdt'] == 100.0  # LDUSDT is Simple Earn USDT
    assert rows[('USDT', 'Funding')]['valueTwd'] == 1600.0
    assert ('ETH', 'Spot') not in rows  # zero balance
    assert snap['unpriced'] == ['DUST']
    # Wallet totals include balances the position list cannot see (e.g. locked Earn); keep the gap explicit.
    assert snap['usdt']['otherWallets'] == 350.0
    assert 'uid' not in str(snap) and '354937868' not in str(snap) and 'permissions' not in str(snap)


def portfolio():
    return {"cashBalance": 100000.0, "totalAssetsEstimated": 500000.0, "totalPnl": 2000.0,
            "summaryFormulas": {"totalAssetsEstimated": "400,000 + 100,000"}, "valuationNote": "Taiwan",
            "regions": {"taiwan": {"cash": 100000.0, "totalAssets": 500000.0, "totalPnl": 2000.0, "leverage": 1.2},
                        "overseas": {"cash": 0, "totalAssets": 0, "totalPnl": 0, "leverage": None},
                        "total": {"cash": 100000.0, "totalAssets": 500000.0, "totalPnl": 2000.0, "leverage": 1.2}}}


def test_merge_adds_crypto_to_total_assets_only_and_adds_a_crypto_region():
    snap = build_snapshot(SPOT, FUNDING, WALLETS, usdt_prices(PRICES), 32.0, 'live', '2026-10-28T15:00:00+00:00')
    merged = merge_binance_into_portfolio(portfolio(), snap)
    assert merged['totalAssetsEstimated'] == 554400.0
    assert merged['cashBalance'] == 100000.0  # stablecoins are not bank cash
    assert merged['totalPnl'] == 2000.0       # no cost basis yet: unknown, never zero-filled
    assert merged['regions']['crypto'] == {'cash': None, 'totalAssets': 54400.0, 'totalPnl': None, 'leverage': None}
    assert merged['regions']['total']['totalAssets'] == 554400.0
    assert merged['summaryFormulas']['totalAssetsEstimated'].endswith('+ Binance 54,400')
    assert merged['binance']['usdt']['total'] == 1700.0
    assert 'Binance' in merged['valuationNote']


def test_merge_with_unknown_total_assets_leaves_it_unknown():
    snap = build_snapshot(SPOT, FUNDING, WALLETS, usdt_prices(PRICES), 32.0, 'live', '2026-10-28T15:00:00+00:00')
    base = {**portfolio(), "totalAssetsEstimated": None}
    assert merge_binance_into_portfolio(base, snap)['totalAssetsEstimated'] is None


def fake_request(calls, fail=None):
    async def request(method, path, params, signed):
        calls.append((method, path, signed))
        if fail and path == fail:
            raise RuntimeError('boom https://api.binance.com/?signature=abc')
        return {'/api/v3/time': {'serverTime': int(time.time() * 1000)}, '/api/v3/account': SPOT,
                '/sapi/v1/asset/get-funding-asset': FUNDING, '/sapi/v1/asset/wallet/balance': WALLETS,
                '/api/v3/ticker/price': PRICES}[path]
    return request


def test_refresh_persists_a_private_snapshot_and_reads_it_back(monkeypatch):
    monkeypatch.setenv('BINANCE_API_KEY', 'k')
    monkeypatch.setenv('BINANCE_API_SECRET', 's')
    monkeypatch.setenv('USD_TWD_RATE', '32')
    calls = []
    service = BinanceAccountService(db=memory_db(), request=fake_request(calls))
    assert asyncio.run(service.refresh_once()) is True
    assert ('GET', '/api/v3/account', True) in calls and ('POST', '/sapi/v1/asset/get-funding-asset', True) in calls
    assert ('GET', '/api/v3/ticker/price', False) in calls
    snap = asyncio.run(service.get_snapshot())
    assert snap['twd']['total'] == 54400.0 and snap['fxSource'] == 'manual'


def test_failed_refresh_keeps_the_last_snapshot_and_hides_the_error_text(monkeypatch, caplog):
    monkeypatch.setenv('BINANCE_API_KEY', 'k')
    monkeypatch.setenv('BINANCE_API_SECRET', 's')
    monkeypatch.setenv('USD_TWD_RATE', '32')
    db = memory_db()
    asyncio.run(BinanceAccountService(db=db, request=fake_request([])).refresh_once())
    failing = BinanceAccountService(db=db, request=fake_request([], fail='/api/v3/account'))
    assert asyncio.run(failing.refresh_once()) is False
    assert asyncio.run(failing.get_snapshot())['twd']['total'] == 54400.0
    assert 'signature=abc' not in caplog.text


def test_service_is_off_without_both_credentials(monkeypatch):
    monkeypatch.setenv('BINANCE_API_KEY', 'k')
    monkeypatch.delenv('BINANCE_API_SECRET', raising=False)
    service = BinanceAccountService(db=memory_db(), request=fake_request([]))
    assert service.enabled is False
    assert asyncio.run(service.get_snapshot()) is None


TRADE_PAGE = [{"symbol": "BTCUSDT", "id": 5, "price": "70000", "qty": "0.015", "quoteQty": "1050", "commission": "0",
               "commissionAsset": "USDT", "time": 1790000000000, "isBuyer": True}]


def cost_request(calls, trades=TRADE_PAGE, converts=None):
    base = fake_request(calls)

    async def request(method, path, params, signed):
        if path == '/api/v3/myTrades':
            calls.append((method, path, dict(params)))
            return [row for row in trades if row['id'] >= params['fromId']]
        if path == '/sapi/v1/convert/tradeFlow':
            calls.append((method, path, dict(params)))
            return {'list': converts or [], 'moreData': False}
        return await base(method, path, params, signed)
    return request


def test_refresh_adds_cost_basis_from_trades_and_fetches_incrementally(monkeypatch):
    monkeypatch.setenv('BINANCE_API_KEY', 'k')
    monkeypatch.setenv('BINANCE_API_SECRET', 's')
    monkeypatch.setenv('USD_TWD_RATE', '32')
    calls = []
    db = memory_db()
    service = BinanceAccountService(db=db, request=cost_request(calls))
    assert asyncio.run(service.refresh_once()) is True
    trade_calls = [c for c in calls if c[1] == '/api/v3/myTrades']
    assert trade_calls == [('GET', '/api/v3/myTrades', {'symbol': 'BTCUSDT', 'fromId': 0, 'limit': 1000})]
    assert len([c for c in calls if c[1] == '/sapi/v1/convert/tradeFlow']) == 13  # one year in 30-day windows
    snap = asyncio.run(service.get_snapshot())
    btc = snap['costBasis']['BTC']
    assert btc['averageCostUsdt'] == 70000.0 and btc['coveredQuantity'] == 0.015
    assert btc['unrealizedPnlUsdt'] == 150.0 and snap['twd']['unrealizedPnl'] == 4800.0

    # Within the hour the stored history is reused; later, only trades after the last id are requested.
    calls.clear()
    asyncio.run(service.refresh_once())
    assert not [c for c in calls if c[1] in ('/api/v3/myTrades', '/sapi/v1/convert/tradeFlow')]
    service._costs_checked = 0.0
    time.sleep(0.01)  # the next convert window must start after the stored end
    asyncio.run(service.refresh_once())
    assert ('GET', '/api/v3/myTrades', {'symbol': 'BTCUSDT', 'fromId': 6, 'limit': 1000}) in calls
    assert len([c for c in calls if c[1] == '/sapi/v1/convert/tradeFlow']) == 1
    assert asyncio.run(service.get_snapshot())['costBasis']['BTC']['events'] == 1  # no duplicate trades


def test_cost_history_failure_keeps_balances(monkeypatch):
    monkeypatch.setenv('BINANCE_API_KEY', 'k')
    monkeypatch.setenv('BINANCE_API_SECRET', 's')
    monkeypatch.setenv('USD_TWD_RATE', '32')
    base = fake_request([])

    async def request(method, path, params, signed):
        if path in ('/api/v3/myTrades', '/sapi/v1/convert/tradeFlow'):
            raise RuntimeError('binance_http_429:-1003:' + path)
        return await base(method, path, params, signed)
    service = BinanceAccountService(db=memory_db(), request=request)
    assert asyncio.run(service.refresh_once()) is True
    snap = asyncio.run(service.get_snapshot())
    assert snap['twd']['total'] == 54400.0
    assert snap['twd']['unrealizedPnl'] is None


def test_merge_adds_known_crypto_pnl_to_total_pnl():
    from maya_sawa.services.binance_costs import apply_cost_basis
    snap = build_snapshot(SPOT, FUNDING, WALLETS, usdt_prices(PRICES), 32.0, 'live', '2026-10-28T15:00:00+00:00')
    snap = apply_cost_basis(snap, {'BTC': {'quantity': 0.015, 'costUsdt': 1050.0, 'realizedPnlUsdt': 0.0, 'events': 1}}, 'now')
    merged = merge_binance_into_portfolio(portfolio(), snap)
    assert merged['totalPnl'] == 2000.0 + 4800.0
    assert merged['regions']['crypto']['totalPnl'] == 4800.0
    assert merged['regions']['total']['totalPnl'] == 6800.0
