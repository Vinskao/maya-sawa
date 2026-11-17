"""Intraday move alerts to Telegram (docs/INTRADAY_ALERTS.md).

Covers Taiwan stocks (Shioaji quotes the refresh loop already fetches) and Japanese stocks (Yahoo daily chart, polled here).
Scope: holdings, custom and watch symbols, plus every stock held or traded since Monday of this week.
Alerts: ±5% from the prior close (again at ±7%, ±9%), a 5-point pullback from the day's high (+10% -> +5% counts), a 5-point
bounce from the day's low. Any ±5% alert that follows a ±5% day in the same direction (streak) or in the opposite
direction (next-day reversal) says so. Pure rules in `evaluate`; `IntradayAlertMonitor` keeps per-day state and sends.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import telegram_notify, volume_rank

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
TOKYO = ZoneInfo("Asia/Tokyo")
MARKETS = {  # timezone, session (open, close) in that market's local clock, label for non-Taiwan stocks
    "TW": (TAIPEI, ((9, 0), (13, 30)), ""),
    "JP": (TOKYO, ((9, 0), (15, 30)), "日股"),
}
LEVELS = (5, 7, 9)  # Taiwan stocks are limited to ±10% a day
BIG_DAY = 5.0  # a day counts toward a streak / reversal when it moved at least this much
SWING = 5.0  # points of change-percent from the day's high / low
HISTORY_DAYS = 6
JAPAN_POLL = timedelta(seconds=120)
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
PRICE_KINDS = ("rise", "fall", "pullback", "bounce")
INDEX_LEVELS, INDEX_SWING, INDEX_BIG_DAY = (2, 3, 5), 2.0, 3.0  # a whole-market index moves far less than a single stock
INDEX_POLL = timedelta(seconds=60)
INDEX_CODE, INDEX_YAHOO, INDEX_NAME = "TAIEX", "^TWII", "加權指數"
LIMIT_DAY = 9.5  # percent: a move this large is probably a locked limit-up / limit-down, where volume is tiny
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
EPS = 1e-9


def in_trading_hours(now: datetime, market: str = "TW") -> bool:
    tz, (opens, closes), _ = MARKETS[market]
    local = now.astimezone(tz)
    return local.weekday() < 5 and opens <= (local.hour, local.minute) <= closes


def week_start(now: datetime) -> datetime:
    """Monday 00:00 Taipei of the week `now` is in: stocks traded since then stay on the alert list after they are sold."""
    local = now.astimezone(TAIPEI)
    return (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _signed(pct: float) -> str:
    return f"{pct:+.1f}%"


def _label(quote: dict) -> str:
    name = f"{quote['symbol']} {quote.get('name') or ''}".strip()
    market = MARKETS.get(quote.get("market") or "TW", MARKETS["TW"])[2]
    return f"{name}（{market}）" if market else name


def _alert(telegram: str, kind: str, quote: dict, title: str, body: str, **extra) -> dict:
    return {"telegram": telegram, "kind": kind, "symbol": quote["symbol"], "market": quote.get("market") or "TW",
            "title": f"{_label(quote)} {title}", "body": body, "pct": float(quote["changePercent"]), **extra}


def _special(pct: float, history: list[float], big: float = BIG_DAY) -> dict:
    """What earlier big days say about today's ±5% move: a streak in the same direction, or a reversal of yesterday."""
    sign = 1 if pct > 0 else -1
    streak = 0
    for day in reversed(history):
        if day * sign >= big - EPS:
            streak += 1
        else:
            break
    if streak:
        return {"streak": streak + 1, "recent": history[-streak:]}
    if history and history[-1] * sign <= -big + EPS:
        return {"reversal": True, "recent": history[-1:]}
    return {}


def _move_alert(quote: dict, pct: float, level: int, history: list[float]) -> dict:
    up, price = pct > 0, float(quote["close"])
    verb = "上漲" if up else "下跌"
    big = float(quote.get("bigDay") or BIG_DAY)
    special = _special(pct, history, big)
    note, title = "", f"盤中{verb} {_signed(pct)}"
    if "streak" in special:
        days = " → ".join(_signed(d) for d in special["recent"]) + f" → 今天 {_signed(pct)}"
        title = f"⚡ 連續 {special['streak']} 天{'漲' if up else '跌'}超過 {big:g}%（今天{_signed(pct)}）"
        note = f"\n⚡ 連續 {special['streak']} 天單日{'漲' if up else '跌'}幅超過 {big:g}%：{days}"
    elif special.get("reversal"):
        title = f"⚡ 隔日反向 {_signed(pct)}（前一日 {_signed(special['recent'][0])}）"
        note = f"\n⚡ 隔日反向：前一日 {_signed(special['recent'][0])}，今天 {_signed(pct)}，反向超過 {big:g}%"
    return _alert("attention" if special or not up else "update", "rise" if up else "fall", quote, title,
                  f"{_signed(pct)}，現價 {price:g}（較前一日收盤{'漲' if up else '跌'}超過 {level}%）{note}",
                  direction="up" if up else "down", level=level, **{k: v for k, v in special.items() if k != "recent"})


def evaluate(state: dict, quote: dict, now: datetime) -> tuple[dict, list[dict]]:
    """Return (new state, alerts) for one quote. `quote["history"]` holds the completed days' change-percents, oldest first."""
    market = quote.get("market") or "TW"
    symbol = str(quote.get("symbol", "")).upper()
    if market not in MARKETS or quote.get("productType") not in ("stock", "index") or not symbol or not float(quote.get("close") or 0):
        return state, []
    tz = MARKETS[market][0]
    local = now.astimezone(tz)
    stamp = str(quote.get("timestamp") or "")
    if stamp and stamp[:10] != local.date().isoformat():
        return state, []  # yesterday's snapshot on a market holiday
    pct, today = float(quote.get("changePercent") or 0), local.date().isoformat()
    quote = {**quote, "symbol": symbol}
    history = [float(d) for d in quote.get("history") or []][-HISTORY_DAYS:]
    key = f"{market}:{symbol}"
    own = state.get(key)
    if not own or own.get("day") != today:
        own = {"day": today, "high": pct, "low": pct, "up": [], "down": []}
    own = {**own, "up": list(own["up"]), "down": list(own["down"]), "volume": list(own.get("volume", []))}
    price = float(quote["close"])
    alerts = []

    levels, swing = quote.get("levels") or LEVELS, float(quote.get("swing") or SWING)
    crossed_up = [lv for lv in levels if pct >= lv - EPS and lv not in own["up"]]
    if crossed_up:
        own["up"] += crossed_up
        alerts.append(_move_alert(quote, pct, crossed_up[-1], history))
    crossed_down = [lv for lv in levels if pct <= -lv + EPS and lv not in own["down"]]
    if crossed_down:
        own["down"] += crossed_down
        alerts.append(_move_alert(quote, pct, crossed_down[-1], history))

    own["high"], own["low"] = max(own["high"], pct), min(own["low"], pct)
    if own["high"] - pct >= swing - EPS:
        alerts.append(_alert("attention", "pullback", quote, f"自盤中高點回落 {own['high'] - pct:.1f} 點",
                             f"盤中最高 {_signed(own['high'])} → 現在 {_signed(pct)}，現價 {price:g}", high=own["high"], direction="down"))
        own["high"] = pct  # the next pullback has to be another full swing from here, or from a new high
    if pct - own["low"] >= swing - EPS:
        alerts.append(_alert("update", "bounce", quote, f"自盤中低點反彈 {pct - own['low']:.1f} 點",
                             f"盤中最低 {_signed(own['low'])} → 現在 {_signed(pct)}，現價 {price:g}", low=own["low"], direction="up"))
        own["low"] = pct
    volume = _volume_alerts(own, quote, today, local, pct)
    if volume:
        alerts.append(volume)
    note = _volume_note(quote, local, pct)
    if note:
        for alert in alerts:
            if alert["kind"] in PRICE_KINDS:
                alert["body"] += f"\n{note}"
    return {**state, key: own}, alerts


def _volume_context(quote: dict, local: datetime):
    """(today's rank, trailing volumes, this week's day report), or None without enough volume history."""
    running = quote.get("volumeShares")
    volumes = volume_rank.trailing_volumes(quote.get("volumeHistory") or [], local.date())
    if not running or len(volumes) < volume_rank.MIN_HISTORY_DAYS:
        return None
    today = local.date()
    week = volume_rank.week_summary(quote["volumeHistory"], today, today - timedelta(days=today.weekday()), running)
    return volume_rank.rank_of(running, volumes), volumes, week


def _volume_alerts(own: dict, quote: dict, today: str, local: datetime, pct: float) -> dict | None:
    """Fires when today's running volume reaches the top 10, then the top 5, of the trailing year (once each per day)."""
    context = _volume_context(quote, local)
    if context is None:
        return None
    rank, volumes, week = context
    fired = own.setdefault("volume", [])
    reached = [level for level in volume_rank.TOP_LEVELS if rank <= level and level not in fired]
    if not reached:
        return None
    level = min(reached)
    fired.extend(reached)
    running = int(quote["volumeShares"])
    cutoffs = sorted(volumes, reverse=True)
    return _alert("attention", "volume", quote, f"成交量進入近一年前 {level} 大（第 {rank} 名）",
                  f"今日累計 {running:,} 股，近一年第 {rank} 大（前 10 門檻 {int(cutoffs[9]):,} 股、前 5 門檻 {int(cutoffs[4]):,} 股）\n{_week_line(week)}",
                  level=level, rank=rank, direction="up")


def _week_line(week: list[dict]) -> str:
    parts = []
    for day in week:
        label = f"{day['weekday']}{'（今日）' if day['today'] else ''}"
        mark = {"top5": "，前 5", "top10": "，前 10"}.get(day["flag"], "")
        parts.append(f"{label} 第 {day['rank']} 名{mark}")
    return "本週成交量排名（近一年）：" + "、".join(parts) if parts else ""


def _volume_note(quote: dict, local: datetime, pct: float) -> str:
    """The volume line every price alert carries: today's rank and each day of this week, with a limit-day reminder."""
    context = _volume_context(quote, local)
    if context is None:
        return ""
    rank, _, week = context
    status = "進入前 5" if rank <= 5 else "進入前 10" if rank <= 10 else "未進前 10"
    lines = [f"成交量（近一年排名）：今日第 {rank} 名（{status}）"]
    past = [day for day in week if not day["today"]]
    if past:
        lines.append(_week_line(past).replace("本週成交量排名（近一年）：", "本週前幾日："))
        flagged = [day for day in week if day["flag"]]
        if flagged:
            lines.append("本週進入前 10 的有：" + "、".join(f"{day['weekday']}第 {day['rank']} 名" for day in flagged))
    if abs(pct) >= LIMIT_DAY:
        lines.append("漲跌停時成交量常很小，所以本週各日都列出。")
    return "\n".join(lines)


# ---- data: Japanese quotes (Yahoo daily chart) and Taiwan daily history (official closes) ----

def _pcts(closes: list[float]) -> list[float]:
    return [round((closes[i] / closes[i - 1] - 1) * 100, 2) for i in range(1, len(closes)) if closes[i - 1]]


def parse_yahoo_chart(payload: dict, code: str, today: date, name: str = "") -> dict | None:
    """Today's quote plus the completed days before it from a Yahoo daily chart; None when there is no session today."""
    try:
        result = payload["chart"]["result"][0]
        meta, stamps = result["meta"], result["timestamp"]
        closes = result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return None
    volumes = (result["indicators"]["quote"][0].get("volume") or [])
    volumes += [None] * (len(stamps) - len(volumes))
    daily = [(datetime.fromtimestamp(t, TOKYO).date(), float(c), v) for t, c, v in zip(stamps, closes, volumes)
             if isinstance(c, (int, float)) and c > 0]
    rows = [(day, close) for day, close, _ in daily]
    if len(rows) < 2 or rows[-1][0] != today:
        return None
    price = float(meta.get("regularMarketPrice") or rows[-1][1])
    previous = rows[-2][1]
    stamp = meta.get("regularMarketTime")
    return {"symbol": code.upper(), "name": name or meta.get("shortName") or "", "productType": "stock", "market": "JP",
            "close": price, "changePercent": round((price / previous - 1) * 100, 2),
            "timestamp": (datetime.fromtimestamp(stamp, TOKYO) if stamp else datetime.combine(today, datetime.min.time(), TOKYO)).isoformat(),
            "history": _pcts([c for _, c in rows[:-1]])[-HISTORY_DAYS:],
            "volumeShares": int(daily[-1][2]) if daily[-1][2] else None,
            "volumeHistory": [[day.isoformat(), int(v)] for day, _, v in daily[:-1] if v]}


def parse_yahoo_volumes(payload: dict, today: date) -> tuple[list, int | None]:
    """([[iso day, shares]] of days before `today`, today's running volume or None) from a Yahoo daily chart, days in Tokyo time."""
    try:
        result = payload["chart"]["result"][0]
        stamps, volumes = result["timestamp"], result["indicators"]["quote"][0].get("volume") or []
    except (KeyError, IndexError, TypeError):
        return [], None
    rows, live = [], None
    for stamp, volume in zip(stamps, volumes):
        if not volume:
            continue
        day = datetime.fromtimestamp(stamp, TOKYO).date()
        if day < today:
            rows.append([day.isoformat(), int(volume)])
        elif day == today:
            live = int(volume)
    return rows, live


def japan_volume_history(code: str, today: date) -> tuple[list, int | None]:
    """A Japanese stock's trailing year of daily volumes plus today's running volume, from Yahoo (.T)."""
    from .market_price_targets import yahoo_symbols
    symbol = (yahoo_symbols(code, "JP") or [None])[0]
    if not symbol:
        return [], None
    with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(CHART_URL.format(symbol=symbol), params={"range": "1y", "interval": "1d"})
        response.raise_for_status()
        return parse_yahoo_volumes(response.json(), today)


def fetch_japan_quotes(items: list[dict], today: date, client: httpx.Client | None = None) -> list[dict]:
    """One daily-chart request per Japanese stock; a failing symbol is skipped and logged, never fatal."""
    from .market_price_targets import yahoo_symbols
    own = client is None
    client = client or httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT})
    quotes = []
    try:
        for item in items:
            code = str(item.get("code", "")).upper()
            try:
                symbol = (yahoo_symbols(code, "JP") or [None])[0]
                if not symbol:
                    continue
                response = client.get(CHART_URL.format(symbol=symbol), params={"range": "1y", "interval": "1d"})
                response.raise_for_status()
                quote = parse_yahoo_chart(response.json(), code, today, item.get("name") or "")
                if quote:
                    quotes.append(quote)
            except Exception as exc:
                logger.warning("Japan quote for %s unavailable: %s", code, type(exc).__name__)
    finally:
        if own:
            client.close()
    return quotes


def fetch_index_quote(today: date) -> dict | None:
    """The TAIEX from Yahoo (^TWII): price and change-percent while Taipei trades. Yahoo reports no running volume for it."""
    with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(CHART_URL.format(symbol=INDEX_YAHOO), params={"range": "1y", "interval": "1d"})
        response.raise_for_status()
        quote = parse_yahoo_chart(response.json(), INDEX_CODE, today, INDEX_NAME)
    if not quote:
        return None
    return {**quote, "productType": "index", "market": "TW", "levels": INDEX_LEVELS, "swing": INDEX_SWING, "bigDay": INDEX_BIG_DAY}


def pcts_from_points(points: list[dict], today: str) -> list[float]:
    """Completed days' change-percents from stored official TWSE/TPEx daily prices (today's partial row is excluded)."""
    out = []
    for point in points:
        if point["date"] >= today:
            continue
        values = next((point["sources"][s] for s in ("twse:daily-price", "tpex:daily-price")
                       if isinstance(point["sources"].get(s, {}).get("close"), (int, float))), None)
        if not values or not isinstance(values.get("change"), (int, float)):
            continue
        base = values["close"] - values["change"]
        if base > 0:
            out.append(round(values["change"] / base * 100, 2))
    return out[-HISTORY_DAYS:]


def _db_volume_history(code: str, today: date) -> list:
    from ..databases.market_history_db import market_history_db
    points = market_history_db.history(code, today - timedelta(days=370), today,
                                       sources=["twse:daily-price", "tpex:daily-price"])["points"]
    rows = []
    for point in points:
        values = next((point["sources"][s] for s in ("twse:daily-price", "tpex:daily-price")
                       if isinstance(point["sources"].get(s, {}).get("volume_shares"), (int, float))), None)
        if values and values["volume_shares"] > 0:
            rows.append([point["date"], int(values["volume_shares"])])
    return rows


def _yahoo_volume_history(code: str, today: date) -> list:
    """A year of daily volumes (shares) from Yahoo when the database has not collected that much for this stock."""
    with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        for suffix in (".TW", ".TWO"):
            response = client.get(CHART_URL.format(symbol=f"{code}{suffix}"), params={"range": "1y", "interval": "1d"})
            if response.status_code != 200:
                continue
            result = (response.json().get("chart") or {}).get("result") or []
            if not result:
                continue
            stamps, volumes = result[0].get("timestamp") or [], (result[0]["indicators"]["quote"][0].get("volume") or [])
            rows = [[datetime.fromtimestamp(t, TAIPEI).date().isoformat(), int(v)] for t, v in zip(stamps, volumes) if v]
            return [row for row in rows if row[0] < today.isoformat()]
    return []


def volume_history_for(code: str, today: date, db=_db_volume_history, yahoo=_yahoo_volume_history) -> list:
    """Daily volumes for the trailing year: the database's own records when they reach far enough back, else Yahoo."""
    try:
        rows = db(code, today)
        if len(rows) >= volume_rank.MIN_HISTORY_DAYS:
            return rows
    except Exception:
        logger.warning("Volume history from the database unavailable for %s", code, exc_info=True)
    try:
        return yahoo(code, today)
    except Exception:
        logger.warning("Volume history from Yahoo unavailable for %s", code, exc_info=True)
        return []


def taiwan_history(code: str, today: date) -> list[float]:
    from ..databases.market_history_db import market_history_db
    points = market_history_db.history(code, today - timedelta(days=14), today,
                                       sources=["twse:daily-price", "tpex:daily-price"])["points"]
    return pcts_from_points(points, today.isoformat())


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

    def __init__(self, fetch_index=fetch_index_quote, fetch_japan=fetch_japan_quotes, history_taiwan=taiwan_history, volume_history_taiwan=volume_history_for):
        self._state: dict = {}
        self._fetch_index = fetch_index
        self._fetch_japan, self._history_taiwan, self._volume_history_taiwan = fetch_japan, history_taiwan, volume_history_taiwan
        self._history: dict = {}  # (code, day) -> completed days' percents, read once a day
        self._volumes: dict = {}  # (code, day) -> [[date, shares], ...] for the trailing year, read once a day
        self._last_japan: datetime | None = None
        self._last_index: datetime | None = None

    async def _run(self, quotes: list[dict], now: datetime) -> list[dict]:
        alerts = []
        for quote in quotes:
            self._state, found = evaluate(self._state, quote, now)
            alerts += found
        if alerts:
            await asyncio.to_thread(notify, alerts)
        return alerts

    async def check(self, quotes: list[dict], now: datetime | None = None) -> list[dict]:
        """Taiwan quotes from the Shioaji refresh."""
        now = now or datetime.now(TAIPEI)
        if not in_trading_hours(now, "TW"):
            return []
        today = now.astimezone(TAIPEI).date()
        with_history = []
        for quote in quotes:
            key = (quote.get("symbol"), today)
            if key not in self._history:
                try:
                    self._history[key] = await asyncio.to_thread(self._history_taiwan, str(quote.get("symbol")), today)
                except Exception:
                    logger.warning("Taiwan daily history unavailable for %s", quote.get("symbol"), exc_info=True)
                    self._history[key] = []
            if key not in self._volumes:
                try:
                    self._volumes[key] = await asyncio.to_thread(self._volume_history_taiwan, str(quote.get("symbol")), today)
                except Exception:
                    logger.warning("Taiwan volume history unavailable for %s", quote.get("symbol"), exc_info=True)
                    self._volumes[key] = []
            with_history.append({**quote, "history": self._history[key], "volumeHistory": quote.get("volumeHistory") or self._volumes[key]})
        return await self._run(with_history, now)

    async def check_japan(self, items: list[dict], now: datetime | None = None) -> list[dict]:
        """Japanese stocks: polled from Yahoo at most every two minutes, and only while Tokyo is open."""
        now = now or datetime.now(TOKYO)
        if not items or not in_trading_hours(now, "JP"):
            return []
        if self._last_japan and now - self._last_japan < JAPAN_POLL:
            return []
        self._last_japan = now
        quotes = await asyncio.to_thread(self._fetch_japan, items, now.astimezone(TOKYO).date())
        return await self._run(quotes, now)


    async def check_index(self, now: datetime | None = None) -> list[dict]:
        """The TAIEX (docs/INTRADAY_ALERTS.md): polled from Yahoo at most once a minute while Taipei is open."""
        now = now or datetime.now(TAIPEI)
        if not in_trading_hours(now, "TW"):
            return []
        if self._last_index and now - self._last_index < INDEX_POLL:
            return []
        self._last_index = now
        quote = await asyncio.to_thread(self._fetch_index, now.astimezone(TAIPEI).date())
        return await self._run([quote], now) if quote else []


intraday_alert_monitor = IntradayAlertMonitor()
