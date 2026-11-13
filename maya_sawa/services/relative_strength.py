"""Daily relative strength of a Taiwan stock against TAIEX, computed on the server so the analysis routines only read it.

Rules (routines/market-taiwan-*.md 連續跑贏／跑輸):
- The benchmark's trading days are the calendar. A day's gap = stock return - TAIEX return, both from the previous
  benchmark trading day's close, in percentage points.
- A day where either close is missing (suspension, not yet collected) has no gap and breaks the streak.
- Streak: consecutive same-sign gaps ending at the latest day; an exactly flat gap ends it. Unrounded numbers decide.
- Cumulative gap: stock compound return minus TAIEX compound return over the streak, from the close before its first day.
- Closes are not adjusted for dividends or splits, so an ex-dividend day shows as underperformance (noted in output).
"""
from __future__ import annotations

from typing import Iterable


def _pct(after: float, before: float) -> float:
    return (after / before - 1) * 100


def relative_streak(stock: dict[str, float], benchmark: dict[str, float]) -> dict:
    """stock and benchmark map ISO date -> close. Returns the latest gap, signed streak length and cumulative gap."""
    days = sorted(day for day, value in benchmark.items() if value)
    gaps: list[tuple[str, float | None]] = []
    for before, after in zip(days, days[1:]):
        if stock.get(before) and stock.get(after):
            gaps.append((after, _pct(stock[after], stock[before]) - _pct(benchmark[after], benchmark[before])))
        else:
            gaps.append((after, None))
    if not gaps:
        return {"status": "insufficient", "asOf": days[-1] if days else None}
    as_of, latest = gaps[-1]
    if latest is None:
        return {"status": "pending", "asOf": as_of, "reason": "no stock close on the latest benchmark day"}
    sign = (latest > 0) - (latest < 0)
    length = 0
    if sign:
        for _, gap in reversed(gaps):
            if gap is None or (gap > 0) - (gap < 0) != sign:
                break
            length += 1
    start_index = len(days) - 1 - length          # close before the streak's first day
    base = days[start_index]
    cumulative = _pct(stock[as_of], stock[base]) - _pct(benchmark[as_of], benchmark[base]) if length else 0.0
    # The streak reached the start of the data window, so it may be longer than shown.
    at_least = length > 0 and start_index == 0
    return {"status": "ok", "asOf": as_of, "benchmark": "TAIEX", "todayGapPp": round(latest, 2),
            "streakDays": sign * length, "streakAtLeast": at_least, "streakStart": days[start_index + 1] if length else None,
            "cumulativeGapPp": round(cumulative, 2),
            "note": "closes are not dividend-adjusted; an ex-dividend day reads as underperformance"}


def closes_from_history(points: Iterable[dict]) -> dict[str, float]:
    """ISO date -> close from /dashboard/history points (twse or tpex daily price)."""
    closes = {}
    for point in points:
        for key in ("twse:daily-price", "tpex:daily-price"):
            close = (point.get("sources") or {}).get(key, {}).get("close")
            if close:
                closes[point["date"]] = float(close)
                break
    return closes
