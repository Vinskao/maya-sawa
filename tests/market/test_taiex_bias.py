from maya_sawa.services.taiex_bias import BIAS_WINDOWS, bias_series


def test_bias_is_percent_above_the_moving_average():
    closes = {f"2026-01-{day:02d}": float(value) for day, value in zip(range(1, 6), [10, 10, 10, 10, 20])}
    assert bias_series(closes, 5) == {"2026-01-05": "66.67"}   # average 12, 20 / 12 - 1


def test_bias_starts_once_the_window_is_full_and_rolls():
    closes = {f"2026-01-{day:02d}": float(value) for day, value in zip(range(1, 5), [10, 20, 30, 60])}
    assert bias_series(closes, 2) == {"2026-01-02": "33.33", "2026-01-03": "20.00", "2026-01-04": "33.33"}


def test_bias_skips_bad_closes_and_short_history():
    assert bias_series({"2026-01-01": 100.0}, 20) == {}
    assert bias_series({"2026-01-01": 0.0, "2026-01-02": 100.0}, 1) == {"2026-01-02": "0.00"}


def test_windows_are_month_quarter_year_lines():
    assert BIAS_WINDOWS == {20: "TW_TAIEX_BIAS_20", 60: "TW_TAIEX_BIAS_60", 120: "TW_TAIEX_BIAS_120", 240: "TW_TAIEX_BIAS_240"}
