"""U.S. Treasury yields reach the dashboard a business day earlier from the Treasury's own daily curve.

2026-11-03: the yield-curve node showed 10-year 4.94% (2026-10-30) although 11-02 had closed at 4.91%. FRED's DGS10, DGS2,
DGS3MO and DFII10 (Fed H.15) publish the next evening, while the Treasury's daily par and real yield curves are out the
same day; FRED's own T10Y2Y already had 11-02. The numbers are the same series (the 10-30 values match FRED exactly), so
the Treasury rows only extend the FRED history by the days FRED does not have yet.
"""
import json
from pathlib import Path

import pytest

from maya_sawa.services import market_macro

FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
PAR = (FIXTURES / "treasury_par_yield_2026-11-02.csv").read_bytes()
REAL = (FIXTURES / "treasury_real_yield_2026-11-02.csv").read_bytes()


def test_the_par_curve_csv_becomes_daily_rows_for_the_tracked_maturities_only():
    rows = market_macro.treasury_curve_rows(PAR, market_macro.TREASURY_PAR_COLUMNS)
    assert set(rows) == {"DGS3MO", "DGS2", "DGS10"}
    assert [r["period"] for r in rows["DGS10"]] == ["2026-10-29", "2026-10-30", "2026-11-02"]          # MM/DD/YYYY -> ISO, oldest first
    assert [r["value"] for r in rows["DGS10"]] == ["4.98", "4.94", "4.91"]
    assert [r["value"] for r in rows["DGS2"]][-1] == "4.59" and [r["value"] for r in rows["DGS3MO"]][-1] == "4.21"
    assert all(r["code"] == "DGS10" for r in rows["DGS10"])


def test_the_real_yield_curve_gives_the_10_year_tips_yield():
    rows = market_macro.treasury_curve_rows(REAL, market_macro.TREASURY_REAL_COLUMNS)
    assert set(rows) == {"DFII10"}
    assert [(r["period"], r["value"]) for r in rows["DFII10"]][-2:] == [("2026-10-30", "2.60"), ("2026-11-02", "2.62")]


def test_blank_n_a_unparseable_dates_and_missing_columns_are_skipped_not_fatal():
    raw = b'Date,"3 Mo","2 Yr","10 Yr"\n11/02/2026,4.21,,4.91\n11/01/2026,N/A,4.5,4.9\nnot-a-date,4.1,4.4,4.8\n10/30/2026,4.16,4.56,\n'
    rows = market_macro.treasury_curve_rows(raw, market_macro.TREASURY_PAR_COLUMNS)
    assert [r["period"] for r in rows["DGS3MO"]] == ["2026-10-30", "2026-11-02"]
    assert [r["period"] for r in rows["DGS2"]] == ["2026-10-30", "2026-11-01"]
    assert [r["period"] for r in rows["DGS10"]] == ["2026-11-01", "2026-11-02"]
    assert market_macro.treasury_curve_rows(b"", market_macro.TREASURY_PAR_COLUMNS) == {}
    assert market_macro.treasury_curve_rows(b"<html>Access denied</html>", market_macro.TREASURY_PAR_COLUMNS) == {}
    assert market_macro.treasury_curve_rows(b'Date,"1 Mo"\n11/02/2026,4.05\n', market_macro.TREASURY_PAR_COLUMNS) == {}   # no tracked column


def test_treasury_rows_only_extend_fred_never_overwrite_it():
    fred = [{"code": "DGS10", "period": "2026-10-29", "value": 4.98}, {"code": "DGS10", "period": "2026-10-30", "value": 4.94}]
    treasury = [{"code": "DGS10", "period": "2026-10-30", "value": 4.99}, {"code": "DGS10", "period": "2026-11-02", "value": 4.91}]
    merged = market_macro.merge_newer_rows(fred, treasury)
    assert [(r["period"], r["value"]) for r in merged] == [("2026-10-29", 4.98), ("2026-10-30", 4.94), ("2026-11-02", 4.91)]
    assert market_macro.merge_newer_rows([], treasury) == treasury                      # a series FRED returned nothing for
    assert market_macro.merge_newer_rows(fred, []) == fred


def run_fred_refresh(monkeypatch, treasury_ok=True):
    saved_persisted = {}

    def fake_request(url, *args, **kwargs):
        if "treasury.gov" in url:
            if not treasury_ok:
                raise RuntimeError("upstream_http_503")
            return 200, (REAL if "real_yield" in url else PAR)
        code = market_macro.urllib.parse.parse_qs(market_macro.urllib.parse.urlparse(url).query)["series_id"][0]
        values = {"DGS10": "4.94", "DGS2": "4.56", "DGS3MO": "4.16", "DFII10": "2.60", "T10Y2Y": "0.38"}
        return 200, json.dumps({"observations": [{"date": "2026-10-29", "value": "4.0"}, {"date": "2026-10-30", "value": values.get(code, "1")}]}).encode()

    monkeypatch.setattr(market_macro, "_request", fake_request)
    monkeypatch.setattr(market_macro, "FRED_KEY", "test-key")
    monkeypatch.setattr(market_macro.market_macro_db, "reserve_source_call", lambda *args, **kwargs: 1)
    monkeypatch.setattr(market_macro.market_macro_db, "finish_source_call", lambda *args, **kwargs: None)
    monkeypatch.setattr(market_macro.market_macro_db, "save_observations",
                        lambda source, rows: saved_persisted.setdefault(rows[0]["code"], rows) and len(rows) if rows else 0)
    monkeypatch.setattr(market_macro.market_macro_db, "sessions", None)
    monkeypatch.setattr(market_macro, "_macro_local_cache", market_macro.LocalTTLCache(max_entries=256))
    market_macro.MarketMacroService()._fetch_fred_observations()
    history = lambda code: [(r["period"], r["value"]) for r in (market_macro._macro_local_cache.get(f"series:{code}") or {}).get("history", [])]
    return history, saved_persisted


def test_the_fred_refresh_adds_the_days_fred_does_not_have_yet(monkeypatch):
    history, persisted = run_fred_refresh(monkeypatch)
    assert history("DGS2")[-2:] == [("2026-10-30", "4.56"), ("2026-11-02", "4.59")]          # FRED's 10-30 kept, Treasury's 11-02 added
    assert history("DGS3MO")[-1] == ("2026-11-02", "4.21")
    assert history("DFII10")[-1] == ("2026-11-02", "2.62")
    assert [(r["period"], r["value"]) for r in persisted["DGS10"]][-2:] == [("2026-10-30", "4.94"), ("2026-11-02", "4.91")]   # the persisted series too
    assert history("T10Y2Y")[-1] == ("2026-10-30", "0.38")                                        # series Treasury does not carry are untouched


def test_a_treasury_outage_leaves_the_fred_refresh_intact(monkeypatch):
    history, persisted = run_fred_refresh(monkeypatch, treasury_ok=False)
    assert history("DGS2")[-1] == ("2026-10-30", "4.56")
    assert [r["period"] for r in persisted["DGS10"]][-1] == "2026-10-30"
