"""Whose turn a scheduled analysis run is: two Sonnet runs, then one Opus (stdlib only; run first by both routines).

Each analysis routine has an Opus twin on the same cron. Both start with this script; the one whose model is not
printed stops at once, so every scheduled day gets exactly one analysis. Runs are counted on the routine's own cron
days (Taipei) from Monday 2026-10-26, so the cadence holds across weekends and month ends. Covered by
tests/test_routine_turn.py.

    python3 maya_sawa/public_scripts/routine_turn.py taiwan     # prints "sonnet 4" or "opus 6"
"""
import sys
from datetime import date, datetime, timedelta, timezone

ANCHOR = date(2026, 10, 26)
TAIPEI = timezone(timedelta(hours=8))
# Taipei weekdays (Mon=0): Taiwan Friday 21:15; US and macro Tue-Sat 07:30.
SCHEDULES = {"taiwan": frozenset({4}), "us": frozenset(range(1, 6))}
LATE_START = timedelta(hours=6)  # a start delayed past midnight still belongs to the scheduled evening


def run_day(now: datetime) -> date:
    return (now.astimezone(TAIPEI) - LATE_START).date()


def run_number(routine: str, day: date) -> int:
    if day < ANCHOR:
        raise ValueError(f"{day} is before {ANCHOR}")
    weekdays = SCHEDULES[routine]
    return sum(1 for offset in range((day - ANCHOR).days + 1) if (ANCHOR + timedelta(days=offset)).weekday() in weekdays)


def turn(routine: str, day: date) -> str:
    return "opus" if run_number(routine, day) % 3 == 0 else "sonnet"


def main(argv, now: datetime | None = None) -> int:
    if len(argv) != 1 or argv[0] not in SCHEDULES:
        print(f"usage: routine_turn.py {'|'.join(SCHEDULES)}")
        return 2
    day = run_day(now or datetime.now(timezone.utc))
    print(turn(argv[0], day), run_number(argv[0], day), day.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
