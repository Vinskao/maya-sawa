"""2026-10-29: the owner wants the stock and macro analysis routines to alternate models, two Sonnet runs then one Opus.

A routine's model is fixed, so each routine has an Opus twin on the same cron; both start by asking routine_turn.py
whose turn the scheduled run is, and the other one stops at once. Runs are counted on each routine's own cron days
from Monday 2026-10-26, so the cadence is exact across weekends and month ends.
"""
import importlib.util
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

# Loaded by path like report_routine_usage.py: public_scripts is a folder of standalone stdlib scripts, not a package.
_spec = importlib.util.spec_from_file_location(
    "routine_turn", Path(__file__).resolve().parents[1] / "maya_sawa" / "public_scripts" / "routine_turn.py")
routine_turn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(routine_turn)


def taiwan_turns(*days):
    return [routine_turn.turn("taiwan", date(2026, *day)) for day in days]


def test_the_taiwan_routine_alternates_two_sonnet_runs_then_one_opus_across_the_weekend():
    # Mon 10/26 … Fri 10/30, then Mon 11/2 … Wed 11/4 (Taipei weekday sessions).
    assert taiwan_turns((10, 26), (10, 27), (10, 28), (10, 29), (10, 30), (11, 2), (11, 3), (11, 4)) == [
        "sonnet", "sonnet", "opus", "sonnet", "sonnet", "opus", "sonnet", "sonnet"]


def test_the_us_and_macro_routine_counts_its_own_tuesday_to_saturday_runs():
    turns = [routine_turn.turn("us", date(2026, *day)) for day in ((10, 27), (10, 28), (10, 29), (10, 30), (10, 31), (11, 3))]
    assert turns == ["sonnet", "sonnet", "opus", "sonnet", "sonnet", "opus"]


def test_one_run_in_three_is_opus_over_a_long_stretch_including_month_ends():
    days = [date.fromordinal(day) for day in range(date(2026, 10, 26).toordinal(), date(2027, 10, 26).toordinal())]
    turns = [routine_turn.turn("taiwan", day) for day in days if day.weekday() < 5]
    assert all(turns[index:index + 3] == ["sonnet", "sonnet", "opus"] for index in range(0, len(turns) - 2, 3))


def test_a_late_start_still_counts_as_the_scheduled_day():
    # The Taiwan cron is 21:15 Taipei; a start delayed past midnight belongs to the previous evening's run.
    late = datetime(2026, 10, 28, 17, 30, tzinfo=timezone.utc)          # 01:30 Taipei on 10/29
    assert routine_turn.run_day(late) == date(2026, 10, 28)
    assert routine_turn.run_day(datetime(2026, 10, 28, 23, 30, tzinfo=timezone.utc)) == date(2026, 10, 29)  # US 07:30


def test_the_command_prints_whose_turn_it_is(capsys):
    assert routine_turn.main(["taiwan"], now=datetime(2026, 10, 28, 13, 15, tzinfo=timezone.utc)) == 0
    assert capsys.readouterr().out.split()[0] == "opus"
    assert routine_turn.main(["nope"]) == 2


def test_days_before_the_anchor_are_rejected():
    with pytest.raises(ValueError):
        routine_turn.turn("taiwan", date(2026, 10, 25))
