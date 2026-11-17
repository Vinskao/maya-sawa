from pathlib import Path

from maya_sawa.services import market_macro

RAW = (Path(__file__).parents[2] / 'fixtures/macro/owid_population.csv').read_bytes()


def test_population_series_cover_the_four_economies_as_annual_millions():
    assert set(market_macro.POPULATION_SERIES) == {'US_POPULATION', 'JP_POPULATION', 'TW_POPULATION', 'KR_POPULATION'}
    assert all(unit == 'million persons' and freq == 'annual' for _, unit, freq in market_macro.POPULATION_SERIES.values())
    assert set(market_macro.POPULATION_SERIES) <= market_macro.FREE_CACHE_CODES


def test_owid_population_keeps_four_economies_in_millions_and_skips_blank_and_other_countries():
    rows = market_macro.parse_owid_population_csv(RAW)
    assert {'code': 'TW_POPULATION', 'period': '2023', 'value': 23.317} in rows
    assert {'code': 'US_POPULATION', 'period': '2023', 'value': 343.477} in rows
    assert {'code': 'JP_POPULATION', 'period': '2022', 'value': 124.998} in rows
    assert not any(row['code'].startswith('FR') for row in rows)
    assert not any(row['code'] == 'US_POPULATION' and row['period'] == '2022' for row in rows)


def test_population_collector_stores_rows_from_one_request(monkeypatch):
    calls = []
    monkeypatch.setattr(market_macro, '_request_free_cached', lambda *a, **k: calls.append(a) or (200, RAW))
    monkeypatch.setattr(market_macro.market_macro_db, 'reserve_source_call', lambda *a, **k: 1)
    monkeypatch.setattr(market_macro.market_macro_db, 'finish_source_call', lambda *a, **k: None)
    monkeypatch.setattr(market_macro, '_fetched_within', lambda *a, **k: False)
    saved = []
    service = market_macro.MarketMacroService()
    monkeypatch.setattr(service, '_cache_free_series', lambda rows, *a, **k: saved.extend(rows) or len(rows))
    assert service._fetch_population() == 5
    assert len(calls) == 1 and {row['code'] for row in saved} == set(market_macro.POPULATION_SERIES)
