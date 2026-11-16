from datetime import date

from maya_sawa.services.market_macro import fred_observation_start


def test_fred_daily_and_weekly_history_cover_three_calendar_years():
    today = date(2026, 11, 16)
    assert fred_observation_start("DGS10", "daily", today) == "2023-11-01"
    assert fred_observation_start("ICSA", "weekly", today) == "2023-11-01"
