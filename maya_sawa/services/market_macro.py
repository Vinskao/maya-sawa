"""Low-frequency, persisted US macro data from registered BLS/FRED APIs and the Fed calendar."""
from __future__ import annotations

import asyncio
import csv
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from ..databases.market_macro_db import MacroFetchRun, MacroSeries, market_macro_db

logger = logging.getLogger(__name__)
UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")
CENTRAL = ZoneInfo("America/Chicago")
MACRO_ENABLED = os.getenv("MACRO_ENABLED", "false").lower() == "true"
BLS_KEY = os.getenv("BLS_API_KEY", "").strip()
FRED_KEY = os.getenv("FRED_API_KEY", "").strip()
BLS_SERIES = {
    "CES0000000001": ("Nonfarm payrolls", "thousand persons", "monthly"),
    "LNS14000000": ("Unemployment rate", "percent", "monthly"),
    "CUSR0000SA0": ("CPI, all items, seasonally adjusted", "index 1982-84=100", "monthly"),
    "CUSR0000SA0L1E": ("Core CPI, seasonally adjusted", "index 1982-84=100", "monthly"),
    "CUUR0000SA0": ("CPI, all items, not seasonally adjusted", "index 1982-84=100", "monthly"),
    "CUUR0000SA0L1E": ("Core CPI, not seasonally adjusted", "index 1982-84=100", "monthly"),
    "WPUFD4": ("Producer Price Index, final demand", "index Nov 2009=100", "monthly"),
}
FRED_RELEASES = {
    "50": ("employment", "Nonfarm payrolls / Employment Situation"),
    "180": ("claims", "Unemployment Insurance Weekly Claims Report"),
    "10": ("cpi", "CPI / Consumer Price Index"),
    "46": ("ppi", "Producer Price Index"),
    "9": ("retail_sales", "Advance Monthly Sales for Retail and Food Services"),
}
FRED_SERIES = {
    "DFEDTARL": ("Federal funds target range, lower limit", "percent", "daily"),
    "DFEDTARU": ("Federal funds target range, upper limit", "percent", "daily"),
    "RSAFS": ("Advance retail sales and food services", "millions of dollars", "monthly"),
    "DGS10": ("10-year Treasury constant maturity yield", "percent", "daily"),
    "DCOILWTICO": ("WTI crude oil spot price", "USD/barrel", "daily"),
    "ICSA": ("Initial unemployment insurance claims, seasonally adjusted", "persons", "weekly"),
    "GBRSLRTTO01GPSAM": ("United Kingdom retail sales volume, month over month", "percent", "monthly"),
    "GBRSLRTTO01GYSAM": ("United Kingdom retail sales volume, year over year", "percent", "monthly"),
    # Money supply and central-bank balance sheets (plan section 22). Units are after FRED_SCALE.
    "M2SL": ("U.S. M2 money stock, seasonally adjusted", "USD billion", "monthly"),
    "WALCL": ("Federal Reserve total assets (H.4.1, Wednesday level)", "USD billion", "weekly"),
    "WTREGEN": ("U.S. Treasury General Account at the Fed (Wednesday level)", "USD billion", "weekly"),
    "RRPONTSYD": ("Fed overnight reverse repurchase agreements", "USD billion", "daily"),
    "ECBASSETSW": ("Eurosystem total assets", "EUR billion", "weekly"),
    "JPNASSETS": ("Bank of Japan total assets", "JPY trillion", "monthly"),
    # Market and policy rates beyond the Fed target and 10-year yield.
    "SOFR": ("Secured Overnight Financing Rate", "percent", "daily"),
    "DGS3MO": ("3-month Treasury constant maturity yield", "percent", "daily"),
    "DGS2": ("2-year Treasury constant maturity yield", "percent", "daily"),
    "T10Y2Y": ("10-year minus 2-year Treasury spread", "percent", "daily"),
    "T10Y3M": ("10-year minus 3-month Treasury spread", "percent", "daily"),
    "DFII10": ("10-year TIPS real yield", "percent", "daily"),
    "T10YIE": ("10-year breakeven inflation rate", "percent", "daily"),
    "ECBDFR": ("ECB deposit facility rate", "percent", "daily"),
    "IUDSOIA": ("Sterling Overnight Index Average (SONIA)", "percent", "daily"),
    "IRSTCI01JPM156N": ("Japan overnight call rate (OECD)", "percent", "monthly"),
    # Credit spreads, bank delinquency/charge-off rates and financial stress.
    "BAMLH0A0HYM2": ("ICE BofA U.S. high yield option-adjusted spread", "percent", "daily"),
    "BAMLC0A0CM": ("ICE BofA U.S. investment grade corporate option-adjusted spread", "percent", "daily"),
    "BAA10Y": ("Moody's Baa corporate yield minus 10-year Treasury", "percent", "daily"),
    "DRALACBS": ("U.S. bank delinquency rate, all loans", "percent", "quarterly"),
    "DRBLACBS": ("U.S. bank delinquency rate, business loans", "percent", "quarterly"),
    "DRSFRMACBS": ("U.S. bank delinquency rate, single-family residential mortgages", "percent", "quarterly"),
    "DRCCLACBS": ("U.S. bank delinquency rate, credit cards", "percent", "quarterly"),
    "CORCCACBS": ("U.S. bank net charge-off rate, credit cards", "percent", "quarterly"),
    "STLFSI4": ("St. Louis Fed Financial Stress Index (0 = normal)", "index points", "weekly"),
    "NFCI": ("Chicago Fed National Financial Conditions Index (0 = average)", "index points", "weekly"),
}
ASIA_FRED_SERIES = {
    'LRUNTTTTJPM156S': ('Japan unemployment rate, age 15+, seasonally adjusted', 'percent', 'monthly'),
    'LRUNTTTTKRM156S': ('Korea unemployment rate, age 15+, seasonally adjusted', 'percent', 'monthly'),
    'IRSTCI01KRM156N': ('Korea overnight call rate (OECD)', 'percent', 'monthly'),
    'DEXKOUS': ('South Korean won per U.S. dollar', 'KRW/USD', 'daily'),
    'JPNSLRTTO01GPSAM': ('Japan retail sales volume, month over month', 'percent', 'monthly'),
    'JPNSLRTTO01GYSAM': ('Japan retail sales volume, year over year', 'percent', 'monthly'),
    'KORSLRTTO01GPSAM': ('Korea retail sales volume, month over month', 'percent', 'monthly'),
    'KORSLRTTO01GYSAM': ('Korea retail sales volume, year over year', 'percent', 'monthly'),
    'XTEXVA01JPM667S': ('Japan merchandise exports, USD, seasonally adjusted', 'USD', 'monthly'),
    'XTIMVA01JPM667S': ('Japan merchandise imports, USD, seasonally adjusted', 'USD', 'monthly'),
    'XTEXVA01KRM667S': ('Korea merchandise exports, USD, seasonally adjusted', 'USD', 'monthly'),
    'XTIMVA01KRM667S': ('Korea merchandise imports, USD, seasonally adjusted', 'USD', 'monthly'),
}
FRED_SERIES.update(ASIA_FRED_SERIES)
ASIA_CPI_SERIES = {
    'JP_CPI': ('Japan consumer price index (BIS long series)', 'index 2010=100', 'monthly'),
    'KR_CPI': ('Korea consumer price index (BIS long series)', 'index 2010=100', 'monthly'),
}
# Source units converted to the units declared above: millions -> billions, 100 million yen -> trillion yen.
FRED_SCALE = {"WALCL": 1 / 1000, "WTREGEN": 1 / 1000, "ECBASSETSW": 1 / 1000, "JPNASSETS": 1 / 10000}
FRED_SOURCE_LABELS = {"GBRSLRTTO01GPSAM": "OECD (via FRED)", "GBRSLRTTO01GYSAM": "OECD (via FRED)",
    "IRSTCI01JPM156N": "OECD (via FRED)", "BAMLH0A0HYM2": "ICE BofA (via FRED)", "BAMLC0A0CM": "ICE BofA (via FRED)"}
FRED_SOURCE_LABELS.update({code: 'Federal Reserve (via FRED)' if code == 'DEXKOUS' else 'OECD (via FRED)' for code in ASIA_FRED_SERIES})
# Series written to PostgreSQL before section 22; everything newer stays in process memory (postgres has 100m CPU).
FRED_PERSISTED = {"DFEDTARL", "DFEDTARU", "RSAFS", "DGS10", "DCOILWTICO", "ICSA"}
WORLD_MONEY_SERIES = {
    "EZ_M2_INDEX": ("Euro area M2, index of notional stocks, seasonally adjusted (ECB)", "index points", "monthly"),
    "JP_M2": ("Japan M2 money stock, average amounts outstanding (BoJ)", "JPY trillion", "monthly"),
    "TW_M1B": ("Taiwan M1B, daily average (CBC)", "NTD million", "monthly"),
    "TW_M2": ("Taiwan M2, daily average (CBC)", "NTD million", "monthly"),
}
DERIVED_SERIES = {
    "US_NET_LIQUIDITY": ("Fed net liquidity: total assets - TGA - overnight reverse repo", "USD billion", "weekly"),
}
CBC_SERIES = {
    "CBC_REDISCOUNT": ("Taiwan CBC rediscount rate", "percent", "daily"),
    "CBC_SECURED_LOAN": ("Taiwan CBC secured loan rate", "percent", "daily"),
    "CBC_SHORT_TERM_LOAN": ("Taiwan CBC short-term loan rate", "percent", "daily"),
}
TAIWAN_SERIES = {
    "CBC_USD_TWD": ("Taiwan interbank USD/TWD closing rate", "TWD/USD", "daily"),
    "TW_EXPORTS": ("Taiwan exports, customs value", "NTD thousand", "monthly"),
    "TW_IMPORTS": ("Taiwan imports, customs value", "NTD thousand", "monthly"),
}
TPEX_SERIES = {
    "TPEx_GOLD_TWD": ("Taiwan gold spot average transaction price", "TWD/tael", "daily"),
}
# Free daily market closes from the Yahoo chart API (no key; it rejects urllib's default agent).
# TPEx only publishes the latest gold quote, so the gold trend uses COMEX front-month futures; JPY and the ICE
# dollar index come from here instead of FRED so they do not consume the FRED daily budget.
YAHOO_SERIES = {
    "COMEX_GOLD_USD": ("COMEX gold futures (front month) daily close", "USD/troy oz", "daily"),
    "USD_JPY": ("Japanese yen per U.S. dollar, daily close", "JPY/USD", "daily"),
    "US_DOLLAR_INDEX": ("ICE U.S. Dollar Index (DXY), daily close", "index points", "daily"),
}
YAHOO_SYMBOLS = {"COMEX_GOLD_USD": "GC=F", "USD_JPY": "JPY=X", "US_DOLLAR_INDEX": "DX-Y.NYB"}
YAHOO_AGENT = {"User-Agent": "Mozilla/5.0 (compatible; maya-sawa macro dashboard)"}
DGBAS_COMMODITY_SERIES = {
    "WORLD_GOLD_USD": ("World Bank monthly gold price", "USD/troy oz", "monthly"),
}
DGBAS_SERIES = {
    "TW_EMPLOYED": ("Taiwan employed persons", "thousand persons", "monthly"),
    "TW_UNEMPLOYED": ("Taiwan unemployed persons", "thousand persons", "monthly"),
    "TW_PPI": ("Taiwan producer price index", "index points", "monthly"),
    "TW_CPI": ("Taiwan consumer price index, general", "index points", "monthly"),
    "TW_UNEMPLOYMENT_RATE": ("Taiwan unemployment rate (unemployed / labour force)", "percent", "monthly"),
}
UMICH_SERIES = {
    "UMICH_CPI_EXPECTED_1Y": ("Michigan median expected inflation over next 12 months", "percent", "monthly"),
}
PMI_SERIES = {
    "TW_PMI": ("Taiwan manufacturing PMI", "index points", "monthly"),
    "TW_NMI": ("Taiwan non-manufacturing NMI", "index points", "monthly"),
    "US_ISM_MFG_PMI": ("U.S. ISM manufacturing PMI", "index points", "monthly"),
    "US_ISM_SERVICES_PMI": ("U.S. ISM services PMI", "index points", "monthly"),
}
def _bounded_budget(name: str, default: int, ceiling: int) -> int:
    try: requested = int(os.getenv(name, str(default)))
    except ValueError: requested = default
    return max(1, min(requested, ceiling))


BLS_DAILY_BUDGET = _bounded_budget("MACRO_BLS_DAILY_BUDGET", 40, 40)
# 17 daily series, RSAFS/ICSA (persisted) and 5 release schedules run every 6-hour refresh
# (~96 calls/day); the 15 cached weekly/monthly/quarterly series are refetched once a day. A
# restart refetches all 39. The rest of the 200 covers deploys and manual recovery while
# remaining well below FRED's per-minute limit.
FRED_DAILY_BUDGET = _bounded_budget("MACRO_FRED_DAILY_BUDGET", 200, 200)


class LocalTTLCache:
    """Small process-local TTL cache for free, low-frequency macro source data."""
    def __init__(self, max_entries: int = 64):
        self._entries: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.RLock()
        self._max_entries = max_entries

    def get(self, key: str):
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return deepcopy(value)

    def set(self, key: str, value, ttl_seconds: int = 12 * 3600):
        with self._lock:
            self._entries[key] = (time.monotonic() + ttl_seconds, deepcopy(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


# One entry per cached series plus the raw responses of free sources (ECB, BoJ, CBC, DGBAS, ...).
_macro_local_cache = LocalTTLCache(max_entries=128)
LOCAL_MACRO_TTL_SECONDS = 12 * 3600
# Past freshForSeconds a series is shown as stale; past this window it is dropped.
FREE_SERIES_FALLBACK_SECONDS = 30 * 24 * 3600
FREE_HTTP_TTL_SECONDS = 4 * 3600
FREE_CACHE_CODES = (set(CBC_SERIES) | set(TAIWAN_SERIES) | set(TPEX_SERIES) | set(YAHOO_SERIES) | set(DGBAS_SERIES)
    | set(DGBAS_COMMODITY_SERIES) | set(UMICH_SERIES) | set(PMI_SERIES) | (set(FRED_SERIES) - FRED_PERSISTED)
    | set(WORLD_MONEY_SERIES) | set(DERIVED_SERIES) | set(ASIA_CPI_SERIES))


def parse_bis_cpi_csv(raw: bytes) -> list[dict]:
    rows = []
    for item in csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))):
        country, period, value = item.get('REF_AREA'), item.get('TIME_PERIOD', ''), item.get('OBS_VALUE', '')
        if country not in {'JP', 'KR'} or item.get('FREQ') != 'M' or item.get('UNIT_MEASURE') != '628' or not re.fullmatch(r'\d{4}-\d{2}', period):
            continue
        try: valid = math.isfinite(float(value)) and float(value) > 0
        except (TypeError, ValueError): valid = False
        if valid: rows.append({'code': f'{country}_CPI', 'period': period, 'value': value})
    return rows


# Money and central-bank liquidity series keep history since 2019, so charts show the 2020 expansion, the 2022-23
# contraction and the reverse repo draining to zero; two years of these slow-moving levels drew flat lines.
LONG_HISTORY_START = "2019-01"
LONG_HISTORY_CODES = {"M2SL", "WALCL", "WTREGEN", "RRPONTSYD", "ECBASSETSW", "JPNASSETS", "US_NET_LIQUIDITY"} | set(WORLD_MONEY_SERIES)


def fred_observation_start(code: str, frequency: str, today: date) -> str:
    """First FRED observation date requested: 2019 for liquidity, two years for daily/weekly, six years otherwise."""
    if code in LONG_HISTORY_CODES:
        return f"{LONG_HISTORY_START}-01"
    if frequency in ("daily", "weekly"):
        return (today - timedelta(days=730)).isoformat()
    return f"{today.year - 6}-01-01"


def snapshot_history(code: str, frequency: str, history: list[dict], months: int) -> list[dict]:
    """History sent to the dashboard: everything since 2019 for liquidity series, the usual window otherwise."""
    if code in LONG_HISTORY_CODES:
        return [row for row in history if row["period"] >= LONG_HISTORY_START]
    return history[-history_window(frequency, months):]


def history_window(frequency: str, months: int) -> int:
    """Observations per series in a snapshot: ~32 per month for daily, ~5 for weekly, at least 24 otherwise."""
    if frequency == "daily":
        return months * 32
    if frequency == "weekly":
        return months * 5
    return max(months, 24)


def _scaled(value: str, scale: float) -> str:
    if scale == 1:
        return value
    return f"{float(value) * scale:.10f}".rstrip("0").rstrip(".")


def fred_observation_rows(code: str, observations: list, frequency: str, scale: float = 1) -> list[dict]:
    """FRED observations -> rows. "." marks a missing day; daily/weekly keep the date, others keep YYYY-MM."""
    rows = []
    for item in observations:
        value = str(item.get("value") or "").strip()
        if not value or value == ".":
            continue
        try:
            observation_date = date.fromisoformat(item["date"])
            float(value)
        except (KeyError, ValueError, TypeError):
            continue
        period = observation_date.isoformat() if frequency in ("daily", "weekly") else observation_date.isoformat()[:7]
        rows.append({"code": code, "period": period, "value": _scaled(value, scale)})
    return rows


def parse_ecb_csv(raw: bytes, code: str) -> list[dict]:
    """ECB Data Portal csvdata: one row per TIME_PERIOD with OBS_VALUE; blanks and NaN are unpublished."""
    rows = []
    for item in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        period, value = str(item.get("TIME_PERIOD") or "").strip(), str(item.get("OBS_VALUE") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            continue
        try:
            if float(value) != float(value):
                continue
        except ValueError:
            continue
        rows.append({"code": code, "period": period, "value": value})
    return rows


def parse_boj_series(payload: dict, series_code: str, code: str, scale: float = 1) -> list[dict]:
    """BoJ Time-Series Data Search API (getDataCode): parallel SURVEY_DATES (YYYYMM) and VALUES arrays."""
    if payload.get("STATUS") != 200:
        raise RuntimeError(f"boj_status_{payload.get('STATUS')}:{payload.get('MESSAGEID')}")
    series = next((item for item in payload.get("RESULTSET") or [] if item.get("SERIES_CODE") == series_code), None)
    if not series:
        raise RuntimeError("boj_series_missing")
    values = series.get("VALUES") or {}
    rows = []
    for stamp, value in zip(values.get("SURVEY_DATES") or [], values.get("VALUES") or []):
        if value in (None, "") or not re.fullmatch(r"\d{6}", str(stamp)):
            continue
        rows.append({"code": code, "period": f"{str(stamp)[:4]}-{str(stamp)[4:]}", "value": _scaled(str(value), scale)})
    return rows


# EF15M01 rows: period, then 15 (level, YoY%) pairs; the last three pairs are M1A, M1B, M2. The column headers come
# back mis-encoded, so positions are fixed and a row with any other width is rejected.
CBC_MONEY_COLUMNS = {"TW_M1B": 27, "TW_M2": 29}


def parse_cbc_money_stock(payload: dict) -> list[dict]:
    rows = []
    for item in payload.get("data", {}).get("dataSets", []):
        if len(item) != 31:
            raise RuntimeError("cbc_money_stock_layout_changed")
        match = re.fullmatch(r"(\d{4})M(\d{2})", str(item[0]))
        if not match:
            continue
        for code, index in CBC_MONEY_COLUMNS.items():
            if re.fullmatch(r"\d+(?:\.\d+)?", str(item[index])):
                rows.append({"code": code, "period": f"{match.group(1)}-{match.group(2)}", "value": str(item[index])})
    return rows


def net_liquidity_rows(walcl: list[dict], tga: list[dict], rrp: list[dict]) -> list[dict]:
    """Weekly Fed net liquidity in USD billion: Wednesday total assets - Wednesday TGA - that day's ON RRP.
    RRP falls back to the latest day up to 7 days earlier (holidays); weeks missing either input are skipped."""
    tga_by_day = {row["period"]: float(row["value"]) for row in tga}
    rrp_days = sorted((row["period"], float(row["value"])) for row in rrp)
    rows = []
    for row in sorted(walcl, key=lambda item: item["period"]):
        day = row["period"]
        if day not in tga_by_day:
            continue
        floor = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
        reverse_repo = next((value for period, value in reversed(rrp_days) if floor <= period <= day), None)
        if reverse_repo is None:
            continue
        value = float(row["value"]) - tga_by_day[day] - reverse_repo
        rows.append({"code": "US_NET_LIQUIDITY", "period": day, "value": f"{value:.1f}"})
    return rows


def _request(url: str, body: dict | None = None, extra_headers: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    # Keep urllib's standard User-Agent and Accept headers. FRED stalls when it
    # receives the custom macro client headers, while its default headers return
    # the same payload immediately. BLS JSON POSTs still need an explicit type.
    # Only sources that reject urllib's agent (Yahoo chart) pass extra_headers.
    headers = {"Content-Type": "application/json"} if data else {}
    headers.update(extra_headers or {})
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        # Never persist URLs or response bodies from authenticated FRED requests.
        raise RuntimeError(f"upstream_http_{exc.code}") from None
    except Exception as exc:
        raise RuntimeError(type(exc).__name__) from None


def _request_free_cached(cache_key: str, url: str, ttl_seconds: int = FREE_HTTP_TTL_SECONDS,
                         extra_headers: dict | None = None) -> tuple[int, bytes]:
    """Cache public-source HTTP responses per Python process to avoid repeat calls."""
    key = f"http:{cache_key}"
    cached = _macro_local_cache.get(key)
    if cached is not None:
        return cached
    response = _request(url, extra_headers=extra_headers)
    _macro_local_cache.set(key, response, ttl_seconds)
    return response


def _record_run(source: str, status: str, count: int = 0, detail: str = "", http_status: int | None = None) -> None:
    # Summary diagnostics are not provider requests; the reserved request already records its own failure.
    if status == "error": status = "diagnostic_error"
    if not market_macro_db.sessions:
        return
    now = datetime.now(UTC)
    try:
        with market_macro_db.sessions.begin() as session:
            session.add(MacroFetchRun(source=source, started_at=now, finished_at=now, status=status,
                http_status=http_status, record_count=count, detail=detail[:80]))
    except Exception:
        logger.exception("Unable to persist macro source run: %s", source)


class _CalendarText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.text: list[str] = []
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.in_body = True
    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "header", "footer"):
            self.in_body = False
    def handle_data(self, data):
        if not self.in_body:
            self.text.append(data)


class MarketMacroService:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._cache: tuple[float, dict] | None = None
        self._sync_lock = threading.Lock()

    def _cache_free_series(self, rows: list[dict], definitions: dict, source: str, source_url: str,
        fresh_for_seconds: int = LOCAL_MACRO_TTL_SECONDS) -> int:
        """Keep free source observations in bounded process memory, not in maya_sawa_macro_observations.

        Each series is also copied to one row of maya_sawa_macro_cached_series so a restarted pod can
        serve it at once (restore_free_series_cache) instead of refetching against the daily budgets."""
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["code"], []).append({"period": row["period"], "value": str(row["value"])})
        fetched_at = datetime.now(UTC).isoformat()
        entries = []
        for code, series_rows in grouped.items():
            series_rows.sort(key=lambda item: item["period"])
            entry = {
                "code": code, "name": definitions[code][0], "unit": definitions[code][1],
                "frequency": definitions[code][2], "source": source, "sourceUrl": source_url,
                "fetchedAt": fetched_at, "freshForSeconds": fresh_for_seconds, "history": series_rows,
            }
            _macro_local_cache.set(f"series:{code}", entry, FREE_SERIES_FALLBACK_SECONDS)
            entries.append(entry)
        try:
            market_macro_db.save_cached_series(entries)
        except Exception:
            logger.warning("Unable to save the restart copy of %s macro series", source)
        self._cache = None
        return sum(len(items) for items in grouped.values())

    def restore_free_series_cache(self) -> int:
        """Reload the restart copy into process memory, keeping each series' original fetch time."""
        try:
            entries = market_macro_db.load_cached_series(max_age_days=FREE_SERIES_FALLBACK_SECONDS // 86400)
        except Exception:
            logger.warning("Unable to load the restart copy of macro series")
            return 0
        restored = 0
        for entry in entries:
            if entry.get("code") not in FREE_CACHE_CODES or _macro_local_cache.get(f"series:{entry['code']}"):
                continue
            age = (datetime.now(UTC) - datetime.fromisoformat(entry["fetchedAt"])).total_seconds()
            _macro_local_cache.set(f"series:{entry['code']}", entry, max(1, int(FREE_SERIES_FALLBACK_SECONDS - age)))
            restored += 1
        if restored:
            self._cache = None
        return restored

    async def start(self):
        if not MACRO_ENABLED:
            logger.info("Macro data collection disabled by MACRO_ENABLED")
            return
        if self._task and not self._task.done():
            return
        restored = await asyncio.to_thread(self.restore_free_series_cache)
        logger.info("Restored %d cached macro series", restored)
        self._task = asyncio.create_task(self._run_loop(), name="market-macro-refresh")

    async def close(self):
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            self._task = None

    async def _run_loop(self):
        # Daily scheduled data collection; all replicas serialize on a PostgreSQL advisory lock.
        while True:
            try:
                await self.refresh()
            except Exception:
                logger.exception("Macro scheduled refresh failed")
            # Four refreshes daily stay inside FRED_DAILY_BUDGET (see its comment).
            await asyncio.sleep(6 * 3600)

    async def refresh(self) -> dict:
        if not MACRO_ENABLED:
            return {"enabled": False, "reason": "disabled"}
        async with self._lock:
            return await asyncio.to_thread(self._refresh_sync)

    def _refresh_sync(self) -> dict:
        if not self._sync_lock.acquire(blocking=False):
            return {"enabled": True, "status": "already_running"}
        database_lock = None
        try:
            database_lock = market_macro_db.acquire_refresh_lock()
            if database_lock is None:
                return {"enabled": True, "status": "another_replica_or_database_unavailable"}
            output = {"enabled": True, "sources": {}}
            if FRED_KEY:
                # Calendar outages must not prevent the actual macro series from being
                # persisted. Each sync path records its own provider-call results.
                fred_result = {}
                for label, fetch in (("calendarEvents", self._fetch_fred_dates),
                                     ("rateObservations", self._fetch_fred_observations)):
                    try:
                        fred_result[label] = fetch()
                    except Exception as exc:
                        logger.warning("FRED %s refresh failed: %s", label, str(exc)[:80])
                        _record_run("FRED", "error", detail=f"{label}:{str(exc)[:60]}")
                output["sources"]["FRED"] = fred_result
            else:
                _record_run("FRED", "blocked", detail="missing_key")
                output["sources"]["FRED"] = "missing_key"
            if BLS_KEY:
                try: output["sources"]["BLS"] = self._fetch_bls()
                except Exception as exc:
                    logger.warning("BLS refresh failed: %s", str(exc)[:80]); _record_run("BLS", "error", detail=str(exc))
            else:
                _record_run("BLS", "blocked", detail="missing_key")
                output["sources"]["BLS"] = "missing_key"
            try: output["sources"]["FederalReserve"] = self._fetch_fed_calendar()
            except Exception as exc:
                logger.warning("Fed calendar refresh failed: %s", str(exc)[:80]); _record_run("FederalReserve", "error", detail=str(exc))
            for source_name, fetch in (("CBC", self._fetch_cbc_observations), ("TaiwanCustoms", self._fetch_taiwan_trade),
                ("TPExGold", self._fetch_tpex_gold), ("YahooMarkets", self._fetch_yahoo_markets),
                ("DGBAS", self._fetch_dgbas_employment),
                ("DGBASPrices", self._fetch_taiwan_prices),
                ("WorldBank", self._fetch_world_bank_gold),
                ("UMichInflation", self._fetch_umich_inflation_expectations),
                ("PMI", self._fetch_pmi_series),
                ("WorldMoney", self._fetch_world_money), ("BISCPI", self._fetch_asia_cpi)):
                try: output["sources"][source_name] = fetch()
                except Exception as exc:
                    logger.warning("%s refresh failed: %s", source_name, str(exc)[:80])
                    _record_run(source_name, "error", detail=str(exc)[:70])
            try: output["sources"]["FinanceCalendar"] = self._fetch_consensus_calendar()
            except Exception as exc:
                logger.warning("Consensus calendar refresh failed: %s", str(exc)[:80]); _record_run("FinanceCalendar", "error", detail=str(exc))
            market_macro_db.cleanup_fetch_runs(90)
            self._cache = None
            return output
        finally:
            market_macro_db.release_refresh_lock(database_lock)
            self._sync_lock.release()

    def _fetch_bls(self) -> int:
        run_id = market_macro_db.reserve_source_call("BLS", daily_limit=BLS_DAILY_BUDGET)
        if run_id is None:
            raise RuntimeError("bls_daily_or_minute_budget_exhausted")
        codes = list(BLS_SERIES)
        body = {"seriesid": codes, "startyear": str(date.today().year - 6), "endyear": str(date.today().year), "registrationkey": BLS_KEY}
        try:
            status, raw = _request("https://api.bls.gov/publicAPI/v2/timeseries/data/", body)
            response = json.loads(raw)
            if response.get("status") != "REQUEST_SUCCEEDED":
                raise RuntimeError("bls_request_not_succeeded")
            rows = []
            for series in response.get("Results", {}).get("series", []):
                for item in series.get("data", []):
                    period = str(item.get("period", ""))
                    if not re.fullmatch(r"M(0[1-9]|1[0-2])", period): continue
                    footnotes = item.get("footnotes") or []
                    rows.append({"code": series["seriesID"], "period": f"{item['year']}-{period[1:]}",
                        "value": item["value"], "preliminary": any(note.get("code") == "P" for note in footnotes)})
            previous_employment = market_macro_db.latest_period("CES0000000001")
            previous_cpi = market_macro_db.latest_period("CUSR0000SA0")
            previous_ppi = market_macro_db.latest_period("WPUFD4")
            newest = {code: max((row["period"] for row in rows if row["code"] == code), default=None)
                for code in ("CES0000000001", "CUSR0000SA0", "WPUFD4")}
            with market_macro_db.sessions.begin() as session:
                for code, (name, unit, frequency) in BLS_SERIES.items():
                    session.merge(MacroSeries(code=code, name=name, unit=unit, frequency=frequency, source="BLS"))
            saved = market_macro_db.save_observations("BLS", rows)
            if previous_employment and newest["CES0000000001"] and newest["CES0000000001"] > previous_employment:
                market_macro_db.record_observed_release("employment", newest["CES0000000001"], "https://www.bls.gov/news.release/empsit.htm")
            if previous_cpi and newest["CUSR0000SA0"] and newest["CUSR0000SA0"] > previous_cpi:
                market_macro_db.record_observed_release("cpi", newest["CUSR0000SA0"], "https://www.bls.gov/news.release/cpi.htm")
            if previous_ppi and newest["WPUFD4"] and newest["WPUFD4"] > previous_ppi:
                market_macro_db.record_observed_release("ppi", newest["WPUFD4"], "https://www.bls.gov/news.release/ppi.htm")
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_fred_dates(self) -> int:
        # FRED authenticated API is the canonical calendar source. api_key never enters persisted URL/logs.
        count = 0
        failures = 0
        for release_id, (group, title) in FRED_RELEASES.items():
            run_id = market_macro_db.reserve_source_call("FRED", daily_limit=FRED_DAILY_BUDGET, minute_limit=60)
            if run_id is None:
                raise RuntimeError("fred_daily_or_minute_budget_exhausted")
            params = urllib.parse.urlencode({"release_id": release_id, "file_type": "json", "include_release_dates_with_no_data": "true",
                # Keep the response to the recent schedule window. A larger page
                # can stall from the production pod even though smaller pages work.
                "sort_order": "desc", "limit": "20", "offset": "0", "api_key": FRED_KEY})
            try:
                status, raw = _request(f"https://api.stlouisfed.org/fred/release/dates?{params}")
                payload = json.loads(raw)
                rows = payload.get("release_dates")
                if not isinstance(rows, list): raise RuntimeError("fred_response_invalid")
                # The keyed FRED API is authoritative for dates; its calendar HTML may enrich those
                # dates with a displayed release time (US Central). If that page fails, retain date-only.
                try:
                    release_times = self._fred_calendar_times(release_id)
                except Exception as exc:
                    logger.info("FRED release-time supplement unavailable for release %s: %s", release_id, str(exc)[:60])
                    release_times = {}
                events = []
                for item in rows:
                    try: scheduled = date.fromisoformat(item["date"])
                    except (KeyError, ValueError, TypeError): continue
                    if not date.today() - timedelta(days=7) <= scheduled <= date.today() + timedelta(days=90): continue
                    # Monthly release identity remains stable if the day is revised.
                    source_period = scheduled.isoformat() if release_id == "180" else scheduled.strftime("%Y-%m")
                    source_id = f"{release_id}:{source_period}"
                    local_time = release_times.get(scheduled)
                    events.append({"id": f"fred:{source_id}", "sourceId": source_id, "groupId": group,
                        "type": group, "title": title, "scheduledDate": scheduled,
                        "scheduledAt": local_time.astimezone(UTC) if local_time else None,
                        "timePrecision": "minute" if local_time else "date",
                        "scheduleVerification": "confirmed" if local_time else "date_only",
                        "sourceUrl": "https://fred.stlouisfed.org/releases/calendar"})
                saved = market_macro_db.save_events("FRED", events); count += saved
                market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            except Exception as exc:
                market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
                failures += 1
                logger.warning("FRED release-date refresh failed for release %s: %s", release_id, str(exc)[:60])
        if failures == len(FRED_RELEASES):
            raise RuntimeError("fred_release_dates_all_failed")
        return count

    def _fetch_fred_observations(self) -> int:
        count = 0
        if market_macro_db.sessions:
            with market_macro_db.sessions.begin() as session:
                for code in FRED_PERSISTED:
                    name, unit, frequency = FRED_SERIES[code]
                    session.merge(MacroSeries(code=code, name=name, unit=unit, frequency=frequency, source="FRED"))
        failures = 0
        attempted = 0
        for code in FRED_SERIES:
            # Weekly/monthly/quarterly series change at most once a day; refetching them every 6 hours would
            # spend the FRED budget for nothing. Daily series and persisted series refresh every run.
            cached = _macro_local_cache.get(f"series:{code}") if code in FREE_CACHE_CODES else None
            if cached and FRED_SERIES[code][2] != "daily" and \
                    (datetime.now(UTC) - datetime.fromisoformat(cached["fetchedAt"])).total_seconds() < 24 * 3600:
                continue
            attempted += 1
            run_id = market_macro_db.reserve_source_call("FRED", daily_limit=FRED_DAILY_BUDGET, minute_limit=60)
            if run_id is None: raise RuntimeError("fred_daily_or_minute_budget_exhausted")
            params = urllib.parse.urlencode({"series_id": code, "file_type": "json",
                "observation_start": fred_observation_start(code, FRED_SERIES[code][2], date.today()),
                "sort_order": "asc", "limit": "10000", "api_key": FRED_KEY})
            if FRED_SERIES[code][2] == "monthly":
                params += "&" + urllib.parse.urlencode({"frequency": "m", "aggregation_method": "eop"})
            try:
                status, raw = _request(f"https://api.stlouisfed.org/fred/series/observations?{params}")
                payload = json.loads(raw)
                observations = payload.get("observations")
                if not isinstance(observations, list): raise RuntimeError("fred_observation_response_invalid")
                rows = fred_observation_rows(code, observations, FRED_SERIES[code][2], FRED_SCALE.get(code, 1))
                if code in FREE_CACHE_CODES:
                    # Low-frequency series are refetched daily, so they count as stale only after two missed days.
                    saved = self._cache_free_series(rows, FRED_SERIES, FRED_SOURCE_LABELS.get(code, "FRED"),
                        f"https://fred.stlouisfed.org/series/{code}",
                        fresh_for_seconds=12 * 3600 if FRED_SERIES[code][2] == "daily" else 48 * 3600)
                else:
                    saved = market_macro_db.save_observations("FRED", rows)
                count += saved
                market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            except Exception as exc:
                market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
                failures += 1
                logger.warning("FRED observation refresh failed for %s: %s", code, str(exc)[:60])
        if attempted and failures == attempted:
            raise RuntimeError("fred_observations_all_failed")
        histories = [(_macro_local_cache.get(f"series:{code}") or {}).get("history") or []
            for code in ("WALCL", "WTREGEN", "RRPONTSYD")]
        if all(histories):
            count += self._cache_free_series(net_liquidity_rows(*histories), DERIVED_SERIES, "FRED (derived)",
                "https://fred.stlouisfed.org/series/WALCL", fresh_for_seconds=48 * 3600)
        return count

    def _fetch_asia_cpi(self) -> int:
        cached = [_macro_local_cache.get(f'series:{code}') for code in ASIA_CPI_SERIES]
        if all(item and (datetime.now(UTC) - datetime.fromisoformat(item['fetchedAt'])).total_seconds() < 24 * 3600 for item in cached):
            return 0
        run_id = market_macro_db.reserve_source_call('BISCPI', daily_limit=8, minute_limit=2)
        if run_id is None: raise RuntimeError('bis_cpi_daily_budget_exhausted')
        try:
            url = 'https://stats.bis.org/api/v2/data/dataflow/BIS/WS_LONG_CPI/1.0/M.JP+KR.628?format=csv&startPeriod=' + LONG_HISTORY_START[:7]
            status, raw = _request_free_cached('bis:asia-cpi', url, ttl_seconds=12 * 3600)
            rows = parse_bis_cpi_csv(raw)
            if {row['code'] for row in rows} != set(ASIA_CPI_SERIES): raise RuntimeError('bis_cpi_response_incomplete')
            saved = self._cache_free_series(rows, ASIA_CPI_SERIES, 'BIS (national statistical sources)',
                'https://data.bis.org/topics/CPI', fresh_for_seconds=48 * 3600)
            market_macro_db.finish_source_call(run_id, 'success', saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, 'error', detail=str(exc))
            raise

    def _fetch_world_money(self) -> int:
        """Cache euro-area (ECB), Japan (BoJ) and Taiwan (CBC) money supply; FRED's OECD copies stopped in 2023."""
        run_id = market_macro_db.reserve_source_call("WorldMoney", daily_limit=12, minute_limit=3)
        if run_id is None: raise RuntimeError("world_money_daily_budget_exhausted")
        start_year = LONG_HISTORY_START[:4]
        sources = (
            ("ECB", "https://data-api.ecb.europa.eu/service/data/BSI/M.U2.Y.V.M20.X.I.U2.2300.Z01.E"
                f"?format=csvdata&detail=dataonly&startPeriod={start_year}-01",
                lambda raw: parse_ecb_csv(raw, "EZ_M2_INDEX"), "https://data.ecb.europa.eu/data/datasets/BSI"),
            ("BoJ", "https://www.stat-search.boj.or.jp/api/v1/getDataCode?format=json&lang=en&db=MD02"
                f"&code=MAM1NAM2M2MO&startDate={start_year}01",
                lambda raw: parse_boj_series(json.loads(raw), "MAM1NAM2M2MO", "JP_M2", scale=1 / 10000),
                "https://www.stat-search.boj.or.jp/"),
            ("CBC", "https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=EF15M01",
                lambda raw: [row for row in parse_cbc_money_stock(json.loads(raw)) if row["period"] >= f"{start_year}-01"],
                "https://cpx.cbc.gov.tw/Data/ExportToAPIInfo"),
        )
        saved, failures, status = 0, [], None
        for source, url, parse, source_url in sources:
            try:
                status, raw = _request_free_cached(f"world-money:{source}", url, ttl_seconds=12 * 3600)
                rows = parse(raw)
                if not rows:
                    raise RuntimeError("empty")
                saved += self._cache_free_series(rows, WORLD_MONEY_SERIES, source, source_url, fresh_for_seconds=48 * 3600)
            except Exception as exc:
                failures.append(f"{source}:{str(exc)[:30]}")
        if len(failures) == len(sources):
            market_macro_db.finish_source_call(run_id, "error", detail=";".join(failures))
            raise RuntimeError("world_money_all_sources_failed")
        market_macro_db.finish_source_call(run_id, "success", saved, detail=";".join(failures), http_status=status)
        return saved

    def _fetch_cbc_observations(self) -> int:
        """Persist official CBC policy-rate history and daily interbank USD/TWD history."""
        rows = []
        # CBC publishes the policy-rate history as [date, rediscount, secured loan, short-term loan].
        run_id = market_macro_db.reserve_source_call("CBC", daily_limit=24, minute_limit=5)
        if run_id is None: raise RuntimeError("cbc_daily_budget_exhausted")
        try:
            status, raw = _request_free_cached("cbc:EG28D01", "https://cpx.cbc.gov.tw/API/DataAPI/Get?FileName=EG28D01")
            payload = json.loads(raw)
            rows = []
            for item in payload.get("data", {}).get("dataSets", []):
                if len(item) < 4 or not re.fullmatch(r"\d{8}", str(item[0])): continue
                period = f"{item[0][:4]}-{item[0][4:6]}-{item[0][6:8]}"
                for code, index in (("CBC_REDISCOUNT", 1), ("CBC_SECURED_LOAN", 2), ("CBC_SHORT_TERM_LOAN", 3)):
                    if item[index] not in (None, "", "-"):
                        rows.append({"code": code, "period": period, "value": item[index]})
            policy_rows = rows
            market_macro_db.finish_source_call(run_id, "success", len(rows), http_status=status)
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

        # Official open data API, sourced by CBC from Taipei Forex Inc.; only retain recent history.
        run_id = market_macro_db.reserve_source_call("CBC", daily_limit=24, minute_limit=5)
        if run_id is None: raise RuntimeError("cbc_daily_budget_exhausted")
        try:
            status, raw = _request_free_cached("cbc:FTDOpenData_Day", "https://cpx.cbc.gov.tw/api/OpenData/FTDOpenData_Day")
            payload = json.loads(raw)
            fx_rows = []
            cutoff = date.today() - timedelta(days=365 * 6)
            for item in payload if isinstance(payload, list) else []:
                raw_date = str(item.get("\u65e5\u671f", ""))
                try: observation_date = datetime.strptime(raw_date, "%Y%m%d").date()
                except ValueError: continue
                if observation_date < cutoff: continue
                value = item.get("NTD_USD")
                if value in (None, "", "-"): continue
                fx_rows.append({"code": "CBC_USD_TWD", "period": observation_date.isoformat(), "value": value})
            market_macro_db.finish_source_call(run_id, "success", len(fx_rows), http_status=status)
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise
        return self._cache_free_series(policy_rows + fx_rows, {**CBC_SERIES, "CBC_USD_TWD": TAIWAN_SERIES["CBC_USD_TWD"]},
            "CBC", "https://cpx.cbc.gov.tw/Data/ExportToAPIInfo")

    def _fetch_taiwan_trade(self) -> int:
        """Persist Taiwan's free monthly Customs exports/imports CSV, including revisions."""
        run_id = market_macro_db.reserve_source_call("TaiwanCustoms", daily_limit=4, minute_limit=2)
        if run_id is None: raise RuntimeError("customs_daily_budget_exhausted")
        try:
            status, raw = _request_free_cached("customs:6053", "https://opendata.customs.gov.tw/data/6053/csv.csv")
            import csv
            import io
            rows = []
            export_field = "\u51fa\u53e3\u7e3d\u503c(\u65b0\u81fa\u5e63\u5343\u5143)"
            import_field = "\u9032\u53e3\u7e3d\u503c(\u65b0\u81fa\u5e63\u5343\u5143)"
            for item in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
                year = re.sub(r"\D", "", item.get("\u5e74\u5ea6", ""))
                month = re.sub(r"\D", "", item.get("\u6708\u4efd", ""))
                if len(year) != 3 or not month: continue
                period = f"{int(year) + 1911:04d}-{int(month):02d}"
                for code, field in (("TW_EXPORTS", export_field), ("TW_IMPORTS", import_field)):
                    value = re.sub(r"[^0-9.-]", "", item.get(field, ""))
                    if value: rows.append({"code": code, "period": period, "value": value})
            saved = self._cache_free_series(rows, TAIWAN_SERIES, "TaiwanCustoms", "https://data.gov.tw/dataset/6053")
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_tpex_gold(self) -> int:
        """Persist the free daily TPEx Taiwan-bank gold spot quote (TWD per tael)."""
        run_id = market_macro_db.reserve_source_call("TPEx", daily_limit=24, minute_limit=5)
        if run_id is None: raise RuntimeError("tpex_gold_daily_budget_exhausted")
        try:
            status, raw = _request_free_cached("tpex:gold_latest", "https://www.tpex.org.tw/openapi/v1/tpex_gold_latest")
            payload = json.loads(raw)
            rows = []
            for item in payload if isinstance(payload, list) else []:
                raw_date = str(item.get("Date", ""))
                try:
                    if len(raw_date) == 7:
                        observation_date = date(int(raw_date[:3]) + 1911, int(raw_date[3:5]), int(raw_date[5:7]))
                    else:
                        observation_date = datetime.strptime(raw_date, "%Y%m%d").date()
                except ValueError: continue
                value = item.get("TradingAvg.") or item.get("TradingLatestTradingInfo.LatestPrice")
                if value in (None, "", "-"): continue
                rows.append({"code": "TPEx_GOLD_TWD", "period": observation_date.isoformat(), "value": value})
            saved = self._cache_free_series(rows, TPEX_SERIES, "TPEx", "https://www.tpex.org.tw/openapi/")
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_yahoo_markets(self) -> int:
        """Cache one year of daily closes per Yahoo symbol; one failing symbol does not drop the others."""
        run_id = market_macro_db.reserve_source_call("Yahoo", daily_limit=12, minute_limit=2)
        if run_id is None: raise RuntimeError("yahoo_daily_budget_exhausted")
        saved, failures, status = 0, [], None
        for code, symbol in YAHOO_SYMBOLS.items():
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1y&interval=1d"
                status, raw = _request_free_cached(f"yahoo:{symbol}:1y", url, ttl_seconds=6 * 3600, extra_headers=YAHOO_AGENT)
                result = (json.loads(raw).get("chart", {}).get("result") or [{}])[0]
                zone = ZoneInfo(result.get("meta", {}).get("exchangeTimezoneName") or "America/New_York")
                closes = ((result.get("indicators", {}).get("quote") or [{}])[0]).get("close") or []
                rows = [{"code": code, "period": datetime.fromtimestamp(stamp, zone).date().isoformat(), "value": round(close, 2)}
                    for stamp, close in zip(result.get("timestamp") or [], closes) if close]
                saved += self._cache_free_series(rows, YAHOO_SERIES, "Yahoo Finance",
                    f"https://finance.yahoo.com/quote/{urllib.parse.quote(symbol)}/")
            except Exception as exc:
                failures.append(f"{code}:{str(exc)[:30]}")
        if len(failures) == len(YAHOO_SYMBOLS):
            market_macro_db.finish_source_call(run_id, "error", detail=";".join(failures))
            raise RuntimeError("yahoo_all_symbols_failed")
        market_macro_db.finish_source_call(run_id, "success", saved, detail=";".join(failures), http_status=status)
        return saved

    def _fetch_dgbas_employment(self) -> int:
        """Cache free DGBAS employment/unemployment totals; the API is monthly and anonymous."""
        run_id = market_macro_db.reserve_source_call("DGBAS", daily_limit=24, minute_limit=5)
        if run_id is None: raise RuntimeError("dgbas_daily_budget_exhausted")
        try:
            today = date.today()
            end_year, end_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
            start_year, start_month = end_year - 2, end_month + 1
            if start_month > 12:
                start_year, start_month = start_year + 1, 1
            start_period = f"{start_year}-M{start_month}"
            end_period = f"{end_year}-M{end_month}"
            rows = []
            saved_http_status = None
            for code, stat_id in (("TW_EMPLOYED", "1"), ("TW_UNEMPLOYED", "2")):
                path = f"A040101020/{stat_id}.1.1.M"
                query = urllib.parse.urlencode({"startTime": start_period, "endTime": end_period})
                url = f"https://nstatdb.dgbas.gov.tw/dgbasAll/webMain.aspx?sdmx/{path}&{query}"
                status, raw = _request_free_cached(f"dgbas:{code}:{start_period}:{end_period}", url)
                saved_http_status = status
                payload = json.loads(raw)
                data = payload.get("data", {})
                data_set = (data.get("dataSets") or [{}])[0]
                periods = data.get("structure", {}).get("dimensions", {}).get("observation", [{}])[0].get("values", [])
                series = next(iter(data_set.get("series", {}).values()), {})
                for period_index, values in series.get("observations", {}).items():
                    index = int(period_index)
                    # DGBAS fills months not yet published with 0; a population count is never 0.
                    if index >= len(periods) or not values or values[0] in (None, "") or float(values[0]) == 0:
                        continue
                    period = str(periods[index].get("id", ""))
                    match = re.fullmatch(r"(\d{4})-M(\d{1,2})", period)
                    if match:
                        rows.append({"code": code, "period": f"{match.group(1)}-{int(match.group(2)):02d}", "value": values[0]})
            # DGBAS defines the unemployment rate as unemployed / labour force (employed + unemployed).
            counts: dict[str, dict[str, float]] = {}
            for row in rows:
                counts.setdefault(row["period"], {})[row["code"]] = float(row["value"])
            for period, pair in sorted(counts.items()):
                employed, unemployed = pair.get("TW_EMPLOYED"), pair.get("TW_UNEMPLOYED")
                if employed and unemployed:
                    rows.append({"code": "TW_UNEMPLOYMENT_RATE", "period": period, "value": round(unemployed / (employed + unemployed) * 100, 2)})
            saved = self._cache_free_series(rows, DGBAS_SERIES, "DGBAS", "https://nstatdb.dgbas.gov.tw/dgbasAll/")
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=saved_http_status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_taiwan_prices(self) -> int:
        """Cache Taiwan's official CPI and PPI general indices from DGBAS, in process memory only."""
        run_id = market_macro_db.reserve_source_call("DGBASPrices", daily_limit=12, minute_limit=3)
        if run_id is None: raise RuntimeError("dgbas_prices_daily_budget_exhausted")
        try:
            today = date.today()
            end_year, end_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
            start_period = f"{end_year - 6}-M{end_month}"
            end_period = f"{end_year}-M{end_month}"
            query = urllib.parse.urlencode({"startTime": start_period, "endTime": end_period})
            rows = []
            status = None
            for code, table in (("TW_CPI", "A030101015"), ("TW_PPI", "A030701015")):
                url = f"https://nstatdb.dgbas.gov.tw/dgbasAll/webMain.aspx?sdmx/{table}/1.1.1.M&{query}"
                status, raw = _request_free_cached(f"dgbas:{code}:{start_period}:{end_period}", url, ttl_seconds=12 * 3600)
                data = json.loads(raw).get("data", {})
                data_set = (data.get("dataSets") or [{}])[0]
                periods = data.get("structure", {}).get("dimensions", {}).get("observation", [{}])[0].get("values", [])
                series = next(iter(data_set.get("series", {}).values()), {})
                for period_index, values in series.get("observations", {}).items():
                    index = int(period_index)
                    # Unpublished months come back as 0 or blank; an index level is never 0.
                    if index >= len(periods) or not values or values[0] in (None, "") or float(values[0]) == 0:
                        continue
                    match = re.fullmatch(r"(\d{4})-M(\d{1,2})", str(periods[index].get("id", "")))
                    if match:
                        rows.append({"code": code, "period": f"{match.group(1)}-{int(match.group(2)):02d}", "value": values[0]})
            if not rows:
                raise RuntimeError("dgbas_price_observations_empty")
            saved = self._cache_free_series(rows, DGBAS_SERIES, "DGBAS", "https://nstatdb.dgbas.gov.tw/dgbasAll/", fresh_for_seconds=12 * 3600)
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_pmi_series(self) -> int:
        """Cache Taiwan PMI/NMI history from CIER's published monthly trend tables."""
        cache_key = "series:TW_PMI"
        existing = _macro_local_cache.get(cache_key)
        if existing and (datetime.now(UTC) - datetime.fromisoformat(existing["fetchedAt"])).total_seconds() < 12 * 3600:
            return sum(len((_macro_local_cache.get(f"series:{code}") or {}).get("history", [])) for code in PMI_SERIES if code.startswith("TW_"))
        run_id = market_macro_db.reserve_source_call("PMI", daily_limit=8, minute_limit=2)
        if run_id is None: raise RuntimeError("pmi_daily_budget_exhausted")
        try:
            status, raw = _request_free_cached("cier:pmi-trend", "https://www.cier.edu.tw/pmi-trend/", ttl_seconds=12 * 3600)
            html = raw.decode("utf-8", errors="replace")
            tables = re.findall(r"<table\b[^>]*>(.*?)</table>", html, flags=re.I | re.S)
            output: dict[str, list[dict]] = {"TW_PMI": [], "TW_NMI": []}
            for table in tables:
                text = unescape(re.sub(r"<[^>]+>", " ", table))
                code = "TW_PMI" if "臺灣製造業PMI" in text else "TW_NMI" if "臺灣非製造業NMI" in text else None
                if not code:
                    continue
                for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table, flags=re.I | re.S):
                    cells = [unescape(re.sub(r"<[^>]+>", " ", cell)).strip() for cell in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, flags=re.I | re.S)]
                    if len(cells) < 2:
                        continue
                    period_match = re.fullmatch(r"(\d{4})/(\d{1,2})", cells[0])
                    value_match = re.search(r"\d+(?:\.\d+)?", cells[1].replace(",", ""))
                    if period_match and value_match:
                        output[code].append({"code": code, "period": f"{period_match.group(1)}-{int(period_match.group(2)):02d}", "value": value_match.group(0)})
            if not output["TW_PMI"] or not output["TW_NMI"]:
                raise RuntimeError("cier_pmi_tables_incomplete")
            saved = self._cache_free_series(output["TW_PMI"] + output["TW_NMI"], PMI_SERIES, "CIER", "https://www.cier.edu.tw/pmi-trend/", fresh_for_seconds=12 * 3600)
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_umich_inflation_expectations(self) -> int:
        """Cache the University of Michigan's official monthly one-year inflation expectations CSV."""
        code = "UMICH_CPI_EXPECTED_1Y"
        existing = _macro_local_cache.get(f"series:{code}")
        if existing and (datetime.now(UTC) - datetime.fromisoformat(existing["fetchedAt"])).total_seconds() < 12 * 3600:
            return len(existing["history"])
        run_id = market_macro_db.reserve_source_call("UMichInflation", daily_limit=4, minute_limit=2)
        if run_id is None:
            raise RuntimeError("umich_inflation_daily_budget_exhausted")
        source_url = "https://www.sca.isr.umich.edu/files/tbcpx1px5.csv"
        try:
            status, raw = _request_free_cached("umich:inflation-expectations", source_url, ttl_seconds=12 * 3600)
            text = raw.decode("utf-8-sig", errors="replace")
            rows = csv.reader(text.splitlines())
            observations = []
            for row in rows:
                if len(row) < 4:
                    continue
                date_match = re.fullmatch(r"([A-Za-z]+)(?:\s*\([^)]*\))?", row[0].strip())
                if not date_match or not re.fullmatch(r"\d{4}", row[1].strip()):
                    continue
                try:
                    period = datetime.strptime(f"{date_match.group(1)} {row[1].strip()}", "%B %Y").strftime("%Y-%m")
                except ValueError:
                    continue
                value = row[3].strip()
                if re.fullmatch(r"\d+(?:\.\d+)?", value):
                    observations.append({"code": code, "period": period, "value": value})
            if not observations:
                raise RuntimeError("umich_inflation_csv_empty")
            saved = self._cache_free_series(observations, UMICH_SERIES, "University of Michigan Surveys of Consumers",
                "https://www.sca.isr.umich.edu/tables.html", fresh_for_seconds=12 * 3600)
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_world_bank_gold(self) -> int:
        """Load the free World Bank monthly gold history into process-local memory only."""
        existing = _macro_local_cache.get("series:WORLD_GOLD_USD")
        if existing and (datetime.now(UTC) - datetime.fromisoformat(existing["fetchedAt"])).total_seconds() < 45 * 24 * 3600:
            return len(existing["history"])
        run_id = market_macro_db.reserve_source_call("WorldBank", daily_limit=4, minute_limit=2)
        if run_id is None: raise RuntimeError("world_bank_daily_budget_exhausted")
        try:
            _, catalog = _request_free_cached("worldbank:catalog", "https://www.worldbank.org/en/research/commodity-markets", ttl_seconds=24 * 3600)
            match = re.search(r"href=[\"']([^\"']*CMO-Historical-Data-Monthly\.xlsx[^\"']*)[\"']", catalog.decode("utf-8", errors="replace"), re.I)
            if not match:
                raise RuntimeError("world_bank_monthly_file_link_missing")
            url = urllib.parse.urljoin("https://www.worldbank.org", unescape(match.group(1)))
            status, raw = _request_free_cached("worldbank:pink-sheet-monthly", url, ttl_seconds=45 * 24 * 3600)
            namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            with zipfile.ZipFile(io.BytesIO(raw)) as workbook:
                shared_root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
                shared = ["".join(node.text or "" for node in item.findall(".//x:t", namespace))
                    for item in shared_root.findall("x:si", namespace)]
                sheet = ET.fromstring(workbook.read("xl/worksheets/sheet2.xml"))
            rows = []
            for row in sheet.findall(".//x:sheetData/x:row", namespace):
                cells = {cell.attrib.get("r", ""): cell for cell in row.findall("x:c", namespace)}
                date_cell, gold_cell = cells.get(f"A{row.attrib.get('r')}"), cells.get(f"BR{row.attrib.get('r')}")
                if date_cell is None or gold_cell is None:
                    continue
                def cell_value(cell):
                    value = cell.find("x:v", namespace)
                    if value is None:
                        return ""
                    return shared[int(value.text)] if cell.attrib.get("t") == "s" else value.text or ""
                period_match = re.fullmatch(r"(\d{4})M(\d{1,2})", cell_value(date_cell).strip())
                price = cell_value(gold_cell).strip()
                if not period_match or not re.fullmatch(r"\d+(?:\.\d+)?", price):
                    continue
                rows.append({"code": "WORLD_GOLD_USD", "period": f"{period_match.group(1)}-{int(period_match.group(2)):02d}", "value": price})
            saved = self._cache_free_series(rows, DGBAS_COMMODITY_SERIES, "WorldBank", url, fresh_for_seconds=45 * 24 * 3600)
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fred_calendar_times(self, release_id: str) -> dict[date, datetime]:
        today = date.today()
        params = urllib.parse.urlencode({"rid": release_id, "vs": (today - timedelta(days=7)).isoformat(),
            "ve": (today + timedelta(days=90)).isoformat(), "ob": "rd"})
        status, raw = _request(f"https://fred.stlouisfed.org/releases/calendar?{params}")
        html = raw.decode("utf-8", errors="replace")
        result: dict[date, datetime] = {}
        current_date: date | None = None
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.I | re.S):
            plain = re.sub(r"<[^>]+>", " ", row)
            plain = re.sub(r"\s+", " ", plain).strip()
            date_match = re.search(r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})", plain)
            if date_match:
                try: current_date = datetime.strptime(" ".join(date_match.groups()), "%B %d %Y").date()
                except ValueError: current_date = None
                continue
            time_match = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)\b", plain, re.I)
            if current_date and time_match:
                try:
                    hour, minute = int(time_match.group(1)), int(time_match.group(2))
                    if time_match.group(3).lower() == "pm" and hour != 12: hour += 12
                    if time_match.group(3).lower() == "am" and hour == 12: hour = 0
                    result[current_date] = datetime(current_date.year, current_date.month, current_date.day,
                        hour, minute, tzinfo=CENTRAL)
                except ValueError: continue
        return result

    def _fetch_fed_calendar(self) -> int:
        run_id = market_macro_db.reserve_source_call("FederalReserve", daily_limit=24, minute_limit=3)
        if run_id is None:
            raise RuntimeError("fed_calendar_budget_exhausted")
        try:
            return self._fetch_fed_calendar_reserved(run_id)
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

    def _fetch_consensus_calendar(self) -> int:
        """Cache calendar history and upcoming releases so CPI consensus can be charted beside actuals."""
        today = date.today()
        windows = ((today - timedelta(days=90), today), (today + timedelta(days=1), today + timedelta(days=90)))
        events_by_id: dict[str, dict] = {}
        for start, end in windows:
            run_id = market_macro_db.reserve_source_call("FinanceCalendar", daily_limit=8, minute_limit=2)
            if run_id is None:
                raise RuntimeError("consensus_calendar_budget_exhausted")
            try:
                query = urllib.parse.urlencode({"from": start.isoformat(), "to": end.isoformat(), "limit": "500"})
                status, raw = _request(f"https://www.financecalendar.com/wp-json/fc/v1/calendar?{query}")
                payload = json.loads(raw)
                if not isinstance(payload.get("events"), list):
                    raise RuntimeError("consensus_calendar_response_invalid")
                for item in payload["events"]:
                    title = str(item.get("title") or item.get("name") or "")
                    lowered = title.lower()
                    country = str(item.get("country") or item.get("country_code") or item.get("region") or "").strip().lower()
                    international_label = {'jp': 'Japan', 'jpn': 'Japan', 'japan': 'Japan',
                        'kr': 'Korea', 'kor': 'Korea', 'korea': 'Korea', 'south korea': 'Korea',
                        'eu': 'Euro area', 'ea': 'Euro area', 'euro area': 'Euro area', 'eurozone': 'Euro area',
                        'gb': 'UK', 'uk': 'UK', 'gbr': 'UK', 'united kingdom': 'UK'}.get(country)
                    is_us = country in {"us", "usa", "united states", "united states of america"} or bool(re.search(r"(?:\bu\.s\.\s|\bus\s|\bunited states\b)", lowered))
                    is_uk = country in {"gb", "uk", "gbr", "united kingdom", "great britain"} or bool(re.match(r"\s*(?:uk\s|u\.k\.\s)", lowered))
                    group = None
                    if "fomc" in lowered and ("decision" in lowered or "rate" in lowered):
                        group = "fed"
                    elif "cpi" in lowered and is_us:
                        group = "cpi"
                    elif "ppi" in lowered and is_us:
                        group = "ppi"
                    elif ("retail sales" in lowered or "retail trade" in lowered) and (is_us or is_uk):
                        group = "retail_sales"
                    elif any(term in lowered for term in ("nonfarm payroll", "employment situation", "us jobs report")):
                        group = "employment"
                    elif is_us and any(term in lowered for term in ("jobless claims", "initial claims", "weekly claims")):
                        group = "claims"
                    elif is_us and str(item.get("impact") or "").strip().lower() in {"medium", "high"} and any(term in lowered for term in (
                        "gdp", "gross domestic product", "pce", "personal consumption", "personal income", "personal spending",
                        "durable goods", "industrial production", "housing starts", "building permits", "new home sales",
                        "existing home sales", "consumer confidence", "consumer sentiment", "michigan sentiment", "trade balance",
                        "business inventories", "factory orders", "consumer credit", "leading indicators", "ism manufacturing",
                        "ism services", " ism pmi", "jobless claims", "initial claims", "weekly claims")):
                        group = "other"
                    if not group and international_label and str(item.get('impact') or '').lower() in {'medium', 'high'} and any(
                        term in lowered for term in ('cpi', 'inflation', 'unemployment', 'employment', 'interest rate',
                            'rate decision', 'retail sales', 'retail trade', 'exports', 'imports', 'trade balance', 'gdp', 'industrial production')):
                        group = 'other'
                    if not group:
                        continue
                    try:
                        scheduled = date.fromisoformat(str(item["date"])[:10])
                    except (KeyError, ValueError, TypeError):
                        continue
                    raw_time = item.get("time_utc")
                    try:
                        scheduled_at = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00")) if raw_time else None
                    except ValueError:
                        scheduled_at = None
                    source_url = str(item.get("url") or "https://www.financecalendar.com/api/")
                    consensus, actual = item.get("consensus"), item.get("actual")
                    # Multiple countries and multiple releases can share a calendar date.
                    # Keep their identities distinct so one event cannot overwrite another.
                    event_title = f"UK {title}" if group == "retail_sales" and is_uk and not lowered.startswith(("uk ", "u.k.")) else title
                    if group == 'other' and international_label and not lowered.startswith(international_label.lower()):
                        event_title = f'{international_label} {title}'
                    title_key = hashlib.sha256(f"{country}:{title}".casefold().encode("utf-8")).hexdigest()[:12]
                    use_title_key = group == "other" or (group == "retail_sales" and is_uk)
                    identity = f"{scheduled.isoformat()}:{title_key}" if use_title_key else scheduled.isoformat()
                    event_id = f"financecalendar:{group}:{identity}"
                    protected_ism = group == "other" and "ism" in lowered
                    events_by_id[event_id] = {"id": event_id, "sourceId": f"{group}:{identity}",
                        "groupId": group, "type": group, "title": event_title, "scheduledDate": scheduled,
                        "scheduledAt": scheduled_at, "timePrecision": "minute" if scheduled_at else "date",
                        "scheduleVerification": "confirmed" if scheduled_at else "date_only",
                        "consensusValue": str(consensus) if not protected_ism and consensus not in (None, "") else None,
                        "actualValue": str(actual) if not protected_ism and actual not in (None, "") else None,
                        "expectationSource": "Finance Calendar", "sourceUrl": source_url}
                market_macro_db.finish_source_call(run_id, "success", len(payload["events"]), http_status=status)
            except Exception as exc:
                market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
                raise
        saved = market_macro_db.update_event_expectations(list(events_by_id.values()))
        return saved

    def _fetch_fed_calendar_reserved(self, run_id: int) -> int:
        status, raw = _request("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm")
        parser = _CalendarText(); parser.feed(raw.decode("utf-8", errors="replace"))
        text = " ".join(" ".join(parser.text).split())
        year = date.today().year
        events = []
        # Restrict parsing to calendar table rows; a free-text page scan can mistake unrelated dates for meetings.
        rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", raw.decode("utf-8", errors="replace"), flags=re.I | re.S)
        current_year = year
        for raw_row in rows:
            row_text = re.sub(r"<[^>]+>", " ", raw_row)
            row_text = re.sub(r"\s+", " ", row_text).strip()
            year_match = re.search(r"\b(20\d{2})\b", row_text)
            month_match = re.search(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*(?:[–-]\s*(\d{1,2}))?\b", row_text, re.I)
            if year_match and not month_match:
                current_year = int(year_match.group(1))
            if not month_match:
                continue
            month_name, first_day, meeting_end_day = month_match.groups()
            # FOMC statements follow the final meeting day; do not flag the opening day as the release.
            day = meeting_end_day or first_day
            yr = int(year_match.group(1)) if year_match else current_year
            try: scheduled = date(yr, datetime.strptime(month_name, "%B").month, int(day))
            except ValueError: continue
            if date.today() - timedelta(days=3) <= scheduled <= date.today() + timedelta(days=400):
                source_id = f"fomc:{scheduled:%Y-%m}"
                events.append({"id": f"fed:{source_id}", "sourceId": source_id, "groupId": "fed",
                    "type": "fed_rate_decision", "title": "FOMC rate decision", "scheduledDate": scheduled,
                    "scheduledAt": None, "timePrecision": "date", "scheduleVerification": "expected",
                    "sourceUrl": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"})
        # De-duplicate repeated month/date strings from surrounding page text.
        unique = {event["id"]: event for event in events}
        saved = market_macro_db.save_events("FederalReserve", list(unique.values()))
        market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
        return saved

    async def get(self, history_months: int = 24) -> dict:
        if self._cache and time.monotonic() - self._cache[0] < 300:
            result = deepcopy(self._cache[1])
        else:
            result = await asyncio.to_thread(market_macro_db.snapshot, min(max(history_months, 12), 60))
            result["enabled"] = MACRO_ENABLED
            result["configuration"] = {"BLS": "configured" if BLS_KEY else "missing_key", "FRED": "configured" if FRED_KEY else "missing_key"}
            self._cache = (time.monotonic(), deepcopy(result))
        local_indicators = []
        for code in FREE_CACHE_CODES:
            series = _macro_local_cache.get(f"series:{code}")
            if not series or not series["history"]:
                continue
            history = series["history"]
            latest = history[-1]
            previous = history[-2] if len(history) > 1 else None
            local_indicators.append({
                "code": code, "name": series["name"], "unit": series["unit"], "frequency": series["frequency"],
                "value": latest["value"], "referencePeriod": latest["period"],
                "previousValue": previous["value"] if previous else None,
                "previousPeriod": previous["period"] if previous else None,
                "change": float(latest["value"]) - float(previous["value"]) if previous else None,
                "source": series["source"], "sourceUrl": series["sourceUrl"], "fetchedAt": series["fetchedAt"],
                "cacheStale": (datetime.now(UTC) - datetime.fromisoformat(series["fetchedAt"])).total_seconds() > series.get("freshForSeconds", LOCAL_MACRO_TTL_SECONDS),
                "history": snapshot_history(code, series["frequency"], history, history_months),
            })
        result["indicators"] = [item for item in result.get("indicators", []) if item.get("code") not in FREE_CACHE_CODES] + local_indicators
        umich = next((item for item in local_indicators if item["code"] == "UMICH_CPI_EXPECTED_1Y"), None)
        if umich:
            for indicator in result["indicators"]:
                if indicator.get("code") == "CUUR0000SA0":
                    indicator["expectationHistory"] = [{**point, "source": umich["source"], "sourceUrl": umich["sourceUrl"]}
                        for point in umich["history"]]
        if local_indicators:
            result["status"] = "ready"
        known_sources = {item.get("source") for item in result.get("sources", [])}
        for source in {item["source"] for item in local_indicators} - known_sources:
            result.setdefault("sources", []).append({"source": source, "availability": "success", "stale": False,
                "lastSuccessAt": next(item["fetchedAt"] for item in local_indicators if item["source"] == source)})
        result["asOf"] = datetime.now(UTC).isoformat()
        return result


market_macro_service = MarketMacroService()
