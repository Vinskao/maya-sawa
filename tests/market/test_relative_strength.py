"""2026-11-14: 連續跑贏／跑輸 vs TAIEX was only a prompt rule; the routines had no TAIEX daily data to compute it."""
from maya_sawa.services.relative_strength import closes_from_history, relative_streak

TAIEX = {"2026-11-09": 100.0, "2026-11-10": 101.0, "2026-11-11": 102.0, "2026-11-12": 101.0, "2026-11-13": 101.0}


def test_outperform_streak_and_compound_cumulative_gap():
    stock = {"2026-11-09": 50.0, "2026-11-10": 49.0, "2026-11-11": 50.0, "2026-11-12": 50.5, "2026-11-13": 51.0}
    out = relative_streak(stock, TAIEX)
    # 11-10 lags (-3pp); 11-11 +1.06, 11-12 +1.98, 11-13 +0.99 beat it
    assert out["status"] == "ok" and out["asOf"] == "2026-11-13"
    assert out["streakDays"] == 3 and out["streakStart"] == "2026-11-11" and not out["streakAtLeast"]
    assert out["todayGapPp"] == 0.99
    assert out["cumulativeGapPp"] == round((51 / 49 - 1) * 100 - (101 / 101 - 1) * 100, 2)


def test_missing_close_breaks_streak_and_latest_gap_is_pending():
    stock = {"2026-11-09": 50.0, "2026-11-10": 51.0, "2026-11-12": 52.0, "2026-11-13": 52.5}
    out = relative_streak(stock, TAIEX)
    assert out["streakDays"] == 1 and out["streakStart"] == "2026-11-13"   # 11-11 suspension stops the count
    assert relative_streak({"2026-11-12": 1.0}, TAIEX)["status"] == "pending"


def test_flat_gap_has_no_streak_and_window_start_is_flagged():
    flat = relative_streak({d: v / 2 for d, v in TAIEX.items()}, TAIEX)
    assert flat["streakDays"] == 0 and flat["cumulativeGapPp"] == 0.0
    lagging = relative_streak({d: 10.0 for d in TAIEX}, {d: 100 * 1.01 ** i for i, d in enumerate(TAIEX)})
    assert lagging["streakDays"] == -4 and lagging["streakAtLeast"]


def test_reads_listed_or_otc_close():
    points = [{"date": "2026-11-12", "sources": {"twse:daily-price": {"close": 10.5}}},
              {"date": "2026-11-13", "sources": {"tpex:daily-price": {"close": "11"}}},
              {"date": "2026-11-14", "sources": {"twse:institutional": {}}}]
    assert closes_from_history(points) == {"2026-11-12": 10.5, "2026-11-13": 11.0}
