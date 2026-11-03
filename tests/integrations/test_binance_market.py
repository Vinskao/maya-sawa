import asyncio
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.databases.ibkr_research_db import IbkrResearchDatabase
from maya_sawa.services.binance_market import (
    BinanceMarketCollector, BinanceRegionRestricted, configured_symbols, dashboard_quote, parse_klines, parse_ticker,
)

# Real responses from api.binance.com on 2026-10-28 (BTCUSDT, interval=1d).
KLINES = [
    [1793059200000, "80150.56000000", "81300.00000000", "79506.00000000", "80909.77000000", "13230.64597000",
     1793145599999, "1062256600.12888090", 2450945, "7882.44298000", "633083742.98950630", "0"],
    [1793145600000, "80909.77000000", "81823.00000000", "80621.22000000", "80724.72000000", "5652.61012000",
     1793231999999, "458587476.01613690", 1026225, "3001.53086000", "243593021.22096240", "0"],
]
TICKER = {"symbol": "BTCUSDT", "priceChange": "508.08000000", "priceChangePercent": "0.633",
          "weightedAvgPrice": "80843.31116912", "prevClosePrice": "80216.64000000", "lastPrice": "80724.72000000",
          "lastQty": "0.45384000", "bidPrice": "80724.72000000", "bidQty": "0.23967000", "askPrice": "80724.73000000",
          "askQty": "6.42041000", "openPrice": "80216.64000000", "highPrice": "81823.00000000",
          "lowPrice": "79890.00000000", "volume": "12460.22633000", "quoteVolume": "1007325954.43385430",
          "openTime": 1793106440013, "closeTime": 1793192840013, "firstId": 6795103203, "lastId": 6797453391,
          "count": 2350189}


def memory_db():
    return IbkrResearchDatabase(create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))


def test_klines_become_utc_daily_bars_with_base_and_quote_volume():
    bars = parse_klines(KLINES)
    assert [bar['date'] for bar in bars] == ['2026-10-27', '2026-10-28']
    assert bars[0] == {'date': '2026-10-27', 'timestamp': '2026-10-27T00:00:00+00:00', 'open': 80150.56,
                       'high': 81300.0, 'low': 79506.0, 'close': 80909.77, 'volume': 13230.64597,
                       'quoteVolume': 1062256600.1288809, 'trades': 2450945}


def test_klines_drop_malformed_and_inconsistent_rows():
    bad = [[1793059200000, "0", "0", "0", "0", "0", 0, "0", 0], ["x"],
           [1793145600000, "100", "90", "95", "98", "1", 0, "1", 1]]  # high below open
    assert parse_klines(bad) == []
    assert parse_klines({'code': -1121, 'msg': 'Invalid symbol.'}) == []


def test_ticker_maps_public_24h_fields():
    quote = parse_ticker(TICKER)
    assert quote['close'] == 80724.72
    assert quote['previousClose'] == 80216.64
    assert quote['change'] == 508.08
    assert quote['changePercent'] == 0.633
    assert quote['high'] == 81823.0 and quote['low'] == 79890.0
    assert quote['volume'] == 12460.22633
    assert quote['sourceUpdatedAt'] == 1793192840013
    assert quote['priceType'] == 'last'


def test_symbols_are_validated_and_default_to_btc_eth(monkeypatch):
    monkeypatch.delenv('BINANCE_SYMBOLS', raising=False)
    assert configured_symbols() == ['BTC', 'ETH']
    monkeypatch.setenv('BINANCE_SYMBOLS', 'sol, btc,../x,BTC,')
    assert configured_symbols() == ['SOL', 'BTC']


def test_dashboard_quote_is_a_public_row_with_source_time():
    quote = dashboard_quote('BTC', {'fetchedAt': '2026-10-28T11:00:00+00:00', 'payload': parse_ticker(TICKER)})
    assert quote['symbol'] == 'BTC'
    assert quote['currency'] == 'USDT'
    assert quote['close'] == 80724.72
    assert quote['timestamp'] == '2026-10-28T13:07:20.013000+00:00'
    assert quote['quoteSource'] == 'Binance'
    assert dashboard_quote('BTC', None) is None


def fake_fetch(calls, *, klines=KLINES, ticker=None, error=None):
    async def fetch(path, params):
        calls.append((path, dict(params)))
        if error:
            raise error
        if path == '/api/v3/klines':
            return klines
        return ticker if ticker is not None else [{**TICKER, 'symbol': symbol} for symbol in json.loads(params['symbols'])]
    return fetch


def test_collect_backfills_then_reads_back_the_overseas_shape(monkeypatch):
    monkeypatch.setenv('BINANCE_SYMBOLS', 'BTC')
    calls = []
    collector = BinanceMarketCollector(db=memory_db(), fetch=fake_fetch(calls))
    asyncio.run(collector.collect_once())
    assert calls[0] == ('/api/v3/ticker/24hr', {'symbols': '["BTCUSDT"]'})
    assert calls[1] == ('/api/v3/klines', {'symbol': 'BTCUSDT', 'interval': '1d', 'limit': 1000})
    result = collector.read('BTC')
    assert result['market'] == 'CRYPTO' and result['source'] == 'Binance'
    assert [bar['close'] for bar in result['daily']] == [80909.77, 80724.72]
    assert result['datasets']['quote']['payload']['close'] == 80724.72
    assert result['datasets']['history_raw']['payload']['bars'] == 2
    assert result['coverage']['history_raw']['status'] == 'ok'
    assert result['technical']['sessions'] == 2

    # Fresh data is not refetched; the next history poll after the interval is incremental.
    calls.clear()
    asyncio.run(collector.collect_once())
    assert calls == []
    collector.history_seconds = 0
    collector.quote_seconds = 0
    asyncio.run(collector.collect_once())
    assert ('/api/v3/klines', {'symbol': 'BTCUSDT', 'interval': '1d', 'limit': 5}) in calls


def test_region_block_is_recorded_and_keeps_last_good_data(monkeypatch):
    monkeypatch.setenv('BINANCE_SYMBOLS', 'BTC')
    db = memory_db()
    asyncio.run(BinanceMarketCollector(db=db, fetch=fake_fetch([])).collect_once())
    blocked = BinanceMarketCollector(db=db, fetch=fake_fetch([], error=BinanceRegionRestricted('HTTP 451')))
    blocked.quote_seconds = blocked.history_seconds = 0
    asyncio.run(blocked.collect_once())
    result = blocked.read('BTC')
    assert result['coverage']['quote']['status'] == 'unavailable'
    assert result['coverage']['quote']['detail']['reason'] == 'BinanceRegionRestricted'
    assert result['datasets']['quote']['payload']['close'] == 80724.72
    assert len(result['daily']) == 2


def test_failure_detail_never_stores_raw_exception_text(monkeypatch):
    monkeypatch.setenv('BINANCE_SYMBOLS', 'BTC')
    collector = BinanceMarketCollector(db=memory_db(), fetch=fake_fetch([], error=RuntimeError('https://secret.example/?k=1')))
    asyncio.run(collector.collect_once())
    assert 'secret' not in str(collector.read('BTC')['coverage'])


def test_read_rejects_unconfigured_symbol(monkeypatch):
    monkeypatch.setenv('BINANCE_SYMBOLS', 'BTC')
    with pytest.raises(ValueError):
        BinanceMarketCollector(db=memory_db()).read('DOGE')
