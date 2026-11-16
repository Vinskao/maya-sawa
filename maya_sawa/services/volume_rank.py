"""Where a stock's trading volume ranks among its trailing year of daily volumes (docs/INTRADAY_ALERTS.md).

Pure rules: rank, the top-10 / top-5 flags, and the per-day report for this week. A stock locked at limit-up or limit-down
trades very little, so every day of the week is ranked, not just today.
"""
from datetime import date

TRAILING_DAYS = 250  # about one year of trading days, not counting today
MIN_HISTORY_DAYS = 120  # with less history than this a rank says little, so no volume alert
TOP_LEVELS = (10, 5)  # alert when the rank reaches the top 10, then the top 5
WEEKDAYS = "一二三四五六日"


def rank_of(volume: float, volumes: list[float]) -> int:
    """1 = the largest day of the window; ties do not push a day down."""
    return 1 + sum(1 for other in volumes if other > volume)


def flag_for(rank: int) -> str | None:
    return "top5" if rank <= 5 else "top10" if rank <= 10 else None


def trailing_volumes(history: list, today: date) -> list[float]:
    """Daily volumes of the last year before `today` (today's own, still running, is never part of the window)."""
    days = sorted((str(day), float(volume)) for day, volume in history if str(day) < today.isoformat() and volume)
    return [volume for _, volume in days][-TRAILING_DAYS:]


def week_summary(history: list, today: date, week_start: date, today_volume: float | None) -> list[dict]:
    """Each trading day of this week so far (Monday up to today) with its volume rank against the trailing year."""
    volumes = trailing_volumes(history, today)
    if not volumes:
        return []
    days = [(str(day), float(volume)) for day, volume in sorted(history)
            if week_start.isoformat() <= str(day) < today.isoformat() and volume]
    if today_volume:
        days.append((today.isoformat(), float(today_volume)))
    rows = []
    for day, volume in days:
        rank = rank_of(volume, volumes)
        rows.append({"date": day, "weekday": f"週{WEEKDAYS[date.fromisoformat(day).weekday()]}", "volume": int(volume),
                     "rank": rank, "flag": flag_for(rank), "today": day == today.isoformat()})
    return rows
