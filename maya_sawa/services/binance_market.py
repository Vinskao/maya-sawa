"""Public Binance spot quotes and daily candles for the CRYPTO market (no API key).

Phase 1 of docs/BINANCE_ASSETS_PLAN.md. Only public market-data endpoints are
called; account endpoints and keys belong to phase 2. Data lands in the same
durable dataset table as IBKR (market CRYPTO, conid 0), and API reads never
call Binance. Failures, including a region block (HTTP 451/403), are recorded
as gaps and never erase the last good data.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from copy import deepcopy
from datetime import datetime, timezone

from .ibkr_research import technical_summary

logger = logging.getLogger(__name__)

MARKET = 'CRYPTO'
QUOTE_ASSET = 'USDT'
API_BASE = 'https://api.binance.com'
DEFAULT_SYMBOLS = 'BTC,ETH'
NAMES = {'BTC': 'Bitcoin', 'ETH': 'Ethereum', 'SOL': 'Solana', 'BNB': 'BNB', 'XRP': 'XRP'}
BACKFILL_DAYS = 1000  # the klines maximum per request, about 2.7 years
LOOP_SECONDS = 60


class BinanceRegionRestricted(Exception):
    """Binance refused this location (HTTP 451 or 403). Never worked around with a proxy."""


def _number(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def configured_symbols() -> list[str]:
    symbols = []
    for item in os.getenv('BINANCE_SYMBOLS', DEFAULT_SYMBOLS).split(','):
        code = item.strip().upper()
        if re.fullmatch(r'[A-Z0-9]{2,10}', code) and code not in symbols:
            symbols.append(code)
    return symbols


def parse_klines(raw) -> list[dict]:
    bars = {}
    for row in raw if isinstance(raw, list) else []:
        if not isinstance(row, list) or len(row) < 9:
            continue
        stamp = _number(row[0])
        values = {key: _number(row[index]) for key, index in (('open', 1), ('high', 2), ('low', 3), ('close', 4))}
        if not stamp or any(value is None or value <= 0 for value in values.values()):
            continue
        if values['high'] < max(values['open'], values['close']) or values['low'] > min(values['open'], values['close']):
            continue
        moment = datetime.fromtimestamp(stamp / 1000, timezone.utc)
        day = moment.date().isoformat()  # Binance daily candles open at 00:00 UTC
        trades = _number(row[8])
        bars[day] = {'date': day, 'timestamp': moment.isoformat(), **values, 'volume': _number(row[5]),
                     'quoteVolume': _number(row[7]), 'trades': int(trades) if trades is not None else None}
    return sorted(bars.values(), key=lambda bar: bar['date'])


def parse_ticker(raw: dict) -> dict:
    quote = {name: _number(raw.get(field)) for name, field in {
        'close': 'lastPrice', 'open': 'openPrice', 'high': 'highPrice', 'low': 'lowPrice',
        'previousClose': 'prevClosePrice', 'change': 'priceChange', 'changePercent': 'priceChangePercent',
        'bid': 'bidPrice', 'ask': 'askPrice', 'volume': 'volume', 'quoteVolume': 'quoteVolume'}.items()}
    for key in ('close', 'open', 'high', 'low', 'previousClose', 'bid', 'ask'):
        if quote[key] is not None and quote[key] <= 0:
            quote[key] = None
    quote.update(priceType='last', sourceUpdatedAt=raw.get('closeTime'))
    return quote


def dashboard_quote(code: str, persisted: dict | None) -> dict | None:
    if not persisted:
        return None
    values = persisted.get('payload') or {}
    stamp = values.get('sourceUpdatedAt')
    timestamp = (datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()
                 if isinstance(stamp, (int, float)) else persisted.get('fetchedAt'))
    return {'symbol': code, 'name': NAMES.get(code, code), 'productType': 'crypto', 'currency': QUOTE_ASSET,
            **{key: values.get(key) for key in ('close', 'open', 'high', 'low', 'change', 'changePercent', 'volume', 'priceType')},
            'timestamp': timestamp, 'fetchedAt': persisted.get('fetchedAt'), 'quoteSource': 'Binance'}


class BinanceMarketCollector:
    def __init__(self, db=None, fetch=None):
        self._db = db
        self._fetch = fetch or self._http_get
        self._task: asyncio.Task | None = None
        self._read_cache = {}
        self.quote_seconds = 60
        self.history_seconds = 6 * 3600

    @property
    def db(self):
        if self._db is None:
            from ..databases.ibkr_research_db import get_ibkr_research_db
            self._db = get_ibkr_research_db()
        return self._db

    @staticmethod
    async def _http_get(path: str, params: dict):
        import httpx
        base = os.getenv('BINANCE_API_BASE', API_BASE).rstrip('/')
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(base + path, params=params)
        if response.status_code in (403, 451):
            raise BinanceRegionRestricted(f'HTTP {response.status_code}')
        response.raise_for_status()
        return response.json()

    def _due(self, code: str, kind: str, seconds: float) -> bool:
        attempt = self.db.latest(code, MARKET, kind, successful=False)
        if not attempt:
            return True
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(attempt['fetchedAt'])).total_seconds()
        # A failure retries within the hour at most; a region block does not change minute to minute.
        return elapsed >= (seconds if attempt['status'] == 'ok' else min(max(seconds, 600), 3600))

    def _save_failure(self, code: str, kind: str, exc: Exception):
        # Safe classification only; raw exception text can carry URLs.
        detail = 'Binance refused this region' if isinstance(exc, BinanceRegionRestricted) else (
            str(exc) if isinstance(exc, ValueError) else 'Binance request unavailable')
        self.db.save(code, MARKET, 0, kind, {'reason': type(exc).__name__, 'detail': detail}, status='unavailable')

    async def collect_once(self):
        symbols = configured_symbols()
        due_quotes = [code for code in symbols if await asyncio.to_thread(self._due, code, 'quote', self.quote_seconds)]
        if due_quotes:
            pairs = [code + QUOTE_ASSET for code in due_quotes]
            try:
                rows = await self._fetch('/api/v3/ticker/24hr', {'symbols': json.dumps(pairs, separators=(',', ':'))})
                by_pair = {row.get('symbol'): row for row in rows if isinstance(row, dict)}
                for code in due_quotes:
                    quote = parse_ticker(by_pair.get(code + QUOTE_ASSET, {}))
                    if quote['close'] is None:
                        await asyncio.to_thread(self._save_failure, code, 'quote', ValueError('No price for this pair'))
                        continue
                    period = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H')  # one stored quote per hour
                    await asyncio.to_thread(self.db.save, code, MARKET, 0, 'quote', quote, period=period)
                    self._read_cache.pop(code, None)
            except Exception as exc:
                for code in due_quotes:
                    await asyncio.to_thread(self._save_failure, code, 'quote', exc)
        for code in symbols:
            if not await asyncio.to_thread(self._due, code, 'history_raw', self.history_seconds):
                continue
            try:
                previous = await asyncio.to_thread(self.db.latest, code, MARKET, 'history_raw')
                raw = await self._fetch('/api/v3/klines', {'symbol': code + QUOTE_ASSET, 'interval': '1d',
                                                           'limit': 5 if previous else BACKFILL_DAYS})
                bars = parse_klines(raw)
                if not bars:
                    raise ValueError('No valid daily candles')
                for bar in bars:
                    await asyncio.to_thread(self.db.save, code, MARKET, 0, 'daily', bar, period=bar['date'])
                meta = {'symbol': code + QUOTE_ASSET, 'interval': '1d', 'bars': len(bars),
                        'first': bars[0]['date'], 'last': bars[-1]['date']}
                await asyncio.to_thread(self.db.save, code, MARKET, 0, 'history_raw', meta,
                                        period=datetime.now(timezone.utc).strftime('%Y-%m-%d'))
                self._read_cache.pop(code, None)
            except Exception as exc:
                await asyncio.to_thread(self._save_failure, code, 'history_raw', exc)

    def read(self, code: str) -> dict:
        code = code.upper()
        if code not in configured_symbols():
            raise ValueError('Unsupported crypto symbol')
        cached = self._read_cache.get(code)
        if cached and time.monotonic() - cached[0] < 60:
            return deepcopy(cached[1])
        datasets = {kind: self.db.latest(code, MARKET, kind) for kind in ('quote', 'history_raw')}
        coverage = {kind: self.db.latest(code, MARKET, kind, successful=False) for kind in datasets}
        daily = [row['payload'] for row in self.db.history(code, MARKET, 'daily', limit=1825)]
        result = {'code': code, 'market': MARKET, 'name': NAMES.get(code, code), 'quoteAsset': QUOTE_ASSET,
                  'source': 'Binance', 'persisted': True,
                  'datasets': {**datasets, 'profile': None, 'financials': None},
                  'coverage': {k: {a: b for a, b in (v or {}).items() if a != 'payload'}
                               | {'detail': (v or {}).get('payload', {}) if (v or {}).get('status') != 'ok' else None}
                               for k, v in coverage.items()},
                  'daily': daily, 'technical': technical_summary(daily),
                  'gaps': [f'Prices are Binance spot {code}/{QUOTE_ASSET}; daily candles open at 00:00 UTC and volume is in {code}.',
                           'Crypto has no filings, institutional flows, margin or ownership data.']}
        self._read_cache[code] = (time.monotonic(), result)
        return deepcopy(result)

    async def _loop(self):
        while True:
            try:
                await self.collect_once()
            except Exception as exc:
                logger.warning('Binance collection failed: %s', type(exc).__name__)
            await asyncio.sleep(LOOP_SECONDS)

    async def start(self):
        if os.getenv('BINANCE_MARKET_ENABLED', 'true').lower() != 'true':
            logger.info('Binance market collection off: BINANCE_MARKET_ENABLED is not true')
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name='binance-market')

    async def close(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


binance_market_collector = BinanceMarketCollector()
