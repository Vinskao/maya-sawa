import json
from datetime import date
from pathlib import Path

from maya_sawa.services import market_macro


def test_asian_fred_series_cover_labor_rates_consumption_fx_and_trade():
    expected = {'LRUNTTTTJPM156S', 'LRUNTTTTKRM156S', 'IRSTCI01KRM156N', 'DEXKOUS',
                'JPNSLRTTO01GPSAM', 'JPNSLRTTO01GYSAM', 'KORSLRTTO01GPSAM', 'KORSLRTTO01GYSAM',
                'XTEXVA01JPM667S', 'XTIMVA01JPM667S', 'XTEXVA01KRM667S', 'XTIMVA01KRM667S'}
    assert expected <= set(market_macro.FRED_SERIES)
    assert market_macro.FRED_SERIES['DEXKOUS'][1] == 'KRW/USD'
    assert market_macro.FRED_SERIES['XTEXVA01KRM667S'][1] == 'USD'


def test_bis_cpi_keeps_country_period_and_index_and_skips_missing_values():
    raw = b'FREQ,REF_AREA,UNIT_MEASURE,TIME_PERIOD,OBS_VALUE\nM,JP,628,2026-08,123.4\nM,KR,628,2026-08,138.3\nM,KR,628,2026-09,\nM,US,628,2026-09,142.0\n'
    assert market_macro.parse_bis_cpi_csv(raw) == [
        {'code': 'JP_CPI', 'period': '2026-08', 'value': '123.4'},
        {'code': 'KR_CPI', 'period': '2026-08', 'value': '138.3'},
    ]


def test_bis_collector_reads_real_fixture_without_using_a_dart_key(monkeypatch):
    raw = (Path(__file__).parent / 'fixtures/macro/bis_jp_kr_cpi.csv').read_bytes()
    monkeypatch.setattr(market_macro, '_request_free_cached', lambda *a, **k: (200, raw))
    monkeypatch.setattr(market_macro.market_macro_db, 'reserve_source_call', lambda *a, **k: 1)
    monkeypatch.setattr(market_macro.market_macro_db, 'finish_source_call', lambda *a, **k: None)
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, '_cache_free_series', lambda rows, *a, **k: saved.extend(rows) or len(rows))
    service._fetch_asia_cpi()
    assert {row['code'] for row in saved} == {'JP_CPI', 'KR_CPI'}
    assert all(float(row['value']) > 0 for row in saved)


def test_japan_and_korea_important_calendar_events_are_not_dropped(monkeypatch):
    payload = {'events': [
        {'title': 'CPI', 'country': 'KR', 'impact': 'high', 'date': date.today().isoformat()},
        {'title': 'Unemployment Rate', 'country': 'Japan', 'impact': 'medium', 'date': date.today().isoformat()},
        {'title': 'Minor survey', 'country': 'KR', 'impact': 'low', 'date': date.today().isoformat()},
    ]}
    monkeypatch.setattr(market_macro, '_request', lambda *a, **k: (200, json.dumps(payload).encode()))
    monkeypatch.setattr(market_macro.market_macro_db, 'reserve_source_call', lambda *a, **k: 1)
    monkeypatch.setattr(market_macro.market_macro_db, 'finish_source_call', lambda *a, **k: None)
    saved = []
    monkeypatch.setattr(market_macro.market_macro_db, 'update_event_expectations', lambda rows: saved.extend(rows) or len(rows))
    market_macro.MarketMacroService()._fetch_consensus_calendar()
    assert {row['title'] for row in saved} == {'Korea CPI', 'Japan Unemployment Rate'}


# 2026-10-28: the FRED daily budget ran out at KORSLRTTO01GYSAM on every refresh, so the four trade series declared
# after it (Korea and Japan exports/imports) were never fetched and the Korea node said "no data collected yet".
def test_fred_fetches_series_it_has_never_stored_before_refreshing_ones_it_has():
    codes = ['DGS10', 'NFCI', 'KORSLRTTO01GYSAM', 'XTEXVA01KRM667S', 'XTIMVA01KRM667S']
    fetched = {'DGS10': '2026-10-28T07:29:00+00:00', 'NFCI': '2026-10-27T03:02:00+00:00'}
    assert market_macro.fred_fetch_order(codes, fetched) == ['KORSLRTTO01GYSAM', 'XTEXVA01KRM667S', 'XTIMVA01KRM667S', 'NFCI', 'DGS10']


def test_a_short_fred_budget_still_reaches_the_korea_trade_series(monkeypatch):
    from datetime import UTC, datetime, timedelta
    stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    store = {f'series:{code}': {'fetchedAt': stale, 'history': []} for code in market_macro.FRED_SERIES
             if code in market_macro.FREE_CACHE_CODES and not code.startswith('XT')}
    monkeypatch.setattr(market_macro._macro_local_cache, 'get', lambda key: store.get(key))
    budget = iter(range(1, 5))
    monkeypatch.setattr(market_macro.market_macro_db, 'reserve_source_call', lambda *a, **k: next(budget, None))
    monkeypatch.setattr(market_macro.market_macro_db, 'finish_source_call', lambda *a, **k: None)
    monkeypatch.setattr(market_macro.market_macro_db, 'sessions', None)
    requested = []
    def fake_request(url, *a, **k):
        requested.append(url.split('series_id=')[1].split('&')[0])
        return 200, b'{"observations": []}'
    monkeypatch.setattr(market_macro, '_request', fake_request)
    monkeypatch.setattr(market_macro.MarketMacroService, '_cache_free_series', lambda self, *a, **k: 0)
    service = market_macro.MarketMacroService()
    try:
        service._fetch_fred_observations()
    except RuntimeError as exc:
        assert 'budget_exhausted' in str(exc)
    assert {'XTEXVA01KRM667S', 'XTIMVA01KRM667S', 'XTEXVA01JPM667S', 'XTIMVA01JPM667S'} == set(requested)
