"""Money supply, central-bank liquidity, extra rates and credit/default series (plan section 22)."""
import json
from pathlib import Path

from maya_sawa.services import market_macro

FIXTURES = Path(__file__).parent / "fixtures" / "macro"


def test_ecb_csv_keeps_period_and_m2_notional_stock_index():
    # Index of notional stocks (flows-based, excludes reclassifications): growth computed from it matches the
    # ECB's published rate, e.g. 2026-08 / 2025-08 = 189.667 / 183.712 - 1 = 3.24% vs published 3.2415%.
    rows = market_macro.parse_ecb_csv((FIXTURES / "ecb_m2_index.csv").read_bytes(), "EZ_M2_INDEX")
    assert rows == [
        {"code": "EZ_M2_INDEX", "period": "2025-07", "value": "183.39912732550587"},
        {"code": "EZ_M2_INDEX", "period": "2025-08", "value": "183.71194646850645"},
    ]


def test_ecb_csv_skips_blank_or_nan_observations():
    raw = b"KEY,TIME_PERIOD,OBS_VALUE\nX,2026-07,\nX,2026-08,NaN\nX,2026-09,3.1\n"
    assert market_macro.parse_ecb_csv(raw, "EZ_M2_INDEX") == [{"code": "EZ_M2_INDEX", "period": "2026-09", "value": "3.1"}]


def test_boj_m2_converts_100_million_yen_to_trillion_yen():
    payload = json.loads((FIXTURES / "boj_m2.json").read_text(encoding="utf-8"))
    rows = market_macro.parse_boj_series(payload, "MAM1NAM2M2MO", "JP_M2", scale=1 / 10000)
    # 12,696,074 x 100 million yen = 1,269.6074 trillion yen.
    assert rows == [
        {"code": "JP_M2", "period": "2025-07", "value": "1269.6074"},
        {"code": "JP_M2", "period": "2025-08", "value": "1271.2263"},
        {"code": "JP_M2", "period": "2025-09", "value": "1270.8414"},
    ]


def test_boj_error_status_raises_instead_of_returning_empty_history():
    payload = {"STATUS": 400, "MESSAGEID": "M181005E", "RESULTSET": []}
    try:
        market_macro.parse_boj_series(payload, "MAM1NAM2M2MO", "JP_M2")
    except RuntimeError as exc:
        assert "boj" in str(exc)
    else:
        raise AssertionError("BoJ error payload must raise")


def test_cbc_money_stock_reads_m1b_and_m2_daily_average_levels():
    payload = json.loads((FIXTURES / "cbc_ef15m01.json").read_text(encoding="utf-8"))
    rows = market_macro.parse_cbc_money_stock(payload)
    by_key = {(row["code"], row["period"]): row["value"] for row in rows}
    # Real 2026-08 row: M1B 30,750,789 and M2 70,677,981 (NT$ million); the CBC header labels are mis-encoded,
    # so the parser relies on column positions and the published YoY must match the levels.
    assert by_key[("TW_M2", "2026-08")] == "70677981"
    assert by_key[("TW_M1B", "2026-08")] == "30750789"
    assert by_key[("TW_M2", "2025-08")] == "66184784"
    assert round((70677981 / 66184784 - 1) * 100, 2) == 6.79
    assert {row["code"] for row in rows} == {"TW_M1B", "TW_M2"}


def test_cbc_money_stock_rejects_a_changed_column_layout():
    payload = {"data": {"dataSets": [["2026M08", "1", "2"]]}}
    try:
        market_macro.parse_cbc_money_stock(payload)
    except RuntimeError as exc:
        assert "layout" in str(exc)
    else:
        raise AssertionError("short CBC rows must not be read as M2")


def test_fred_rows_skip_dot_placeholders_scale_units_and_label_periods():
    observations = [{"date": "2026-09-30", "value": "6755639"}, {"date": "2026-10-07", "value": "."},
                    {"date": "2026-10-14", "value": "6760001"}]
    assert market_macro.fred_observation_rows("WALCL", observations, "weekly", scale=1 / 1000) == [
        {"code": "WALCL", "period": "2026-09-30", "value": "6755.639"},
        {"code": "WALCL", "period": "2026-10-14", "value": "6760.001"},
    ]
    quarterly = [{"date": "2026-04-01", "value": "2.85"}]
    assert market_macro.fred_observation_rows("DRCCLACBS", quarterly, "quarterly") == [
        {"code": "DRCCLACBS", "period": "2026-04", "value": "2.85"}]


def test_net_liquidity_is_fed_assets_minus_tga_minus_reverse_repo():
    walcl = [{"period": "2026-10-07", "value": "6750.0"}, {"period": "2026-10-14", "value": "6755.639"}]
    tga = [{"period": "2026-10-07", "value": "850.0"}, {"period": "2026-10-14", "value": "883.373"}]
    # RRP is daily: the Wednesday value is used; a missing Wednesday falls back to the latest prior day.
    rrp = [{"period": "2026-10-06", "value": "2.5"}, {"period": "2026-10-14", "value": "0.1"}]
    assert market_macro.net_liquidity_rows(walcl, tga, rrp) == [
        {"code": "US_NET_LIQUIDITY", "period": "2026-10-07", "value": "5897.5"},
        {"code": "US_NET_LIQUIDITY", "period": "2026-10-14", "value": "5872.2"},
    ]


def test_net_liquidity_skips_weeks_without_tga_or_recent_rrp():
    walcl = [{"period": "2026-10-07", "value": "6750"}, {"period": "2026-10-14", "value": "6755"}]
    tga = [{"period": "2026-10-14", "value": "883"}]
    rrp = [{"period": "2026-09-01", "value": "5"}]
    assert market_macro.net_liquidity_rows(walcl, tga, rrp) == []


def test_weekly_and_quarterly_snapshots_keep_enough_history():
    assert market_macro.history_window("daily", 24) == 768
    # Weekly series get ~5 points per month (ICSA rule in plan section 21.2), not just 24 weeks.
    assert market_macro.history_window("weekly", 24) == 120
    assert market_macro.history_window("monthly", 24) == 24
    assert market_macro.history_window("quarterly", 24) == 24


def test_new_world_money_rate_and_credit_series_are_registered_and_cached_in_memory():
    expected = {"M2SL", "WALCL", "WTREGEN", "RRPONTSYD", "ECBASSETSW", "JPNASSETS",
                "SOFR", "DGS3MO", "DGS2", "T10Y2Y", "T10Y3M", "DFII10", "T10YIE", "ECBDFR", "IUDSOIA", "IRSTCI01JPM156N",
                "BAMLH0A0HYM2", "BAMLC0A0CM", "BAA10Y", "DRALACBS", "DRCCLACBS", "DRSFRMACBS", "DRBLACBS", "CORCCACBS",
                "STLFSI4", "NFCI"}
    assert expected <= set(market_macro.FRED_SERIES)
    # PostgreSQL has 100m CPU and save_observations selects per row: new series stay in process memory.
    assert expected | {"US_NET_LIQUIDITY", "EZ_M2_INDEX", "JP_M2", "TW_M2", "TW_M1B"} <= market_macro.FREE_CACHE_CODES
    assert market_macro.FRED_SERIES["DRCCLACBS"][2] == "quarterly"


def test_low_frequency_fred_series_are_not_refetched_within_a_day(monkeypatch):
    calls = []

    def fake_request(url, *args, **kwargs):
        code = market_macro.urllib.parse.parse_qs(market_macro.urllib.parse.urlparse(url).query)["series_id"][0]
        calls.append(code)
        return 200, json.dumps({"observations": [{"date": "2026-10-14", "value": "1"}]}).encode()

    monkeypatch.setattr(market_macro, "_request", fake_request)
    monkeypatch.setattr(market_macro, "FRED_KEY", "test-key")
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_macro.market_macro_db, "save_observations", lambda source, rows: len(rows))
    monkeypatch.setattr(market_macro.market_macro_db, "sessions", None)
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache(max_entries=256))
    service = market_macro.MarketMacroService()
    service._fetch_fred_observations()
    first = list(calls)
    calls.clear()
    service._fetch_fred_observations()
    assert "DRCCLACBS" in first and "WALCL" in first and "SOFR" in first
    # Second refresh six hours later: daily series again, weekly/monthly/quarterly cached ones skipped.
    assert "SOFR" in calls and "DGS10" in calls
    assert "DRCCLACBS" not in calls and "WALCL" not in calls and "M2SL" not in calls


def test_world_money_keeps_other_central_banks_when_one_fails(monkeypatch):
    fixtures = {"ECB": (FIXTURES / "ecb_m2_index.csv").read_bytes(),
                "CBC": (FIXTURES / "cbc_ef15m01.json").read_bytes()}

    def fake_request(key, url, **kwargs):
        source = key.split(":")[1]
        if source == "BoJ":
            raise RuntimeError("TimeoutError")
        return 200, fixtures[source]

    monkeypatch.setattr(market_macro, "_request_free_cached", fake_request)
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    finished = []
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: finished.append((args, kwargs)))
    service = market_macro.MarketMacroService()
    saved = []
    monkeypatch.setattr(service, "_cache_free_series", lambda rows, *args, **kwargs: saved.extend(rows) or len(rows))
    service._fetch_world_money()
    assert {row["code"] for row in saved} == {"EZ_M2_INDEX", "TW_M1B", "TW_M2"}
    assert finished[-1][0][1] == "success" and "BoJ" in finished[-1][1]["detail"]


# Liquidity series keep history since 2019 so the 2020 expansion, the 2022-23 contraction and the reverse repo
# draining from 2.5T to zero are on the chart; two years of data drew flat lines.
def test_liquidity_series_fetch_from_2019_and_others_keep_their_windows():
    today = market_macro.date(2026, 10, 17)
    for code in ("M2SL", "WALCL", "WTREGEN", "RRPONTSYD", "ECBASSETSW", "JPNASSETS"):
        assert market_macro.fred_observation_start(code, market_macro.FRED_SERIES[code][2], today) == "2019-01-01", code
    assert market_macro.fred_observation_start("SOFR", "daily", today) == "2024-10-17"
    assert market_macro.fred_observation_start("DRALACBS", "quarterly", today) == "2020-01-01"


def test_snapshot_keeps_all_liquidity_history_since_2019_but_trims_other_series():
    daily = [{"period": f"{year}-01-0{day}", "value": "1"} for year in range(2018, 2027) for day in (2, 3)]
    assert [row["period"][:4] for row in market_macro.snapshot_history("RRPONTSYD", "daily", daily, 24)][0] == "2019"
    assert len(market_macro.snapshot_history("RRPONTSYD", "daily", daily, 24)) == 16
    monthly = [{"period": f"{year}-{month:02d}", "value": "1"} for year in range(2018, 2027) for month in range(1, 13)]
    assert market_macro.snapshot_history("TW_M2", "monthly", monthly, 24)[0]["period"] == "2019-01"
    assert market_macro.snapshot_history("US_NET_LIQUIDITY", "weekly", monthly, 24)[0]["period"] == "2019-01"
    assert len(market_macro.snapshot_history("SOFR", "monthly", monthly, 24)) == 24


def test_local_cache_holds_every_series_plus_raw_source_responses():
    # 54 cached series plus ~13 raw source responses overflowed the old 64-entry LRU and evicted series.
    assert market_macro._macro_local_cache._max_entries >= len(market_macro.FREE_CACHE_CODES) + 32
