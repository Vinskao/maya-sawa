"""Today's market state for the banner at the top of the site (2026-11-17).

The banner used to read the cached daily series, which trails by hours, so on Tuesday it still shouted Monday's
drop. It now reads TWSE directly (FMTQIK closes and trading value, MIS for the live index), describes only TODAY,
says whether a big move came with heavy volume, and flags a falling market P/E (the series from market_macro).
"""
import logging
import time
from datetime import date, datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

TAIPEI = timezone(timedelta(hours=8))
FMTQIK_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={day}&response=json"
MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw&json=1&delay=0"
AGENT = {"User-Agent": "Mozilla/5.0 (compatible; maya-sawa market status)", "Referer": "https://mis.twse.com.tw/stock/index.jsp"}
BIG_MOVE, STRONG_MOVE = 2.0, 3.0   # percent: a warning, then an alert
HEAVY, ELEVATED, THIN = 1.5, 1.2, 0.7   # trading value vs the average of the previous 20 sessions
VOLUME_WINDOW = 20
CACHE_SECONDS = 45


def _number(text) -> float | None:
    try: return float(str(text).replace(",", ""))
    except ValueError: return None


def parse_fmtqik(payload: dict) -> list[dict]:
    """FMTQIK rows -> [{date, close, value}], value = trading value in NT$ 100 million."""
    rows = []
    for item in payload.get("data") or []:
        try:
            year, month, day = str(item[0]).split("/")
            close, amount = _number(item[4]), _number(item[2])
            if close is None or amount is None: continue
            rows.append({"date": date(int(year) + 1911, int(month), int(day)).isoformat(), "close": close, "value": round(amount / 1e8, 2)})
        except (ValueError, IndexError):
            continue
    return rows


def parse_mis_index(payload: dict) -> dict | None:
    """The live TAIEX reading, or None before anything has traded."""
    try:
        row = (payload.get("msgArray") or [])[0]
        price, prev, stamp = _number(row.get("z")), _number(row.get("y")), str(row.get("d", ""))
        if price is None or prev is None or len(stamp) != 8: return None
        return {"date": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}", "time": row.get("t", ""), "price": price, "prev": prev}
    except (IndexError, AttributeError):
        return None


STOCKS = "/stocks/"
NIGHT_FRESH_MINUTES = 30
NIGHT_NOTICE, NIGHT_ALERT = 1.0, 2.0   # percent: when the night session alone is worth a banner, and a red one


def parse_txf_night(quote: dict | None, now: datetime) -> dict | None:
    """The TAIEX futures night session (15:00-05:00) as {price, pct, time}, only while the quote is fresh.

    The futures' own reference price during the night is that day's day-session settlement, so the change percent
    is the night session's move from the day session.
    """
    try:
        stamp = datetime.fromisoformat(str(quote["timestamp"])).astimezone(TAIPEI)
        price, pct = float(quote["close"]), float(quote["changePercent"])
    except (KeyError, TypeError, ValueError):
        return None
    if stamp.hour < 15 and stamp.hour >= 5: return None                       # a day-session (or pre-open) quote
    if (now.astimezone(TAIPEI) - stamp) > timedelta(minutes=NIGHT_FRESH_MINUTES): return None
    return {"price": price, "pct": pct, "time": stamp.strftime("%H:%M")}


def _night_item(night: dict) -> dict:
    pct = night["pct"]
    level = "alert" if abs(pct) >= NIGHT_ALERT else "warn" if abs(pct) >= NIGHT_NOTICE else "info"
    return {"id": "night", "href": STOCKS, "level": level, "dir": "down" if pct < 0 else "up",
            "zh": f"台指期夜盤 {pct:+.2f}%（{night['price']:,.0f}，相對日盤結算價，{night['time']}）",
            "en": f"TAIEX futures night session {pct:+.2f}% ({night['price']:,.0f}, vs the day-session settlement, {night['time']})"}


US_STALE_DAYS = 4          # a long weekend; older U.S. bars are not news
SOX_WARN, SOX_ALERT = 2.5, 4.0
SOX_WEEK_WARN = 4.0         # the week so far, once the U.S. session has closed
VIX_WARN, VIX_ALERT, VIX_JUMP_WARN, VIX_JUMP_ALERT = 25.0, 30.0, 15.0, 25.0
US_SOX_YAHOO, US_VIX_YAHOO = "^SOX", "^VIX"
TAIEX_YAHOO = "^TWII"
YAHOO_ALL_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=max&interval=1wk"
DRAWDOWN_WARN, DRAWDOWN_ALERT = 20.0, 30.0   # % below the all-time closing high; shallower pullbacks are not an event
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1mo&interval=1d"


def parse_yahoo_closes(payload: dict) -> list[dict]:
    """Yahoo daily chart -> [{date (New York), close}] without the empty bars."""
    from zoneinfo import ZoneInfo
    try:
        result = payload["chart"]["result"][0]
        stamps, closes = result["timestamp"], result["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return []
    zone = ZoneInfo("America/New_York")
    return [{"date": datetime.fromtimestamp(t, zone).date().isoformat(), "close": float(c)}
            for t, c in zip(stamps, closes) if isinstance(c, (int, float)) and c > 0]


def _streak(values: list[float], rising: bool) -> int:
    count = 0
    for i in range(len(values) - 1, 0, -1):
        if (values[i] > values[i - 1]) if rising else (values[i] < values[i - 1]): count += 1
        else: break
    return count


def us_items(sox: list[dict], vix: list[dict], today: date, now: datetime | None = None) -> list[dict]:
    """The Philadelphia semiconductor index and the VIX (with how many days it has risen) as banner items."""
    items: list[dict] = []
    from zoneinfo import ZoneInfo
    ny_now = (now or datetime.now(ZoneInfo("America/New_York"))).astimezone(ZoneInfo("America/New_York"))
    def state(bars):
        """(label zh, label en): the latest bar is a live one only while the New York session is open on that date."""
        open_now = ny_now.weekday() < 5 and (9, 30) <= (ny_now.hour, ny_now.minute) < (16, 0) and bars[-1]["date"] == ny_now.date().isoformat()
        return ("盤中", "intraday") if open_now else ("收盤", "close")
    fresh = lambda bars: bool(bars) and 0 <= (today - date.fromisoformat(bars[-1]["date"])).days <= US_STALE_DAYS
    if len(sox) >= 2 and fresh(sox):
        closes, day = [bar["close"] for bar in sox], date.fromisoformat(sox[-1]["date"]).strftime("%m/%d")
        st, st_en = state(sox)
        change = (closes[-1] / closes[-2] - 1) * 100
        if st_en == "intraday":
            if abs(change) >= SOX_WARN:
                word, word_en = ("大跌", "fell") if change < 0 else ("大漲", "rose")
                items.append({"id": "sox", "href": STOCKS, "level": "alert" if abs(change) >= SOX_ALERT else "warn", "dir": "down" if change < 0 else "up",
                              "zh": f"美股費城半導體指數（SOX）{word} {abs(change):.2f}%（{closes[-2]:,.0f}→{closes[-1]:,.0f}，美股 {day} {st}）",
                              "en": f"Philadelphia Semiconductor Index (SOX) {word_en} {abs(change):.2f}% ({closes[-2]:,.0f} to {closes[-1]:,.0f}, U.S. {day} {st_en})"})
        else:
            # A finished U.S. session is yesterday's news by Taiwan morning: report the week so far, not one old day.
            last = date.fromisoformat(sox[-1]["date"])
            monday = (last - timedelta(days=last.weekday())).isoformat()
            week = [i for i, bar in enumerate(sox) if bar["date"] >= monday]
            base_index = week[0] - 1 if week[0] > 0 else week[0]
            base, sessions = closes[base_index], len(sox) - 1 - base_index
            wk = (closes[-1] / base - 1) * 100
            if sessions >= 1 and (abs(wk) >= SOX_WEEK_WARN or abs(change) >= SOX_WARN):
                bigger = max(abs(wk) / SOX_WEEK_WARN * SOX_WARN, abs(change))
                lead = wk if abs(wk) >= 0.01 else change
                word, word_en = ("下跌", "down") if lead < 0 else ("上漲", "up")
                zh = f"美股費城半導體指數（SOX）本週累計{word} {abs(wk):.2f}%（{base:,.0f}→{closes[-1]:,.0f}，{sessions} 個交易日，至美股 {day} {st}）"
                en = f"Philadelphia Semiconductor Index (SOX) {word_en} {abs(wk):.2f}% this week ({base:,.0f} to {closes[-1]:,.0f}, {sessions} sessions, through U.S. {day} {st_en})"
                if sessions > 1 and abs(change) >= 1:
                    zh += f"，最後一天 {change:+.2f}%"; en += f", last session {change:+.2f}%"
                items.append({"id": "sox", "href": STOCKS, "level": "alert" if bigger >= SOX_ALERT else "warn", "dir": "down" if lead < 0 else "up", "zh": zh, "en": en})
        down = _streak(closes, rising=False)
        if down >= 3:
            total = (closes[-1] / closes[-down - 1] - 1) * 100
            items.append({"id": "sox-streak", "href": STOCKS, "level": "warn", "dir": "down", "zh": f"費城半導體指數連跌 {down} 日（累計 {total:.2f}%，美股 {day} {st}）",
                          "en": f"SOX down {down} sessions in a row ({total:.2f}% in total, U.S. {day} {st_en})"})
    if len(vix) >= 2 and fresh(vix):
        closes, day = [bar["close"] for bar in vix], date.fromisoformat(vix[-1]["date"]).strftime("%m/%d")
        st, st_en = state(vix)
        jump, up = (closes[-1] / closes[-2] - 1) * 100, _streak(closes, rising=True)
        level = "alert" if closes[-1] >= VIX_ALERT or jump >= VIX_JUMP_ALERT else             "warn" if closes[-1] >= VIX_WARN or jump >= VIX_JUMP_WARN or up >= 3 else None
        if level:
            zh = f"VIX 恐慌指數 {closes[-1]:.1f}（{jump:+.1f}%，美股 {day} {st}）"
            en = f"VIX {closes[-1]:.1f} ({jump:+.1f}%, U.S. {day} {st_en})"
            if up >= 2:
                zh += f"，連漲 {up} 日（{closes[-up - 1]:.1f}→{closes[-1]:.1f}）"
                en += f", up {up} sessions in a row ({closes[-up - 1]:.1f} to {closes[-1]:.1f})"
            if closes[-1] >= VIX_WARN:
                zh += "，進入恐慌區"
                en += ", in the fear zone"
            items.append({"id": "vix", "href": "/macro/#macro-volatility", "level": level, "dir": "down", "zh": zh, "en": en})
    return items


def drawdown_item(item_id: str, name_zh: str, name_en: str, history: list[dict], recent: list[dict]) -> dict | None:
    """How far an index sits below its all-time closing high; only a fall of 20% or more (a bear market) is an item."""
    bars = [*history, *recent]
    if not bars or not recent: return None
    peak = max(bars, key=lambda bar: bar["close"])
    last = recent[-1]["close"]
    pct = (1 - last / peak["close"]) * 100
    if pct < DRAWDOWN_WARN: return None
    month = peak["date"][:7].replace("-", "/")
    return {"id": item_id, "href": STOCKS, "level": "alert" if pct >= DRAWDOWN_ALERT else "warn", "dir": "down",
            "zh": f"{name_zh}較歷史高點（{month}，{peak['close']:,.0f}）回落 {pct:.1f}%（現 {last:,.0f}），已達空頭等級",
            "en": f"{name_en} is {pct:.1f}% below its all-time high ({month}, {peak['close']:,.0f}); now {last:,.0f}, bear-market territory"}


def _value_text(value: float) -> str:
    return f"{value / 10000:.2f} 兆" if value >= 10000 else f"{value:,.0f} 億"


def _value_text_en(value: float) -> str:
    return f"NT${value / 10000:.2f} trillion" if value >= 10000 else f"NT${value:,.0f}00 million"


def _pe_item(pe: list[tuple[str, float]], today: date) -> dict | None:
    """Market P/E falling for 3+ sessions ending today; warn when the latest drop is at least 1.5x the one before."""
    points = [(day, value) for day, value in sorted(pe) if value and value > 0]
    if len(points) < 4 or points[-1][0] != today.isoformat(): return None
    drops = [(points[i][1] / points[i - 1][1] - 1) * 100 for i in range(1, len(points))]
    streak = 0
    for change in reversed(drops):
        if change >= 0: break
        streak += 1
    if streak < 3: return None
    accelerating = streak >= 3 and drops[-1] <= drops[-2] * 1.5
    path = f"{points[-streak - 1][1]:.1f}→{points[-1][1]:.1f}"
    shown = "、".join(f"{change:.1f}%" for change in drops[-3:])
    zh = f"大盤本益比連降 {streak} 日（{path} 倍；每日 {shown}）" + ("，降速加快" if accelerating else "")
    en = f"Market P/E down {streak} sessions in a row ({path}x; daily {', '.join(f'{c:.1f}%' for c in drops[-3:])})" + (", falling faster" if accelerating else "")
    return {"id": "pe", "href": "/macro/#macro-leverage", "level": "warn" if accelerating else "info", "dir": "down", "zh": zh, "en": en}


GROUPS = {"sox": "us", "sox-streak": "us", "vix": "us", "sox-ath": "us"}   # everything else is Taiwan


def _tag(items: list[dict]) -> list[dict]:
    """Group the items by market. The bar exists only for a heavy-volume or big-swing event: with nothing at warn level
    or above, calm info lines (a small night move, the week total) are not worth a banner and nothing is returned."""
    if not any(item["level"] != "info" for item in items): return []
    return [{**item, "group": GROUPS.get(item["id"], "tw")} for item in items]


def build_status(days: list[dict], live: dict | None, pe: list[tuple[str, float]], today: date, night: dict | None = None, us: list[dict] | None = None, extra: list[dict] | None = None) -> dict:
    """Items for the banner, most severe first; empty when there is no data for today (yesterday is never the headline)."""
    iso = today.isoformat()
    finished = [row for row in days if row["date"] < iso]
    todays = next((row for row in days if row["date"] == iso), None)
    if todays:
        close, final, value = todays["close"], True, todays["value"]
    elif live and live["date"] == iso:
        close, final, value = live["price"], False, None
    else:
        # No day-session data for today (before the open, at night after midnight): only the night session can speak.
        early = list(us or []) + [i for i in (extra or []) if i["id"] == "sox-ath"] + ([_night_item(night)] if night and abs(night["pct"]) >= NIGHT_NOTICE else [])
        if early:
            early.sort(key=lambda item: {"alert": 0, "warn": 1, "info": 2}[item["level"]])
            return {"items": _tag(early), "asOf": iso, "final": False, "session": "night" if night else "day"}
        return {"items": [], "asOf": None}
    if not finished: return {"items": [], "asOf": iso}
    prev = finished[-1]["close"]
    change = (close / prev - 1) * 100
    items: list[dict] = []
    big = abs(change) >= BIG_MOVE
    ratio = None
    if value is not None:
        recent = [row["value"] for row in finished[-VOLUME_WINDOW:] if row["value"]]
        if len(recent) >= 5: ratio = value / (sum(recent) / len(recent))
    heavy, thin = ratio is not None and ratio >= HEAVY, ratio is not None and ratio <= THIN
    if big:
        word, word_en = ("大跌", "fell") if change < 0 else ("大漲", "rose")
        zh = f"加權指數{'日盤收盤' if final else '盤中'}{word} {abs(change):.2f}%（{prev:,.0f}→{close:,.0f}）"
        en = f"TAIEX {'day session' if final else 'intraday'} {word_en} {abs(change):.2f}% ({prev:,.0f} to {close:,.0f})"
        if ratio is not None:
            tag = "爆量" if heavy else "放量" if ratio >= ELEVATED else "量縮" if thin else "量能持平"
            tag_en = "heavy volume" if heavy else "above-average volume" if ratio >= ELEVATED else "thin volume" if thin else "average volume"
            zh += f"，{word}伴隨{tag}：成交值 {_value_text(value)}，為近 {VOLUME_WINDOW} 日均量的 {ratio:.1f} 倍"
            en += f", on {tag_en}: turnover {_value_text_en(value)}, {ratio:.1f}x the {VOLUME_WINDOW}-day average"
        items.append({"id": "move", "href": STOCKS, "level": "alert" if abs(change) >= STRONG_MOVE else "warn", "dir": "down" if change < 0 else "up", "zh": zh, "en": en})
    elif heavy:
        items.append({"id": "volume", "href": STOCKS, "level": "warn", "dir": "down" if change < 0 else "up", "zh": f"加權指數今日成交爆量：{_value_text(value)}，為近 {VOLUME_WINDOW} 日均量的 {ratio:.1f} 倍（漲跌 {change:+.2f}%）",
                      "en": f"TAIEX turnover is heavy today: {_value_text_en(value)}, {ratio:.1f}x the {VOLUME_WINDOW}-day average ({change:+.2f}%)"})
    closes = [row["close"] for row in finished] + [close]
    streak = 0
    for i in range(len(closes) - 1, 0, -1):
        if closes[i] < closes[i - 1]: streak += 1
        else: break
    if streak >= 3:
        total = (closes[-1] / closes[-streak - 1] - 1) * 100
        items.append({"id": "streak", "href": STOCKS, "level": "warn", "dir": "down", "zh": f"加權指數連跌 {streak} 個交易日（累計 {total:.2f}%）",
                      "en": f"TAIEX down {streak} sessions in a row ({total:.2f}% in total)"})
    week_start = today - timedelta(days=today.weekday())
    before_week = [row for row in finished if row["date"] < week_start.isoformat()]
    if before_week and today.weekday() > 0:
        week = (close / before_week[-1]["close"] - 1) * 100
        if abs(week) >= STRONG_MOVE:
            sessions_in_week = len([row for row in finished if row["date"] >= week_start.isoformat()]) + 1
            items.append({"id": "week", "href": STOCKS, "level": "info", "dir": "down" if week < 0 else "up", "zh": f"本週累計 {week:+.2f}%（{sessions_in_week} 個交易日）",
                          "en": f"Week to date {week:+.2f}% ({sessions_in_week} sessions)"})
    pe_item = _pe_item(pe, today)
    if pe_item: items.append(pe_item)
    items += us or []
    if night and (items or abs(night["pct"]) >= NIGHT_NOTICE): items.append(_night_item(night))
    order = {"alert": 0, "warn": 1, "info": 2}
    items += extra or []
    items.sort(key=lambda item: order[item["level"]])
    return {"items": _tag(items), "asOf": iso, "final": final, "session": "night" if night else "day"}


class MarketStatusService:
    def __init__(self) -> None:
        self._cache: tuple[float, dict] | None = None
        self._us_cache: dict[str, tuple[float, list[dict]]] = {}

    def _get_json(self, client: httpx.Client, url: str) -> dict:
        response = client.get(url)
        response.raise_for_status()
        return response.json()

    def _load(self, today: date) -> tuple[list[dict], dict | None]:
        days: list[dict] = []
        with httpx.Client(timeout=10, headers=AGENT) as client:
            for month_start in ((today.replace(day=1) - timedelta(days=1)).replace(day=1), today.replace(day=1)):
                try:
                    days += parse_fmtqik(self._get_json(client, FMTQIK_URL.format(day=f"{month_start:%Y%m%d}")))
                except Exception:
                    logger.warning("FMTQIK unavailable for %s", month_start, exc_info=True)
            live = None
            if not any(row["date"] == today.isoformat() for row in days):
                try: live = parse_mis_index(self._get_json(client, MIS_URL))
                except Exception: logger.warning("Live TAIEX unavailable", exc_info=True)
        return sorted(days, key=lambda row: row["date"]), live

    def _us_bars(self, symbol: str) -> list[dict]:
        cached = self._us_cache.get(symbol)
        if cached and time.monotonic() - cached[0] < 60: return cached[1]   # live while New York trades, so Yahoo is asked about once a minute
        try:
            with httpx.Client(timeout=10, headers=AGENT) as client:
                bars = parse_yahoo_closes(self._get_json(client, YAHOO_URL.format(symbol=symbol)))
        except Exception:
            logger.warning("U.S. series %s unavailable", symbol, exc_info=True)
            return cached[1] if cached else []
        self._us_cache[symbol] = (time.monotonic(), bars)
        return bars

    def _all_time(self, symbol: str) -> list[dict]:
        cached = self._us_cache.get("ath:" + symbol)
        if cached and time.monotonic() - cached[0] < 6 * 3600: return cached[1]
        try:
            with httpx.Client(timeout=15, headers=AGENT) as client:
                bars = parse_yahoo_closes(self._get_json(client, YAHOO_ALL_URL.format(symbol=symbol)))
        except Exception:
            logger.warning("All-time series %s unavailable", symbol, exc_info=True)
            return cached[1] if cached else []
        self._us_cache["ath:" + symbol] = (time.monotonic(), bars)
        return bars

    def _drawdowns(self) -> list[dict]:
        found = [drawdown_item("sox-ath", "費城半導體指數", "SOX", self._all_time(US_SOX_YAHOO), self._us_bars(US_SOX_YAHOO)),
                 drawdown_item("twii-ath", "加權指數", "TAIEX", self._all_time(TAIEX_YAHOO), self._us_bars(TAIEX_YAHOO))]
        return [item for item in found if item]

    def _pe_history(self) -> list[tuple[str, float]]:
        from . import market_macro
        rows = (market_macro._macro_local_cache.get("series:TW_MARKET_PE") or {}).get("history") or []
        out = []
        for row in rows:
            try: out.append((row["period"], float(row["value"])))
            except (KeyError, TypeError, ValueError): continue
        return out

    def get(self, now: datetime | None = None, txf: dict | None = None) -> dict:
        now = now or datetime.now(TAIPEI)
        if self._cache and time.monotonic() - self._cache[0] < CACHE_SECONDS:
            return self._cache[1]
        today = now.astimezone(TAIPEI).date()
        days, live = self._load(today)
        status = build_status(days, live, self._pe_history(), today, parse_txf_night(txf, now),
                              us_items(self._us_bars(US_SOX_YAHOO), self._us_bars(US_VIX_YAHOO), today), self._drawdowns())
        status["checkedAt"] = now.isoformat()
        self._cache = (time.monotonic(), status)
        return status


market_status_service = MarketStatusService()
