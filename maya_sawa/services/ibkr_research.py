"""Paced, DB-first collection of public IBKR contract, quote and OHLCV data.

No orders, paid regulatory snapshots, new subscriptions or deprecated
fundamental tags. API reads never invoke the broker. Missing permissions are
recorded as gaps and never erase successful data.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..databases.ibkr_research_db import get_ibkr_research_db

MARKETS = {'USD': 'US', 'JPY': 'JP', 'KRW': 'KR', 'HKD': 'HK', 'GBP': 'GB', 'EUR': 'EU', 'TWD': 'TW'}
ZONES = {'US': 'America/New_York', 'JP': 'Asia/Tokyo', 'KR': 'Asia/Seoul', 'HK': 'Asia/Hong_Kong'}
FIELDS = '31,55,70,71,82,83,84,86,87,6509,7051,7087,7088,7762'


def number(value):
    if value is None:
        return None
    text = re.sub(r'^[CH]\s*', '', str(value)).replace(',', '').replace('%', '').strip()
    scale = 1
    if text and text[-1].upper() in ('K', 'M', 'B'):
        scale = {'K': 1e3, 'M': 1e6, 'B': 1e9}[text[-1].upper()]
        text = text[:-1]
    try:
        result = float(text) * scale
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def public_quote(raw):
    # Allowlist: account-specific fields 73..80 can never enter the public dataset.
    quote = {name: number(raw.get(field)) for name, field in {
        'close': '31', 'high': '70', 'low': '71', 'change': '82', 'changePercent': '83',
        'bid': '84', 'ask': '86', 'volume': '87', 'historicalVolatility': '7087',
        'historicalVolatilityClose': '7088'}.items()}
    if number(raw.get('7762')) is not None:
        quote['volume'] = number(raw['7762'])
    quote.update(availability=raw.get('6509'), name=raw.get('7051'),
                 priceType='previousClose' if str(raw.get('31', '')).startswith('C') else
                           'halted' if str(raw.get('31', '')).startswith('H') else 'last',
                 sourceUpdatedAt=raw.get('_updated'))
    for key in ('close', 'high', 'low', 'bid', 'ask'):
        if quote[key] is not None and quote[key] <= 0:
            quote[key] = None  # premarket often reports 0.00 for unavailable day ranges
    return quote


def dashboard_quote(position, fetched_at, persisted=None):
    values = (persisted or {}).get('payload') or {}
    stamp = values.get('sourceUpdatedAt')
    timestamp = datetime.fromtimestamp(stamp/1000, timezone.utc).isoformat() if isinstance(stamp, (int, float)) else fetched_at
    return {'symbol': position['code'], 'name': values.get('name') or position.get('name') or position['code'],
            'productType': 'stock', 'currency': position.get('currency'),
            'close': values.get('close') or position.get('lastPrice'), 'open': None,
            **{key: values.get(key) for key in ('high', 'low', 'change', 'changePercent', 'volume', 'availability', 'priceType')},
            'timestamp': timestamp, 'fetchedAt': (persisted or {}).get('fetchedAt') or fetched_at,
            'quoteSource': 'Interactive Brokers CPAPI',
            'priceBasis': 'marketData' if values.get('close') else 'positionValuation'}


def normalize_bars(raw, market):
    zone = ZoneInfo(ZONES.get(market, 'UTC'))
    factor = number(raw.get('volumeFactor'))
    bars = {}
    for row in raw.get('data', []):
        stamp = number(row.get('t'))
        values = {key: number(row.get(field)) for key, field in
                  {'open': 'o', 'high': 'h', 'low': 'l', 'close': 'c'}.items()}
        if not stamp or any(value is None or value <= 0 for value in values.values()):
            continue
        if values['high'] < max(values['open'], values['close']) or values['low'] > min(values['open'], values['close']):
            continue
        moment = datetime.fromtimestamp(stamp / 1000, timezone.utc)
        day = moment.astimezone(zone).date().isoformat()
        volume = number(row.get('v'))
        bars[day] = {'date': day, 'timestamp': moment.isoformat(), **values, 'rawVolume': volume,
                     'volumeFactor': factor, 'volume': volume * factor if volume is not None and factor else None}
    return sorted(bars.values(), key=lambda bar: bar['date'])


def technical_summary(bars):
    closes = [row['close'] for row in bars]
    result = {f'ma{size}': round(sum(closes[-size:]) / size, 4) if len(closes) >= size else None
              for size in (5, 10, 20, 60)}
    result.update(asOf=bars[-1]['date'] if bars else None, sessions=len(bars), rsi14Wilder=None,
                  rangeHigh=max((row['high'] for row in bars), default=None),
                  rangeLow=min((row['low'] for row in bars), default=None))
    for size in (5, 20):
        result[f'change{size}dPercent'] = round((closes[-1] / closes[-size-1] - 1) * 100, 4) if len(closes) > size and closes[-size-1] else None
    if len(closes) >= 15:
        changes = [b-a for a, b in zip(closes, closes[1:])]
        gain = sum(max(v, 0) for v in changes[:14]) / 14
        loss = sum(max(-v, 0) for v in changes[:14]) / 14
        for change in changes[14:]:
            gain = (gain * 13 + max(change, 0)) / 14
            loss = (loss * 13 + max(-change, 0)) / 14
        result['rsi14Wilder'] = round(100 - 100 / (1 + gain/loss), 4) if loss else 100 if gain else 50
    return result


class IbkrResearchCollector:
    def __init__(self, db=None):
        self._db = db
        self.lock = asyncio.Lock()
        self._read_cache = {}

    @property
    def db(self):
        return self._db or get_ibkr_research_db()

    def due(self, code, market, kind, seconds, retry_failed=False):
        attempt = self.db.latest(code, market, kind, successful=False)
        if not attempt:
            return True
        if retry_failed and attempt['status'] != 'ok':  # the session just came back; don't wait out the backoff
            return True
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(attempt['fetchedAt'])).total_seconds()
        return elapsed >= (seconds if attempt['status'] == 'ok' else min(seconds, 3600))

    async def collect(self, gateway, positions, retry_failed=False):
        if self.lock.locked():
            return
        async with self.lock, gateway._client() as client:
            for p in positions:
                cid = p.get('conid')
                market = MARKETS.get(p.get('currency'), 'UNKNOWN')
                if not cid or p.get('assetClass') != 'STK' or market in ('UNKNOWN', 'TW'):
                    continue
                code = p['code']
                for kind, seconds in [('profile', 7 * 86400), ('history_raw', 6 * 3600), ('quote', 240)]:
                    if not await asyncio.to_thread(self.due, code, market, kind, seconds, retry_failed):
                        continue
                    try:
                        if kind == 'profile':
                            response = await client.get(f'{gateway._base}/iserver/contract/{cid}/info')
                        elif kind == 'history_raw':
                            previous = await asyncio.to_thread(self.db.latest, code, market, 'history_raw')
                            response = await client.get(f'{gateway._base}/iserver/marketdata/history', params={
                                'conid': cid, 'period': '1w' if previous else '1y', 'bar': '1d', 'outsideRth': 'false'})
                        else:
                            response = await client.get(f'{gateway._base}/iserver/marketdata/snapshot',
                                                        params={'conids': cid, 'fields': FIELDS})
                            # First request is a subscription preflight and may contain only conid.
                            if response.status_code == 200 and isinstance(response.json(), list) and not any('31' in row for row in response.json()):
                                await asyncio.sleep(1.3)
                                response = await client.get(f'{gateway._base}/iserver/marketdata/snapshot',
                                                            params={'conids': cid, 'fields': FIELDS})
                        response.raise_for_status()
                        raw = response.json()
                        if isinstance(raw, dict) and raw.get('error'):
                            raise ValueError('Broker returned error')
                        period = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                        if kind == 'quote':
                            raw = public_quote(next((row for row in raw if str(row.get('conid')) == str(cid)), {}))
                            if raw['close'] is None:
                                raise ValueError('No quote fields; entitlement or preflight pending')
                            period = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:') + str(datetime.now(timezone.utc).minute // 15 * 15).zfill(2)
                        elif kind == 'history_raw':
                            bars = normalize_bars(raw, market)
                            if not bars:
                                raise ValueError('No valid daily bars')
                            for bar in bars:
                                await asyncio.to_thread(self.db.save, code, market, cid, 'daily', bar, period=bar['date'])
                        elif str(raw.get('con_id')) != str(cid):
                            raise ValueError('Contract identity mismatch')
                        await asyncio.to_thread(self.db.save, code, market, cid, kind, raw, period=period)
                        self._read_cache.pop((code, market), None)
                    except Exception as exc:
                        # Store safe error classification; never raw exception strings (could include account URLs).
                        await asyncio.to_thread(self.db.save, code, market, cid, kind,
                            {'reason': type(exc).__name__, 'detail': str(exc) if isinstance(exc, ValueError) else 'Broker request unavailable'},
                            status='unavailable')
                    await asyncio.sleep(1.3)  # comfortably below 50 history requests/minute
                from .overseas_financials import collect_sec_financials
                await collect_sec_financials(self, code, market, cid)

    def read(self, code, market):
        if market not in ZONES:
            raise ValueError('Unsupported overseas market')
        cached = self._read_cache.get((code, market))
        if cached and time.monotonic() - cached[0] < 60:
            return deepcopy(cached[1])
        datasets = {kind: self.db.latest(code, market, kind) for kind in ('profile', 'quote', 'history_raw', 'financials')}
        coverage = {kind: self.db.latest(code, market, kind, successful=False) for kind in datasets}
        # Request metadata contains a complete history chunk; normalized daily bars are the union of backfill + increments.
        history_meta = datasets['history_raw']
        if history_meta:
            datasets['history_raw'] = {**history_meta, 'payload': {k: v for k, v in history_meta['payload'].items() if k != 'data'}}
        daily = [row['payload'] for row in self.db.history(code, market, 'daily')]
        result = {'code': code, 'market': market, 'source': 'Interactive Brokers CPAPI', 'persisted': True,
                'datasets': datasets, 'coverage': {k: {a: b for a, b in (v or {}).items() if a != 'payload'} | {'detail': (v or {}).get('payload', {}) if (v or {}).get('status') != 'ok' else None} for k, v in coverage.items()},
                'daily': daily, 'technical': technical_summary(daily),
                'gaps': ['CPAPI does not supply quarterly statements, earnings estimates, institutional ownership or short interest. US SEC financials are supplemented where available; Japan EDINET and Korea OpenDART require separate keys.',
                         'Fundamental snapshot tags (EPS, PE, market capitalization, dividend yield, beta) deprecated by IBKR 2026-01-06.']}
        self._read_cache[(code, market)] = (time.monotonic(), result)
        return deepcopy(result)


ibkr_research_collector = IbkrResearchCollector()
