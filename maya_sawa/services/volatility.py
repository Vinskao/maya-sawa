"""Taiwan VIX and U.S. VIX, for the live volatility charts at the top of the macro page (docs/VOLATILITY_CHARTS.md).

History: TAIFEX publishes the Taiwan VIX daily close as one Big5 text file per month (only about four months stay online,
so the series is accumulated in the macro cache). Live: TAIFEX's quote service (symbol TAIWANVIX, the page's own feed) and
Yahoo's one-minute ^VIX chart. Both are unofficial for programmatic use, so a failing source is reported as null, never fatal.
"""
import logging
import re
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
CHICAGO = ZoneInfo("America/Chicago")
TW_VIX_MONTHLY_URL = "https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{month}new.txt"
TAIFEX_QUOTE_URL = "https://mis.taifex.com.tw/futures/api/getQuoteDetail"
YAHOO_VIX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
LIVE_TTL_SECONDS = 30

_DAY_ROW = re.compile(r"^(\d{4})(\d{2})(\d{2})\t")


def parse_taifex_vix_monthly(text: str) -> list[dict]:
    """Daily rows from a monthly file: date, time, VIX at 13:45:00, and the official last-minute average (the last column)."""
    rows = []
    for line in text.splitlines():
        match = _DAY_ROW.match(line)
        cells = [cell.strip() for cell in line.split("\t") if cell.strip()]
        if not match or len(cells) < 3:
            continue
        try:
            value = float(cells[-1])
        except ValueError:
            continue
        rows.append({"code": "TW_VIX", "period": "-".join(match.groups()), "value": f"{value:.2f}"})
    return rows


def merge_history(stored: list[dict], rows: list[dict]) -> list[dict]:
    """Everything stored so far plus the new rows; a new row replaces the stored value for the same day."""
    by_day = {row["period"]: row["value"] for row in stored}
    by_day.update({row["period"]: row["value"] for row in rows})
    return [{"code": "TW_VIX", "period": day, "value": value} for day, value in sorted(by_day.items())]


def _number(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _live(value: float, previous: float | None, high, low, as_of: str, **extra) -> dict:
    change = round(value - previous, 2) if previous else None
    return {"value": value, "previousClose": previous, "high": high, "low": low, "change": change,
            "changePercent": round(change / previous * 100, 2) if change is not None else None, "asOf": as_of, **extra}


def parse_taifex_vix_quote(payload: dict) -> dict | None:
    """TAIFEX quote service answer for TAIWANVIX; None when it carries no price (closed, or the service said no)."""
    try:
        quote = payload["RtData"]["QuoteList"][0]
    except (KeyError, IndexError, TypeError):
        return None
    value = _number(quote.get("CLastPrice"))
    stamp = f"{quote.get('CDate', '')}{str(quote.get('CTime', '')).zfill(6)}"
    if value is None or not re.fullmatch(r"\d{14}", stamp):
        return None
    moment = datetime.strptime(stamp, "%Y%m%d%H%M%S").replace(tzinfo=TAIPEI)
    return _live(value, _number(quote.get("CRefPrice")), _number(quote.get("CHighPrice")), _number(quote.get("CLowPrice")),
                 moment.isoformat(), open=_number(quote.get("COpenPrice")), date=moment.date().isoformat())


def parse_yahoo_vix(payload: dict) -> dict | None:
    try:
        meta = payload["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError):
        return None
    value = _number(meta.get("regularMarketPrice"))
    stamp = meta.get("regularMarketTime")
    if value is None or not isinstance(stamp, (int, float)):
        return None
    moment = datetime.fromtimestamp(stamp, CHICAGO)
    return _live(value, _number(meta.get("chartPreviousClose") or meta.get("previousClose")),
                 _number(meta.get("regularMarketDayHigh")), _number(meta.get("regularMarketDayLow")), moment.isoformat(),
                 date=moment.date().isoformat())


def fetch_taiwan_vix(client: httpx.Client | None = None) -> dict | None:
    own = client is None
    client = client or httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT})
    try:
        response = client.post(TAIFEX_QUOTE_URL, json={"SymbolID": ["TAIWANVIX"]})
        response.raise_for_status()
        return parse_taifex_vix_quote(response.json())
    finally:
        if own:
            client.close()


def fetch_us_vix(client: httpx.Client | None = None) -> dict | None:
    own = client is None
    client = client or httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT})
    try:
        response = client.get(YAHOO_VIX_URL, params={"range": "1d", "interval": "1m"})
        response.raise_for_status()
        return parse_yahoo_vix(response.json())
    finally:
        if own:
            client.close()


class VolatilityLive:
    """Both live readings, refetched at most every 30 seconds however many browsers ask."""

    def __init__(self, fetch_taiwan=fetch_taiwan_vix, fetch_us=fetch_us_vix, clock=lambda: datetime.now(timezone.utc)):
        self._fetchers = {"TW_VIX": fetch_taiwan, "US_VIX": fetch_us}
        self._clock = clock
        self._lock = threading.Lock()
        self._at: datetime | None = None
        self._data: dict = {}

    def get(self) -> dict:
        with self._lock:
            now = self._clock()
            if self._at is None or (now - self._at).total_seconds() >= LIVE_TTL_SECONDS:
                data = {}
                for code, fetch in self._fetchers.items():
                    try:
                        data[code] = fetch()
                    except Exception as exc:
                        logger.warning("Live %s unavailable: %s", code, type(exc).__name__)
                        data[code] = None
                self._data, self._at = data, now
            return {**self._data, "fetchedAt": self._at.isoformat()}


volatility_live = VolatilityLive()
