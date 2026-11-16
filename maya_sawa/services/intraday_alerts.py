"""Intraday move alerts to Telegram (docs/INTRADAY_ALERTS.md).

Watches the quotes the Shioaji refresh loop already fetches (holdings, custom and watch symbols, plus every stock held or traded since Monday of this week) and tells the owner when
a stock moves ±5% from the prior close (again at ±7%, ±9%), falls 5 points from its day high (+10% -> +5% counts), or
bounces 5 points from its day low. Both directions are reported; every situation is reported once per day.
Pure rules in `evaluate`; `IntradayAlertMonitor` keeps the per-day state and sends through telegram_notify.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import telegram_notify

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
LEVELS = (5, 7, 9)  # Taiwan stocks are limited to ±10% a day
SWING = 5.0  # points of change-percent from the day's high / low
EPS = 1e-9


def in_trading_hours(now: datetime) -> bool:
    local = now.astimezone(TAIPEI)
    return local.weekday() < 5 and (9, 0) <= (local.hour, local.minute) <= (13, 30)


def week_start(now: datetime) -> datetime:
    """Monday 00:00 Taipei of the week `now` is in: stocks traded since then stay on the alert list after they are sold."""
    local = now.astimezone(TAIPEI)
    return (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _signed(pct: float) -> str:
    return f"{pct:+.1f}%"


def _alert(telegram: str, kind: str, quote: dict, title: str, body: str, **extra) -> dict:
    label = f"{quote['symbol']} {quote.get('name') or ''}".strip()
    return {"telegram": telegram, "kind": kind, "symbol": quote["symbol"], "title": f"{label} {title}", "body": body,
            "pct": float(quote["changePercent"]), **extra}


def evaluate(state: dict, quote: dict, now: datetime) -> tuple[dict, list[dict]]:
    """Return (new state, alerts) for one quote. `state` maps symbol -> that stock's state for today."""
    symbol = str(quote.get("symbol", "")).upper()
    if quote.get("productType") != "stock" or not symbol or not float(quote.get("close") or 0):
        return state, []
    local = now.astimezone(TAIPEI)
    stamp = str(quote.get("timestamp") or "")
    if stamp and stamp[:10] != local.date().isoformat():
        return state, []  # yesterday's snapshot on a market holiday
    pct, today = float(quote.get("changePercent") or 0), local.date().isoformat()
    quote = {**quote, "symbol": symbol}
    own = state.get(symbol)
    if not own or own.get("day") != today:
        own = {"day": today, "high": pct, "low": pct, "up": [], "down": []}
    own = {**own, "up": list(own["up"]), "down": list(own["down"])}
    price = float(quote["close"])
    alerts = []

    crossed_up = [lv for lv in LEVELS if pct >= lv - EPS and lv not in own["up"]]
    if crossed_up:
        own["up"] += crossed_up
        alerts.append(_alert("update", "rise", quote, f"盤中上漲 {_signed(pct)}",
                             f"{_signed(pct)}，現價 {price:g}（較前一日收盤漲超過 {crossed_up[-1]}%）",
                             direction="up", level=crossed_up[-1]))
    crossed_down = [lv for lv in LEVELS if pct <= -lv + EPS and lv not in own["down"]]
    if crossed_down:
        own["down"] += crossed_down
        alerts.append(_alert("attention", "fall", quote, f"盤中下跌 {_signed(pct)}",
                             f"{_signed(pct)}，現價 {price:g}（較前一日收盤跌超過 {crossed_down[-1]}%）",
                             direction="down", level=crossed_down[-1]))

    own["high"], own["low"] = max(own["high"], pct), min(own["low"], pct)
    if own["high"] - pct >= SWING - EPS:
        alerts.append(_alert("attention", "pullback", quote, f"自盤中高點回落 {own['high'] - pct:.1f} 點",
                             f"盤中最高 {_signed(own['high'])} → 現在 {_signed(pct)}，現價 {price:g}", high=own["high"], direction="down"))
        own["high"] = pct  # the next pullback has to be another full swing from here, or from a new high
    if pct - own["low"] >= SWING - EPS:
        alerts.append(_alert("update", "bounce", quote, f"自盤中低點反彈 {pct - own['low']:.1f} 點",
                             f"盤中最低 {_signed(own['low'])} → 現在 {_signed(pct)}，現價 {price:g}", low=own["low"], direction="up"))
        own["low"] = pct
    return {**state, symbol: own}, alerts


def notify(alerts: list[dict]) -> int:
    """Send every alert to Telegram; one failing message never blocks the rest. Returns how many were sent."""
    sent = 0
    for alert in alerts:
        try:
            if telegram_notify.send(alert["telegram"], alert["title"], alert["body"]).get("sent"):
                sent += 1
        except Exception:
            logger.warning("Intraday alert could not be sent: %s", alert["title"], exc_info=True)
    return sent


class IntradayAlertMonitor:
    """Called after each quote refresh. State lives in memory; a restart mid-session may repeat a level once."""

    def __init__(self):
        self._state: dict = {}

    async def check(self, quotes: list[dict], now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(TAIPEI)
        if not in_trading_hours(now):
            return []
        alerts = []
        for quote in quotes:
            self._state, found = evaluate(self._state, quote, now)
            alerts += found
        if alerts:
            await asyncio.to_thread(notify, alerts)
        return alerts


intraday_alert_monitor = IntradayAlertMonitor()
