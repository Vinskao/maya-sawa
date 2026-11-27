"""Rule-based Telegram warning when a watched Taiwan stock's new quarterly report shows a falling gross margin.

No AI is involved: the MOPS loop already stores each new quarterly income statement, build_fundamental_metrics
turns it into margin changes, and this module decides whether the latest quarter is worth an immediate message.
Rule: gross margin fell GROSS_MARGIN_DROP_PP points or more against the previous quarter, or fell two quarters in a row.
Each stock's report period is announced once (idempotent through the same store the analysis events use).
"""
import hashlib
import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)

GROSS_MARGIN_DROP_PP = 2.0
_ALERT_DAY = date(1970, 1, 2)  # stable primary-key date, distinct from the analysis-event day


def margin_alert(code: str, quarterly: list[dict[str, Any]]) -> dict[str, str] | None:
    """Judge only the newest quarter; returns {period, title, body} or None."""
    rows = [row for row in quarterly if row.get("grossMargin") is not None]
    if not rows:
        return None
    rows.sort(key=lambda row: row["period"])
    latest = rows[-1]
    change = latest.get("grossMarginQoQ")
    if change is None:
        return None
    previous = rows[-2] if len(rows) > 1 else None
    previous_change = previous.get("grossMarginQoQ") if previous else None
    steep = change <= -GROSS_MARGIN_DROP_PP
    streak = change < 0 and previous_change is not None and previous_change < 0
    if not (steep or streak):
        return None
    before = latest["grossMargin"] - change
    why = f"比上一季降 {abs(change):.1f} 點" if steep else f"連續兩季下滑（本季 {change:+.1f} 點、上季 {previous_change:+.1f} 點）"
    return {
        "period": latest["period"],
        "title": f"{code} 毛利率下滑（{latest['period']}）",
        "body": f"毛利率 {before:.1f}% → {latest['grossMargin']:.1f}%，{why}。可能是價格戰或成本上升，請看財報說明。",
    }


def alert_key(code: str, period: str) -> str:
    return "earnings-margin:" + hashlib.sha256(f"{code}:{period}".encode("utf-8")).hexdigest()[:32]


def notify_margin_drops(store, metrics_by_code: dict[str, list[dict]], send, names: dict[str, str] | None = None) -> list[str]:
    """Send one 'attention' message per newly reported quarter; returns the codes that were announced."""
    announced = []
    for code, quarterly in sorted(metrics_by_code.items()):
        alert = margin_alert(code, quarterly)
        if not alert:
            continue
        key = alert_key(code, alert["period"])
        if not store.record(key, _ALERT_DAY, ""):
            continue
        name = (names or {}).get(code)
        title = alert["title"].replace(code, f"{code} {name}", 1) if name else alert["title"]
        result = send("attention", title, alert["body"])
        if not result.get("sent"):
            store.release(key, _ALERT_DAY)  # not configured or failed: try again on the next pass
            continue
        announced.append(code)
    return announced
