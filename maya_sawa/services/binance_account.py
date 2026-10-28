"""Read-only Binance balances folded into the owner's portfolio (phase 2).

Uses a key with "Enable Reading" only (BINANCE_API_KEY / BINANCE_API_SECRET);
off when either is unset. A background loop values spot (including Simple Earn
flexible, shown as LD* assets) and funding balances in USDT, takes per-wallet
totals from /sapi/v1/asset/wallet/balance, converts to NT$, and persists one
private snapshot (code BINANCE, market PRIVATE) that has no public API.
Account identifiers (uid, permissions) are never stored. Cost basis and P/L
are phase 3, so crypto P/L stays unknown rather than zero.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from .binance_market import API_BASE, BinanceRegionRestricted

logger = logging.getLogger(__name__)

STABLECOINS = {'USDT': 1.0, 'USDC': 1.0, 'FDUSD': 1.0, 'TUSD': 1.0, 'USDP': 1.0, 'DAI': 1.0}
NAMES = {'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana', 'BNB': 'BNB', 'XRP': 'XRP', 'USDT': 'Tether',
         'USDC': 'USD Coin'}
REFRESH_SECONDS = 300
RECV_WINDOW = 10000
_FX_FALLBACK_USD_TWD = 31.5


def _number(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def sign_query(params: dict, secret: str) -> str:
    query = urlencode(params)
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f'{query}&signature={signature}'


def usdt_prices(tickers: list[dict]) -> dict[str, float]:
    """USDT price per asset: direct USDT pair, else via BTC, plus stablecoins at 1."""
    pairs = {row.get('symbol'): _number(row.get('price')) for row in tickers if isinstance(row, dict)}
    prices = dict(STABLECOINS)
    btc = pairs.get('BTCUSDT', 0.0)
    for symbol, price in pairs.items():
        if price <= 0:
            continue
        if symbol.endswith('USDT'):
            prices.setdefault(symbol[:-4], price)
    for symbol, price in pairs.items():
        if price > 0 and btc > 0 and symbol.endswith('BTC'):
            prices.setdefault(symbol[:-3], price * btc)
    return prices


def build_snapshot(spot: dict, funding: list[dict], wallets: list[dict], prices: dict[str, float],
                   usd_twd: float, fx_source: str, fetched_at: str) -> dict[str, Any]:
    holdings: dict[tuple[str, str], float] = {}
    for row in spot.get('balances', []):
        asset = str(row.get('asset') or '')
        quantity = _number(row.get('free')) + _number(row.get('locked'))
        if not asset or quantity <= 0:
            continue
        # Simple Earn flexible balances appear in spot as LD<asset>.
        key = (asset[2:], 'Earn') if asset.startswith('LD') and len(asset) > 2 else (asset, 'Spot')
        holdings[key] = holdings.get(key, 0.0) + quantity
    for row in funding:
        asset = str(row.get('asset') or '')
        quantity = sum(_number(row.get(field)) for field in ('free', 'locked', 'freeze', 'withdrawing'))
        if asset and quantity > 0:
            holdings[(asset, 'Funding')] = holdings.get((asset, 'Funding'), 0.0) + quantity
    positions, unpriced = [], []
    for (asset, wallet), quantity in sorted(holdings.items()):
        price = prices.get(asset)
        if not price:
            unpriced.append(asset)
            continue
        value = quantity * price
        positions.append({'asset': asset, 'name': NAMES.get(asset, asset), 'wallet': wallet,
                          'quantity': round(quantity, 10), 'priceUsdt': price, 'valueUsdt': round(value, 2),
                          'valueTwd': round(value * usd_twd, 2)})
    positions.sort(key=lambda p: -p['valueUsdt'])
    wallet_totals = {str(row.get('walletName')): round(_number(row.get('balance')), 2)
                     for row in wallets if _number(row.get('balance')) > 0}
    positions_usdt = round(sum(p['valueUsdt'] for p in positions), 2)
    # The wallet endpoint covers every wallet (locked Earn, futures, bots); positions only spot/funding/flexible.
    total = round(sum(wallet_totals.values()), 2) if wallet_totals else positions_usdt
    other = round(max(total - positions_usdt, 0.0), 2)
    return {'source': 'Binance', 'quoteAsset': 'USDT', 'fetchedAt': fetched_at,
            'usdTwdRate': usd_twd, 'fxSource': fx_source,
            'usdt': {'total': total, 'positions': positions_usdt, 'otherWallets': other, 'wallets': wallet_totals},
            'twd': {'total': round(total * usd_twd, 2), 'positions': round(positions_usdt * usd_twd, 2),
                    'otherWallets': round(other * usd_twd, 2)},
            'positions': positions, 'unpriced': sorted(set(unpriced))}


def merge_binance_into_portfolio(portfolio: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    """Add Binance (NT$) to total assets and a `crypto` region; cash and P/L stay as they are."""
    crypto_twd = snapshot['twd']['total']
    if portfolio.get('totalAssetsEstimated') is not None:
        portfolio['totalAssetsEstimated'] = round(portfolio['totalAssetsEstimated'] + crypto_twd, 2)
    regions = portfolio.setdefault('regions', {})
    regions['crypto'] = {'cash': None, 'totalAssets': crypto_twd, 'totalPnl': None, 'leverage': None}
    if 'total' in regions:
        regions['total'] = {**regions['total'], 'totalAssets': portfolio.get('totalAssetsEstimated')}
    formulas = portfolio.setdefault('summaryFormulas', {})
    if formulas.get('totalAssetsEstimated'):
        formulas['totalAssetsEstimated'] = f"{formulas['totalAssetsEstimated']} + Binance {int(crypto_twd):,}"
    portfolio['binance'] = snapshot
    note = portfolio.get('valuationNote', '')
    addition = f"Binance @ {snapshot['usdTwdRate']} USDT/TWD"
    portfolio['valuationNote'] = f'{note}; includes {addition}' if note else f'Includes {addition}'
    return portfolio


class BinanceAccountService:
    def __init__(self, db=None, request=None):
        self._db = db
        self._request = request or self._http_request
        self._task: asyncio.Task | None = None
        self._time_offset = 0

    @property
    def enabled(self) -> bool:
        return bool(os.getenv('BINANCE_API_KEY') and os.getenv('BINANCE_API_SECRET'))

    @property
    def db(self):
        if self._db is None:
            from ..databases.ibkr_research_db import get_ibkr_research_db
            self._db = get_ibkr_research_db()
        return self._db

    async def _http_request(self, method: str, path: str, params: dict, signed: bool):
        import httpx
        base = os.getenv('BINANCE_API_BASE', API_BASE).rstrip('/')
        headers = {}
        query = urlencode(params)
        if signed:
            params = {**params, 'recvWindow': RECV_WINDOW, 'timestamp': int(time.time() * 1000) + self._time_offset}
            query = sign_query(params, os.environ['BINANCE_API_SECRET'])
            headers['X-MBX-APIKEY'] = os.environ['BINANCE_API_KEY']
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.request(method, f'{base}{path}?{query}' if query else base + path, headers=headers)
        if response.status_code in (403, 451):
            raise BinanceRegionRestricted(f'HTTP {response.status_code}')
        if response.status_code >= 400:
            # Binance error codes (-2015 bad key/IP, -1021 clock) are safe to log; never the URL (it has the signature).
            try:
                code = response.json().get('code')
            except Exception:
                code = None
            raise RuntimeError(f'binance_http_{response.status_code}:{code}:{path}')
        return response.json()

    async def _usd_twd(self) -> tuple[float, str]:
        override = os.getenv('USD_TWD_RATE')
        if override:
            try:
                return float(override), 'manual'
            except ValueError:
                logger.warning('Invalid USD_TWD_RATE, ignoring')
        try:
            from .ibkr_market import ibkr_market_service
            async with ibkr_market_service._client() as client:
                rates, source = await ibkr_market_service._fetch_fx(client)
            return float(rates.get('USD', _FX_FALLBACK_USD_TWD)), source
        except Exception:
            return _FX_FALLBACK_USD_TWD, 'fallback'

    async def refresh_once(self) -> bool:
        if not self.enabled:
            return False
        try:
            server = await self._request('GET', '/api/v3/time', {}, False)
            self._time_offset = int(server['serverTime']) - int(time.time() * 1000)
            spot = await self._request('GET', '/api/v3/account', {'omitZeroBalances': 'true'}, True)
            funding = await self._request('POST', '/sapi/v1/asset/get-funding-asset', {}, True)
            wallets = await self._request('GET', '/sapi/v1/asset/wallet/balance', {'quoteAsset': 'USDT'}, True)
            prices = usdt_prices(await self._request('GET', '/api/v3/ticker/price', {}, False))
            usd_twd, fx_source = await self._usd_twd()
            snapshot = build_snapshot(spot, funding, wallets, prices, usd_twd, fx_source,
                                      datetime.now(timezone.utc).isoformat())
        except Exception as exc:
            detail = str(exc) if str(exc).startswith('binance_http_') else type(exc).__name__
            logger.warning('Binance balance refresh failed: %s', detail)
            return False
        stamp = datetime.now(timezone.utc)
        period = stamp.strftime('%Y-%m-%dT%H:') + str(stamp.minute // 15 * 15).zfill(2)
        await asyncio.to_thread(self.db.save, 'BINANCE', 'PRIVATE', 0, 'portfolio', snapshot, period=period)
        return True

    async def get_snapshot(self) -> dict | None:
        if not self.enabled:
            return None
        saved = await asyncio.to_thread(self.db.latest, 'BINANCE', 'PRIVATE', 'portfolio')
        return saved['payload'] if saved else None

    async def _loop(self):
        while True:
            try:
                await self.refresh_once()
            except Exception:
                logger.exception('Binance balance loop error')
            await asyncio.sleep(REFRESH_SECONDS)

    async def start(self):
        if not self.enabled:
            logger.info('Binance balances off: BINANCE_API_KEY/BINANCE_API_SECRET not set')
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name='binance-account')

    async def close(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


binance_account_service = BinanceAccountService()
