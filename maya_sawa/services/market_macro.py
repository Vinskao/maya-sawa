"""Low-frequency, persisted US macro data from registered BLS/FRED APIs and the Fed calendar."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
import logging
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
}
FRED_RELEASES = {
    "50": ("employment", "Nonfarm payrolls / Employment Situation"),
    "10": ("cpi", "CPI / Consumer Price Index"),
    "9": ("retail_sales", "Advance Monthly Sales for Retail and Food Services"),
}
FRED_SERIES = {
    "DFEDTARL": ("Federal funds target range, lower limit", "percent", "daily"),
    "DFEDTARU": ("Federal funds target range, upper limit", "percent", "daily"),
    "RSAFS": ("Advance retail sales and food services", "millions of dollars", "monthly"),
    "DGS10": ("10-year Treasury constant maturity yield", "percent", "daily"),
    "DCOILWTICO": ("WTI crude oil spot price", "USD/barrel", "daily"),
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
DGBAS_COMMODITY_SERIES = {
    "WORLD_GOLD_USD": ("World Bank monthly gold price", "USD/troy oz", "monthly"),
}
DGBAS_SERIES = {
    "TW_EMPLOYED": ("Taiwan employed persons", "thousand persons", "monthly"),
    "TW_UNEMPLOYED": ("Taiwan unemployed persons", "thousand persons", "monthly"),
}
def _bounded_budget(name: str, default: int, ceiling: int) -> int:
    try: requested = int(os.getenv(name, str(default)))
    except ValueError: requested = default
    return max(1, min(requested, ceiling))


BLS_DAILY_BUDGET = _bounded_budget("MACRO_BLS_DAILY_BUDGET", 40, 40)
FRED_DAILY_BUDGET = _bounded_budget("MACRO_FRED_DAILY_BUDGET", 100, 100)


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


_macro_local_cache = LocalTTLCache()
LOCAL_MACRO_TTL_SECONDS = 12 * 3600
FREE_HTTP_TTL_SECONDS = 4 * 3600
FREE_CACHE_CODES = set(CBC_SERIES) | set(TAIWAN_SERIES) | set(TPEX_SERIES) | set(DGBAS_SERIES) | set(DGBAS_COMMODITY_SERIES)


def _request(url: str, body: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    # Keep urllib's standard User-Agent and Accept headers. FRED stalls when it
    # receives the custom macro client headers, while its default headers return
    # the same payload immediately. BLS JSON POSTs still need an explicit type.
    headers = {"Content-Type": "application/json"} if data else {}
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        # Never persist URLs or response bodies from authenticated FRED requests.
        raise RuntimeError(f"upstream_http_{exc.code}") from None
    except Exception as exc:
        raise RuntimeError(type(exc).__name__) from None


def _request_free_cached(cache_key: str, url: str, ttl_seconds: int = FREE_HTTP_TTL_SECONDS) -> tuple[int, bytes]:
    """Cache public-source HTTP responses per Python process to avoid repeat calls."""
    key = f"http:{cache_key}"
    cached = _macro_local_cache.get(key)
    if cached is not None:
        return cached
    response = _request(url)
    _macro_local_cache.set(key, response, ttl_seconds)
    return response


def _record_run(source: str, status: str, count: int = 0, detail: str = "", http_status: int | None = None) -> None:
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
        """Keep free source observations in bounded process memory; never write them to PostgreSQL."""
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            grouped.setdefault(row["code"], []).append({"period": row["period"], "value": str(row["value"])})
        fetched_at = datetime.now(UTC).isoformat()
        for code, series_rows in grouped.items():
            series_rows.sort(key=lambda item: item["period"])
            _macro_local_cache.set(f"series:{code}", {
                "code": code, "name": definitions[code][0], "unit": definitions[code][1],
                "frequency": definitions[code][2], "source": source, "sourceUrl": source_url,
                "fetchedAt": fetched_at, "freshForSeconds": fresh_for_seconds, "history": series_rows,
            }, 30 * 24 * 3600)
        self._cache = None
        return sum(len(items) for items in grouped.values())

    async def start(self):
        if not MACRO_ENABLED:
            logger.info("Macro data collection disabled by MACRO_ENABLED")
            return
        if self._task and not self._task.done():
            return
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
            # Four BLS batches and up to twenty-eight keyed FRED calls per day stay
            # comfortably inside the site's conservative daily budgets.
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
                ("TPExGold", self._fetch_tpex_gold), ("DGBAS", self._fetch_dgbas_employment),
                ("WorldBank", self._fetch_world_bank_gold)):
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
            newest = {code: max((row["period"] for row in rows if row["code"] == code), default=None)
                for code in ("CES0000000001", "CUSR0000SA0")}
            with market_macro_db.sessions.begin() as session:
                for code, (name, unit, frequency) in BLS_SERIES.items():
                    session.merge(MacroSeries(code=code, name=name, unit=unit, frequency=frequency, source="BLS"))
            saved = market_macro_db.save_observations("BLS", rows)
            if previous_employment and newest["CES0000000001"] and newest["CES0000000001"] > previous_employment:
                market_macro_db.record_observed_release("employment", newest["CES0000000001"], "https://www.bls.gov/news.release/empsit.htm")
            if previous_cpi and newest["CUSR0000SA0"] and newest["CUSR0000SA0"] > previous_cpi:
                market_macro_db.record_observed_release("cpi", newest["CUSR0000SA0"], "https://www.bls.gov/news.release/cpi.htm")
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
            run_id = market_macro_db.reserve_source_call("FRED", daily_limit=FRED_DAILY_BUDGET, minute_limit=10)
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
                    source_id = f"{release_id}:{scheduled:%Y-%m}"
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
        with market_macro_db.sessions.begin() as session:
            for code, (name, unit, frequency) in FRED_SERIES.items():
                session.merge(MacroSeries(code=code, name=name, unit=unit, frequency=frequency, source="FRED"))
        failures = 0
        for code in FRED_SERIES:
            run_id = market_macro_db.reserve_source_call("FRED", daily_limit=FRED_DAILY_BUDGET, minute_limit=10)
            if run_id is None: raise RuntimeError("fred_daily_or_minute_budget_exhausted")
            params = urllib.parse.urlencode({"series_id": code, "file_type": "json",
                "observation_start": (date.today() - timedelta(days=730)).isoformat() if FRED_SERIES[code][2] == "daily"
                    else f"{date.today().year - 6}-01-01",
                "sort_order": "asc", "limit": "1000", "api_key": FRED_KEY})
            if FRED_SERIES[code][2] == "monthly":
                params += "&" + urllib.parse.urlencode({"frequency": "m", "aggregation_method": "eop"})
            try:
                status, raw = _request(f"https://api.stlouisfed.org/fred/series/observations?{params}")
                payload = json.loads(raw)
                observations = payload.get("observations")
                if not isinstance(observations, list): raise RuntimeError("fred_observation_response_invalid")
                rows = []
                for item in observations:
                    if not item.get("value") or item["value"] == ".": continue
                    try:
                        observation_date = date.fromisoformat(item["date"])
                        period = observation_date.isoformat() if FRED_SERIES[code][2] == "daily" else observation_date.isoformat()[:7]
                    except (KeyError, ValueError, TypeError): continue
                    rows.append({"code": code, "period": period, "value": item["value"]})
                saved = market_macro_db.save_observations("FRED", rows); count += saved
                market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            except Exception as exc:
                market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
                failures += 1
                logger.warning("FRED observation refresh failed for %s: %s", code, str(exc)[:60])
        if failures == len(FRED_SERIES):
            raise RuntimeError("fred_observations_all_failed")
        return count

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
                    if index >= len(periods) or not values or values[0] in (None, ""):
                        continue
                    period = str(periods[index].get("id", ""))
                    match = re.fullmatch(r"(\d{4})-M(\d{1,2})", period)
                    if match:
                        rows.append({"code": code, "period": f"{match.group(1)}-{int(match.group(2)):02d}", "value": values[0]})
            saved = self._cache_free_series(rows, DGBAS_SERIES, "DGBAS", "https://nstatdb.dgbas.gov.tw/dgbasAll/")
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=saved_http_status)
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
        """Low-frequency free calendar supplement; consensus and actual may be unavailable per event."""
        run_id = market_macro_db.reserve_source_call("FinanceCalendar", daily_limit=4, minute_limit=2)
        if run_id is None:
            raise RuntimeError("consensus_calendar_budget_exhausted")
        try:
            today = date.today()
            query = urllib.parse.urlencode({"from": today.isoformat(), "to": (today + timedelta(days=90)).isoformat(), "limit": "500"})
            status, raw = _request(f"https://www.financecalendar.com/wp-json/fc/v1/calendar?{query}")
            payload = json.loads(raw)
            if not isinstance(payload.get("events"), list):
                raise RuntimeError("consensus_calendar_response_invalid")
            events = []
            for item in payload["events"]:
                title = str(item.get("title") or item.get("name") or "")
                lowered = title.lower()
                group = None
                if "fomc" in lowered and ("decision" in lowered or "rate" in lowered):
                    group = "fed"
                elif "cpi" in lowered and ("us " in lowered or "united states" in lowered):
                    group = "cpi"
                elif "retail sales" in lowered or "retail trade" in lowered:
                    group = "retail_sales"
                elif any(term in lowered for term in ("nonfarm payroll", "employment situation", "us jobs report")):
                    group = "employment"
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
                consensus = item.get("consensus")
                actual = item.get("actual")
                events.append({"id": f"financecalendar:{group}:{scheduled.isoformat()}",
                    "sourceId": f"{group}:{scheduled.isoformat()}", "groupId": group,
                    "type": group, "title": title, "scheduledDate": scheduled,
                    "scheduledAt": scheduled_at, "timePrecision": "minute" if scheduled_at else "date",
                    "scheduleVerification": "confirmed" if scheduled_at else "date_only",
                    "consensusValue": str(consensus) if consensus not in (None, "") else None,
                    "actualValue": str(actual) if actual not in (None, "") else None,
                    "expectationSource": "Finance Calendar", "sourceUrl": source_url})
            saved = market_macro_db.update_event_expectations(events)
            market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            return saved
        except Exception as exc:
            market_macro_db.finish_source_call(run_id, "error", detail=str(exc))
            raise

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
                "history": history[-max(history_months * 32 if series["frequency"] == "daily" else history_months, 24):],
            })
        result["indicators"] = [item for item in result.get("indicators", []) if item.get("code") not in FREE_CACHE_CODES] + local_indicators
        if local_indicators:
            result["status"] = "ready"
        known_sources = {item.get("source") for item in result.get("sources", [])}
        for source in {item["source"] for item in local_indicators} - known_sources:
            result.setdefault("sources", []).append({"source": source, "availability": "success", "stale": False,
                "lastSuccessAt": next(item["fetchedAt"] for item in local_indicators if item["source"] == source)})
        result["asOf"] = datetime.now(UTC).isoformat()
        return result


market_macro_service = MarketMacroService()
