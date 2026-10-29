"""TAIEX futures roll cost above fair carry (台指期轉倉超額價差): pure parsing and arithmetic, no I/O.

    spread = F_next - F_near                       (daily settlement prices, TAIFEX)
    fair   = F_near * r * days / 365 - D           (r: CBC rediscount rate; days: near expiry to next expiry)
    excess = spread - fair

D is the index points of cash dividends going ex in (near expiry, next expiry]: cash per share x shares issued / divisor,
with divisor = listed market value / TAIEX on a reference day. A dividend that goes ex on the near expiry is already in
the near contract's settlement, so it is not in the window. Covered by tests/test_futures_roll.py; the market-macro
service fetches the inputs (`MarketMacroService._fetch_tx_roll_spread`).
"""
from __future__ import annotations

import calendar
import csv
import io
import re
from datetime import date, timedelta
from typing import Callable, Iterable

Dividend = tuple[date, str, float]  # ex-date, stock code, cash per share (NT$)


def third_wednesday(year: int, month: int) -> date:
    """TX monthly contracts expire on the third Wednesday (a holiday moves it; not modelled, see docs)."""
    first_weekday, _ = calendar.monthrange(year, month)
    return date(year, month, 1 + (2 - first_weekday) % 7 + 14)


def _number(value) -> float | None:
    raw = str(value or "").replace(",", "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _roc_date(value: str) -> date | None:
    match = re.fullmatch(r"(\d{2,3})年(\d{1,2})月(\d{1,2})日", str(value or "").strip())
    return date(int(match.group(1)) + 1911, int(match.group(2)), int(match.group(3))) if match else None


def parse_tx_settlements(document: str) -> dict[date, dict[str, float]]:
    """TAIFEX futDataDown CSV (commodity TX) as {trading day: {YYYYMM: settlement}}, regular session, monthly contracts."""
    days: dict[date, dict[str, float]] = {}
    for row in csv.DictReader(io.StringIO(document)):
        month = str(row.get("到期月份(週別)") or "").strip()
        if str(row.get("交易時段") or "").strip() != "一般" or not re.fullmatch(r"\d{6}", month):
            continue
        settlement = _number(row.get("結算價"))
        match = re.fullmatch(r"(\d{4})/(\d{2})/(\d{2})", str(row.get("交易日期") or "").strip())
        if settlement and match:
            days.setdefault(date(*map(int, match.groups())), {})[month] = settlement
    return days


def parse_shares(payload: Iterable[dict]) -> dict[str, float]:
    """TWSE open data t187ap03_L: listed companies' common shares issued."""
    shares = {}
    for row in payload:
        count = _number(row.get("已發行普通股數或TDR原股發行股數"))
        if count:
            shares[str(row.get("公司代號") or "").strip()] = count
    return shares


def index_divisor(prices: dict, shares: dict[str, float]) -> float | None:
    """Listed market value (close x shares issued, listed companies only) / TAIEX, from one MI_INDEX response."""
    level = None
    price_table = None
    for table in prices.get("tables") or []:
        fields = table.get("fields") or []
        if fields and fields[0] == "指數":
            level = next((_number(row[1]) for row in table.get("data") or [] if str(row[0]).strip() == "發行量加權股價指數"), level)
        if "證券代號" in fields and "收盤價" in fields:
            price_table = table
    if not level or not price_table:
        return None
    code_at, close_at = price_table["fields"].index("證券代號"), price_table["fields"].index("收盤價")
    value = 0.0
    for row in price_table.get("data") or []:
        close, code = _number(row[close_at]), str(row[code_at]).strip()
        if close and code in shares:
            value += close * shares[code]
    return value / level if value else None


def parse_past_dividends(payload: dict) -> list[Dividend]:
    """TWT49U (除權除息計算結果表): cash-only rows (息). 權息 rows give stock and cash as one number and are skipped."""
    fields = payload.get("fields") or []
    if "權值+息值" not in fields:
        return []
    day_at, code_at, value_at, kind_at = (fields.index(name) for name in ("資料日期", "股票代號", "權值+息值", "權/息"))
    rows = []
    for row in payload.get("data") or []:
        day, cash = _roc_date(row[day_at]), _number(row[value_at])
        if day and cash and str(row[kind_at]).strip() == "息":
            rows.append((day, str(row[code_at]).strip(), cash))
    return rows


def parse_upcoming_dividends(payload: dict) -> list[Dividend]:
    """TWT48U (除權除息預告表): announced cash dividends; placeholders ("待公告…") and zero cash are skipped."""
    fields = payload.get("fields") or []
    if "現金股利" not in fields:
        return []
    day_at, code_at, cash_at, kind_at = (fields.index(name) for name in ("除權除息日期", "股票代號", "現金股利", "除權息"))
    rows = []
    for row in payload.get("data") or []:
        day, cash = _roc_date(row[day_at]), _number(row[cash_at])
        if day and cash and "息" in str(row[kind_at]):
            rows.append((day, str(row[code_at]).strip(), cash))
    return rows


def dividend_points(dividends: Iterable[Dividend], shares: dict[str, float], divisor: float, after: date, through: date) -> float:
    """Index points of cash dividends with after < ex-date <= through; stocks without a share count (ETFs) are not in TAIEX."""
    return sum(cash * shares[code] for day, code, cash in dividends if after < day <= through and code in shares) / divisor


def _expiry(month: str) -> date:
    return third_wednesday(int(month[:4]), int(month[4:]))


def roll_rows(settlements: dict[date, dict[str, float]], dividends: list[Dividend], shares: dict[str, float],
              divisor: float, rate_on: Callable[[date], float | None]) -> list[dict]:
    """One row per trading day: near = first contract whose expiry is on or after the day, next = the one after it."""
    rows = []
    for day in sorted(settlements):
        months = sorted(month for month in settlements[day] if _expiry(month) >= day)
        rate = rate_on(day)
        if len(months) < 2 or rate is None:
            continue
        near, following = months[0], months[1]
        near_price, next_price = settlements[day][near], settlements[day][following]
        start, end = _expiry(near), _expiry(following)
        points = dividend_points(dividends, shares, divisor, start, end)
        fair = near_price * rate / 100 * (end - start).days / 365 - points
        spread = next_price - near_price
        rows.append({"period": day.isoformat(), "nearMonth": near, "nextMonth": following, "spread": spread,
                     "dividendPoints": points, "fair": fair, "excess": spread - fair})
    return rows


def month_ranges(today: date, months: int) -> list[tuple[date, date]]:
    """First and last day of the current month and the months before it, newest first (one TAIFEX request each)."""
    first = today.replace(day=1)
    ranges = []
    for _ in range(months):
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        ranges.append((first, min(last, today)))
        first = (first - timedelta(days=1)).replace(day=1)
    return ranges
