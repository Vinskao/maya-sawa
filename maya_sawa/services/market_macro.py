"""Low-frequency, persisted US macro data from registered BLS/FRED APIs and the Fed calendar."""
from __future__ import annotations

import asyncio
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
from datetime import date, datetime, timedelta, timezone
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
FRED_RELEASES = {"50": ("employment", "Nonfarm payrolls / Employment Situation"), "10": ("cpi", "CPI / Consumer Price Index")}
FRED_SERIES = {
    "DFEDTARL": ("Federal funds target range, lower limit", "percent", "daily"),
    "DFEDTARU": ("Federal funds target range, upper limit", "percent", "daily"),
}
def _bounded_budget(name: str, default: int, ceiling: int) -> int:
    try: requested = int(os.getenv(name, str(default)))
    except ValueError: requested = default
    return max(1, min(requested, ceiling))


BLS_DAILY_BUDGET = _bounded_budget("MACRO_BLS_DAILY_BUDGET", 40, 40)
FRED_DAILY_BUDGET = _bounded_budget("MACRO_FRED_DAILY_BUDGET", 100, 100)


def _request(url: str, body: dict | None = None) -> tuple[int, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers={
        "User-Agent": "TY-Multiverse-Macro/1.0", "Accept": "application/json,text/html",
        **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        # Never persist URLs or response bodies from authenticated FRED requests.
        raise RuntimeError(f"upstream_http_{exc.code}") from None
    except Exception as exc:
        raise RuntimeError(type(exc).__name__) from None


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

    async def start(self):
        if not MACRO_ENABLED:
            logger.info("Macro data collection disabled by MACRO_ENABLED")
            return
        if not BLS_KEY or not FRED_KEY:
            missing = [name for name, configured in (("BLS_API_KEY", BLS_KEY), ("FRED_API_KEY", FRED_KEY)) if not configured]
            for source in ("BLS", "FRED"):
                if (source == "BLS" and not BLS_KEY) or (source == "FRED" and not FRED_KEY):
                    _record_run(source, "blocked", detail="missing_key")
            logger.warning("Macro collection not started; missing runtime credentials: %s", ", ".join(missing))
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
            # Four BLS batches and up to sixteen FRED calls per rolling day stay
            # comfortably inside the site's conservative daily budgets.
            await asyncio.sleep(6 * 3600)

    async def refresh(self) -> dict:
        if not MACRO_ENABLED:
            return {"enabled": False, "reason": "disabled"}
        if not BLS_KEY or not FRED_KEY:
            return {"enabled": False, "reason": "missing_credentials"}
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
                try: output["sources"]["FRED"] = {"calendarEvents": self._fetch_fred_dates(), "rateObservations": self._fetch_fred_observations()}
                except Exception as exc:
                    logger.warning("FRED refresh failed: %s", str(exc)[:80]); _record_run("FRED", "error", detail=str(exc))
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
        for release_id, (group, title) in FRED_RELEASES.items():
            run_id = market_macro_db.reserve_source_call("FRED", daily_limit=FRED_DAILY_BUDGET, minute_limit=10)
            if run_id is None:
                raise RuntimeError("fred_daily_or_minute_budget_exhausted")
            params = urllib.parse.urlencode({"release_id": release_id, "file_type": "json", "include_release_dates_with_no_data": "true",
                "sort_order": "desc", "limit": "100", "offset": "0", "api_key": FRED_KEY})
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
                    # Release 50 and 10 are monthly; month identity remains stable if the day is revised.
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
                raise
        return count

    def _fetch_fred_observations(self) -> int:
        count = 0
        with market_macro_db.sessions.begin() as session:
            for code, (name, unit, frequency) in FRED_SERIES.items():
                session.merge(MacroSeries(code=code, name=name, unit=unit, frequency=frequency, source="FRED"))
        for code in FRED_SERIES:
            run_id = market_macro_db.reserve_source_call("FRED", daily_limit=FRED_DAILY_BUDGET, minute_limit=10)
            if run_id is None: raise RuntimeError("fred_daily_or_minute_budget_exhausted")
            params = urllib.parse.urlencode({"series_id": code, "file_type": "json",
                "observation_start": f"{date.today().year - 6}-01-01", "frequency": "m",
                "aggregation_method": "eop", "sort_order": "asc", "limit": "1000", "api_key": FRED_KEY})
            try:
                status, raw = _request(f"https://api.stlouisfed.org/fred/series/observations?{params}")
                payload = json.loads(raw)
                observations = payload.get("observations")
                if not isinstance(observations, list): raise RuntimeError("fred_observation_response_invalid")
                rows = []
                for item in observations:
                    if not item.get("value") or item["value"] == ".": continue
                    try: period = date.fromisoformat(item["date"]).isoformat()[:7]
                    except (KeyError, ValueError, TypeError): continue
                    rows.append({"code": code, "period": period, "value": item["value"]})
                saved = market_macro_db.save_observations("FRED", rows); count += saved
                market_macro_db.finish_source_call(run_id, "success", saved, http_status=status)
            except Exception as exc:
                market_macro_db.finish_source_call(run_id, "error", detail=str(exc)); raise
        return count

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
            return self._cache[1]
        result = await asyncio.to_thread(market_macro_db.snapshot, min(max(history_months, 12), 60))
        result["enabled"] = MACRO_ENABLED
        result["configuration"] = {"BLS": "configured" if BLS_KEY else "missing_key", "FRED": "configured" if FRED_KEY else "missing_key"}
        self._cache = (time.monotonic(), result)
        return result


market_macro_service = MarketMacroService()
