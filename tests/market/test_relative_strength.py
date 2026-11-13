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


from maya_sawa.services.relative_strength import event_tracking

BENCH = {"2026-11-09": 100.0, "2026-11-10": 100.0, "2026-11-11": 100.0, "2026-11-12": 100.0, "2026-11-13": 100.0,
         "2026-11-16": 100.0}


def test_good_news_lag_runs_past_three_days_until_it_catches_up():
    stock = {"2026-11-09": 100.0, "2026-11-10": 99.0, "2026-11-11": 98.0, "2026-11-12": 97.5, "2026-11-13": 97.0,
             "2026-11-16": 97.5}
    out = event_tracking("2026-11-09T15:00", "positive", stock, BENCH)       # after the close -> reacts 11-10
    assert out["status"] == "ended" and out["firstDay"] == "2026-11-10" and out["divergingDays"] == 4
    assert out["endedOn"] == "2026-11-16" and out["cumulativeGapPp"] == -3.0 and out["notable"]


def test_news_before_close_reacts_same_day_and_no_divergence_is_not_tracked():
    stock = {"2026-11-09": 100.0, "2026-11-10": 101.0}
    assert event_tracking("2026-11-10T09:00", "positive", stock, BENCH)["status"] == "no-divergence"


def test_missing_close_leaves_run_pending_and_bad_news_mirrors():
    stock = {"2026-11-09": 100.0, "2026-11-10": 99.8, "2026-11-11": 99.6}
    out = event_tracking("2026-11-09T20:00", "positive", stock, BENCH)
    assert out["status"] == "pending" and out["divergingDays"] == 2 and not out["notable"]
    up = event_tracking("2026-11-09T20:00", "negative", {"2026-11-09": 100.0, "2026-11-10": 101.0}, BENCH)
    assert up["status"] == "pending" and up["divergingDays"] == 1 and up["notable"]
    assert event_tracking("2026-11-16T20:00", "positive", stock, BENCH)["status"] == "pending"
