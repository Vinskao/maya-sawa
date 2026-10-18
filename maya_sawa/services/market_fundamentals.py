"""Official TWSE current fundamentals plus quota-limited persisted FinMind history."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import csv
import io
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..databases.market_dashboard_db import market_dashboard_db
from ..databases.market_fundamentals_db import market_fundamentals_db

logger = logging.getLogger(__name__)
TZ = ZoneInfo("Asia/Taipei")
TWSE = "https://openapi.twse.com.tw/v1/opendata"
TPEx_OTC_MONTHLY = "https://mopsfin.twse.com.tw/opendata/t187ap05_O.csv"


def _get_json(url: str) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "TY-Multiverse-MarketDashboard/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def _publication_date(value: Any) -> str | None:
    """Normalize Gregorian or Republic of China calendar dates to YYYY-MM-DD."""
    raw = str(value or "").strip()
    match = re.search(r"(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})", raw)
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if year < 1911:
        year += 1911
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


class MarketFundamentalsService:
    # Official TWSE feeds cover every listed company in one document; keep the last good copy and refresh it in the
    # background so a request never waits on TWSE once the cache is warm.
    OFFICIAL_FEEDS = {
        "monthly:listed": f"{TWSE}/t187ap05_L",
        "income": f"{TWSE}/t187ap06_L_ci",
        "balance": f"{TWSE}/t187ap07_L_ci",
        "monthly:otc": TPEx_OTC_MONTHLY,
    }
    FINMIND_DATASETS = ("TaiwanStockMonthRevenue", "TaiwanStockFinancialStatements",
                        "TaiwanStockBalanceSheet", "TaiwanStockCashFlowsStatement")

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self._refreshing: dict[str, asyncio.Task] = {}
        self._stale_sources: set[str] = set()
        self._collector_task: asyncio.Task | None = None
        self._worker_task: asyncio.Task | None = None
        self._queue: list[str] = []
        self._queue_event = asyncio.Event()

    async def start(self) -> None:
        if self._collector_task is None or self._collector_task.done():
            self._collector_task = asyncio.create_task(self._collector_loop())
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._finmind_worker())

    async def close(self) -> None:
        for task in (self._collector_task, self._worker_task, *self._refreshing.values()):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._collector_task = self._worker_task = None
        self._refreshing.clear()

    async def _collector_loop(self) -> None:
        while True:
            try:
                for key in self.OFFICIAL_FEEDS:
                    try:
                        await self._official(key)
                    except Exception as exc:
                        logger.warning("Official fundamentals warm-up failed for %s: %s", key, exc)
                for code in await asyncio.to_thread(self._watch_symbols):
                    self._enqueue(code)
                await asyncio.sleep(60 * 60)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Fundamentals collector loop failed")
                await asyncio.sleep(60 * 60)

    def _enqueue(self, code: str, urgent: bool = False) -> None:
        if code in self._queue:
            if not urgent:
                return
            self._queue.remove(code)
        if urgent:
            self._queue.insert(0, code)
        else:
            self._queue.append(code)
        self._queue_event.set()

    async def _finmind_worker(self) -> None:
        while True:
            try:
                while not self._queue:
                    self._queue_event.clear()
                    await self._queue_event.wait()
                code = self._queue.pop(0)
                await asyncio.to_thread(self._collect_code, code)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("FinMind fundamentals worker failed")
                await asyncio.sleep(60)

    async def _official(self, key: str, ttl: int = 900) -> Any:
        url = self.OFFICIAL_FEEDS[key]
        cached = self._cache.get(key)
        if cached:
            if time.monotonic() - cached[0] >= ttl and key not in self._refreshing:
                task = asyncio.create_task(self._refresh_official(key, url))
                self._refreshing[key] = task
                task.add_done_callback(lambda _t, k=key: self._refreshing.pop(k, None))
            return cached[1]
        async with self._lock:
            cached = self._cache.get(key)
            if cached:
                return cached[1]
            return await self._refresh_official(key, url)

    async def _refresh_official(self, key: str, url: str) -> Any:
        try:
            if url.endswith(".csv"):
                request = urllib.request.Request(url, headers={"User-Agent": "TY-Multiverse-MarketDashboard/1.0"})
                with await asyncio.to_thread(urllib.request.urlopen, request, timeout=25) as response:
                    result = response.read().decode("utf-8-sig")
            else:
                result = await asyncio.to_thread(_get_json, url)
            if not isinstance(result, (list, str)):
                raise ValueError("Official fundamentals endpoint returned an unexpected document")
            self._cache[key] = (time.monotonic(), result)
            self._stale_sources.discard(key)
            return result
        except Exception:
            if key in self._cache:
                self._stale_sources.add(key)
                logger.warning("Official fundamentals refresh failed; serving cached copy: %s", key)
                return self._cache[key][1]
            raise

    async def get(self, code: str) -> dict[str, Any]:
        code = code.strip().upper()
        if not code.isdigit() or len(code) != 4:
            raise ValueError("Fundamentals require a four-digit Taiwan stock code")
        statements = await asyncio.gather(
            self._official("monthly:listed"), self._official("income"), self._official("balance"),
            return_exceptions=True,
        )
        monthly_raw, income_raw, balance_raw = statements
        errors = [str(item) for item in statements if isinstance(item, Exception)]
        monthly = self._monthly_rows(monthly_raw, code) if not isinstance(monthly_raw, Exception) else []
        if not monthly:
            try:
                monthly = self._monthly_rows(await self._official("monthly:otc"), code)
            except Exception as exc:
                errors.append(f"OTC monthly revenue: {exc}")
        income = self._statement_rows(income_raw, code, "income") if not isinstance(income_raw, Exception) else []
        balance = self._statement_rows(balance_raw, code, "balance") if not isinstance(balance_raw, Exception) else []
        history = await asyncio.to_thread(self._finmind_history, code)
        # Any stock someone opens joins the refresh queue; the 24h per-dataset checkpoint stops repeat downloads.
        self._enqueue(code, urgent=True)
        return {"code": code, "monthlyRevenue": monthly, "incomeStatements": income, "balanceSheets": balance,
                "metrics": build_fundamental_metrics(monthly, income, history),
                "historyPending": not history.get("TaiwanStockFinancialStatements"),
                "source": "TWSE OpenAPI / MOPS OTC CSV / FinMind", "checkedAt": datetime.now(TZ).isoformat(),
                "staleSources": sorted(self._stale_sources), "errors": errors}

    def cached_official(self, code: str) -> tuple[list[dict], list[dict]]:
        """Official monthly/income rows for one stock from the in-memory feeds only; never blocks on TWSE."""
        def cached(key: str) -> Any:
            entry = self._cache.get(key)
            return entry[1] if entry else None
        monthly = self._monthly_rows(cached("monthly:listed"), code) if cached("monthly:listed") else []
        if not monthly and cached("monthly:otc"):
            monthly = self._monthly_rows(cached("monthly:otc"), code)
        income = self._statement_rows(cached("income"), code, "income") if cached("income") else []
        return monthly, income

    async def published_events(self, codes: list[str]) -> list[dict[str, Any]]:
        """Return actual monthly-revenue and quarterly-statement publication dates from official feeds."""
        wanted = {str(code).strip() for code in codes if str(code).strip().isdigit() and len(str(code).strip()) == 4}
        if not wanted:
            return []
        monthly_raw, income_raw = await asyncio.gather(
            self._official("monthly:listed"), self._official("income"), return_exceptions=True,
        )
        monthly_feed = monthly_raw if not isinstance(monthly_raw, Exception) else []
        income_feed = income_raw if not isinstance(income_raw, Exception) else []
        listed_codes = {str(row.get("公司代號", "")).strip() for row in monthly_feed if isinstance(row, dict)}
        otc_monthly: dict[str, list[dict]] = {}
        otc_codes = wanted - listed_codes
        if otc_codes:
            try:
                otc_feed = await self._official("monthly:otc")
                otc_monthly = {code: self._monthly_rows(otc_feed, code) for code in otc_codes}
            except Exception as exc:
                logger.info("OTC monthly publication dates unavailable: %s", exc)
        events: list[dict[str, Any]] = []
        for code in wanted:
            monthly_rows = (self._monthly_rows(monthly_feed, code) if code in listed_codes
                            else otc_monthly.get(code, []))
            for row in monthly_rows:
                if row.get("publishedAt"):
                    events.append({"code": code, "name": row.get("name") or code,
                                   "type": "monthly_revenue", "period": row["period"],
                                   "date": _publication_date(row["publishedAt"]),
                                   "source": "TWSE OpenAPI / MOPS OTC"})
            for row in self._statement_rows(income_feed, code, "income"):
                if row.get("publishedAt"):
                    events.append({"code": code, "name": row.get("raw", {}).get("公司名稱") or code,
                                   "type": "financial_report", "period": row["period"],
                                   "date": _publication_date(row["publishedAt"]),
                                   "source": "TWSE OpenAPI"})
        # A quarter's income statement is the release signal; avoid duplicating its balance-sheet row.
        return events

    def request_history(self, codes: list[str]) -> None:
        for code in codes:
            self._enqueue(code, urgent=True)

    @staticmethod
    def _finmind_history(code: str) -> dict[str, list[dict]]:
        result = {}
        for dataset in MarketFundamentalsService.FINMIND_DATASETS:
            rows = market_fundamentals_db.rows(code, dataset)
            for item in rows:
                try:
                    item["value"] = json.loads(item["value"])
                except (TypeError, json.JSONDecodeError):
                    pass
            result[dataset] = rows
        return result

    @staticmethod
    def _monthly_rows(payload: Any, code: str) -> list[dict]:
        if isinstance(payload, str):
            import csv, io
            rows = list(csv.DictReader(io.StringIO(payload)))
        else:
            rows = payload if isinstance(payload, list) else []
        result = []
        for row in rows:
            if str(row.get("公司代號") or row.get("公司代碼") or row.get("公司代號 ") or "").strip() != code:
                continue
            month = _normalize_month(row.get("資料年月") or row.get("營業年月") or row.get("年月") or "")
            result.append({"period": str(month), "publishedAt": row.get("出表日期") or row.get("公告日期"),
                           "name": row.get("公司名稱") or row.get("公司簡稱") or "",
                           "industry": row.get("產業別") or "", "unit": "新台幣千元",
                           "revenue": _first_number(row, ("營業收入-當月營收", "當月營收", "營業收入(千元)")),
                           "previousRevenue": _first_number(row, ("營業收入-上月營收", "上月營收")),
                           "yearAgoRevenue": _first_number(row, ("營業收入-去年當月營收", "去年同月營收")),
                           "momPercent": _first_number(row, ("營業收入-上月比較增減(%)", "上月比較增減(%)")),
                           "yoyPercent": _first_number(row, ("營業收入-去年同月增減(%)", "去年同月增減(%)")),
                           "ytdRevenue": _first_number(row, ("累計營業收入-當月累計營收", "當月累計營收")),
                           "source": "TWSE / MOPS"})
        return sorted(result, key=lambda item: item["period"])[-36:]

    @staticmethod
    def _statement_rows(payload: Any, code: str, statement: str) -> list[dict]:
        matching = []
        for row in payload if isinstance(payload, list) else []:
            if str(row.get("公司代號", "")).strip() != code:
                continue
            year, quarter = str(row.get("年度", "")), str(row.get("季別", ""))
            if not year or not quarter:
                continue
            gregorian_year = str(1911 + int(year)) if year.isdigit() and len(year) <= 3 else year
            matching.append((year, quarter, row, gregorian_year))
        by_period = {(year, quarter): row for year, quarter, row, _ in matching}
        result = []
        for year, quarter, row, gregorian_year in matching:
            amount_fields = ({
                "revenue": "營業收入", "grossProfit": "營業毛利（毛損）淨額",
                "operatingIncome": "營業利益（損失）", "netIncome": "本期淨利（淨損）",
            } if statement == "income" else {
                "assets": "資產總計", "liabilities": "負債總計", "equity": "權益總計",
                "bookValuePerShare": "每股參考淨值",
            })
            reported = {key: _first_number(row, (field,)) for key, field in amount_fields.items()}
            previous = by_period.get((year, str(int(quarter) - 1))) if int(quarter) > 1 else None
            single = {}
            for key, current_value in reported.items():
                prior_value = _first_number(previous, (amount_fields[key],)) if previous else None
                if current_value is None:
                    single[key] = None
                elif int(quarter) == 1:
                    single[key] = current_value
                else:
                    single[key] = current_value - prior_value if prior_value is not None else None
            eps = _first_number(row, ("基本每股盈餘（元）", "基本每股盈餘")) if statement == "income" else None
            result.append({"period": f"{gregorian_year}Q{quarter}", "publishedAt": row.get("出表日期"),
                           "scope": "consolidated", "statement": statement,
                           "unit": "新台幣千元；每股項目為元", "reportedCumulative": reported,
                           "singleQuarter": single if statement == "income" else None, "epsReported": eps,
                           "basis": ("TWSE quarterly income values are cumulative year-to-date; single-quarter amounts subtract the preceding reported quarter. EPS stays as reported because share-count basis can change." if statement == "income" else "Quarter-end balance sheet amounts; not cumulative."),
                           "source": "TWSE OpenAPI", "raw": row})
        return sorted(result, key=lambda item: item["period"])[-12:]

    @staticmethod
    def _watch_symbols() -> list[str]:
        if not market_fundamentals_db.sessions:
            return []
        try:
            from .market_selection import selected_stock_codes  # futures resolve to their underlying stock
            return selected_stock_codes()
        except Exception:
            logger.exception("Fundamentals watch-symbol lookup failed")
            return []

    def _collect_code(self, code: str) -> None:
        """Refresh one stock's FinMind history. Anonymous access works (lower quota); a token raises the limit."""
        if not market_fundamentals_db.sessions:
            return
        token = os.getenv("FINMIND_TOKEN", "").strip()
        headers = {"User-Agent": "TY-Multiverse-MarketDashboard/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        # Three years back so the oldest displayed month/quarter still has a year-ago comparison.
        start_date = (datetime.now(TZ).date() - timedelta(days=3 * 366)).isoformat()
        for dataset in self.FINMIND_DATASETS:
            reservation_id = market_fundamentals_db.claim_finmind_slot(dataset, code, min_gap_seconds=FINMIND_GAP_SECONDS)
            if reservation_id is None:
                continue  # refreshed within 24h, or the account-wide hourly budget is spent
            query = urllib.parse.urlencode({"dataset": dataset, "data_id": code, "start_date": start_date})
            request = urllib.request.Request(f"https://api.finmindtrade.com/api/v4/data?{query}", headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                if payload.get("status") != 200:
                    raise RuntimeError(f"FinMind status {payload.get('status')}")
                records = _finmind_records(dataset, payload.get("data") or [])
                market_fundamentals_db.replace_dataset(dataset, code, records, "https://api.finmindtrade.com/api/v4/data")
                market_fundamentals_db.record_periods_seen(dataset, code, [row["period"] for row in records])
                market_fundamentals_db.record_finmind_result(reservation_id, "success", f"rows={len(records)}")
            except urllib.error.HTTPError as exc:
                market_fundamentals_db.record_finmind_result(reservation_id, "error", f"HTTP {exc.code}")
                if exc.code in (402, 429):
                    logger.warning("FinMind quota or permission limit returned HTTP %s; pausing collection", exc.code)
                    time.sleep(15 * 60)
                    return
            except Exception as exc:
                market_fundamentals_db.record_finmind_result(reservation_id, "error", str(exc))
                logger.warning("FinMind collection failed for %s/%s: %s", code, dataset, exc)
            time.sleep(FINMIND_GAP_SECONDS + 1)


FINMIND_GAP_SECONDS = 12  # anonymous FinMind allows ~300 calls/hour


def _finmind_records(dataset: str, raw_rows: list[dict]) -> list[dict]:
    if dataset == "TaiwanStockMonthRevenue":
        # `date` is the publication month; revenue_year/revenue_month name the month the revenue belongs to.
        # create_time is the day the company published that month's revenue (kept as a non-numeric item).
        records = []
        for row in raw_rows:
            if not (row.get("revenue_year") and row.get("revenue_month")):
                continue
            period = f"{int(row['revenue_year']):04d}-{int(row['revenue_month']):02d}"
            records.append({"period": period, "item": "revenue", "value": row.get("revenue"), "unit": "新台幣元"})
            if row.get("create_time"):
                records.append({"period": period, "item": "publishedAt", "value": str(row["create_time"])[:10], "unit": ""})
        return records
    return [{"period": str(row.get("date", "")), "item": str(row.get("type", "")), "value": row.get("value"),
             "unit": str(row.get("unit", "新台幣元"))} for row in raw_rows if row.get("date") and row.get("type")]


def _quarter_label(date_text: str) -> str:
    if len(date_text) >= 7 and date_text[4] == "-":
        return f"{date_text[:4]}Q{(int(date_text[5:7]) - 1) // 3 + 1}"
    return date_text


def _shift_quarter(label: str, quarters: int) -> str:
    index = int(label[:4]) * 4 + int(label[5]) - 1 - quarters
    return f"{index // 4}Q{index % 4 + 1}"


def _shift_month(label: str, months: int) -> str:
    index = int(label[:4]) * 12 + int(label[5:7]) - 1 - months
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _pick(values: dict[str, float], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if values.get(key) is not None:
            return values[key]
    return None


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    return None if numerator is None or not denominator else round(numerator / denominator * 100, 2)


def _growth(current: float | None, previous: float | None) -> float | None:
    # Growth off a non-positive base has no meaningful sign, so leave it blank.
    return None if current is None or previous is None or previous <= 0 else round((current / previous - 1) * 100, 2)


def _diff(current: float | None, previous: float | None) -> float | None:
    return None if current is None or previous is None else round(current - previous, 2)


def _pivot(rows: list[dict], label=_quarter_label) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        value = _num(row.get("value"))
        if value is not None:
            result.setdefault(label(str(row.get("period", ""))), {})[str(row.get("item"))] = value
    return result


def build_fundamental_metrics(monthly_official: list[dict], income_official: list[dict],
                             history: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Growth rates and ratios only; absolute amounts never leave this function."""
    revenue = {period: values["revenue"] for period, values in
               _pivot(history.get("TaiwanStockMonthRevenue", []), label=str).items() if "revenue" in values}
    official_month = {row["period"]: row for row in monthly_official}
    for period, row in official_month.items():
        if row.get("revenue") is not None:
            revenue.setdefault(period, row["revenue"] * 1000)  # official feed is NT$ thousands
    published = {str(row.get("period")): str(row.get("value")) for row in history.get("TaiwanStockMonthRevenue", [])
                 if row.get("item") == "publishedAt" and row.get("value")}
    monthly = []
    for period in sorted(revenue)[-24:]:
        official = official_month.get(period, {})
        year, month = period[:4], int(period[5:7])
        ytd = [revenue.get(f"{year}-{m:02d}") for m in range(1, month + 1)]
        ytd_prior = [revenue.get(f"{int(year) - 1:04d}-{m:02d}") for m in range(1, month + 1)]
        monthly.append({
            "period": period,
            "yoyPercent": official["yoyPercent"] if official.get("yoyPercent") is not None else _growth(revenue[period], revenue.get(_shift_month(period, 12))),
            "momPercent": official["momPercent"] if official.get("momPercent") is not None else _growth(revenue[period], revenue.get(_shift_month(period, 1))),
            "ytdYoyPercent": _growth(sum(ytd), sum(ytd_prior)) if None not in ytd and None not in ytd_prior else None,
            "publishedAt": published.get(period),
        })

    income = _pivot(history.get("TaiwanStockFinancialStatements", []))
    for row in income_official:
        single = row.get("singleQuarter") or {}
        if row["period"] not in income and single.get("revenue") is not None:
            income[row["period"]] = {key: single[src] * 1000 for key, src in (
                ("Revenue", "revenue"), ("GrossProfit", "grossProfit"), ("OperatingIncome", "operatingIncome"),
                ("IncomeAfterTaxes", "netIncome")) if single.get(src) is not None}
            if row["period"].endswith("Q1") and row.get("epsReported") is not None:
                income[row["period"]]["EPS"] = row["epsReported"]

    def income_ratios(period: str) -> dict[str, float | None]:
        values = income.get(period, {})
        revenue_value = values.get("Revenue")
        return {"revenue": revenue_value, "eps": values.get("EPS"),
                "grossMargin": _ratio(values.get("GrossProfit"), revenue_value),
                "operatingMargin": _ratio(values.get("OperatingIncome"), revenue_value),
                "netMargin": _ratio(_pick(values, ("IncomeAfterTaxes", "IncomeFromContinuingOperations")), revenue_value)}

    quarterly = []
    for period in sorted(income)[-8:]:
        now, prev, year_ago = income_ratios(period), income_ratios(_shift_quarter(period, 1)), income_ratios(_shift_quarter(period, 4))
        entry: dict[str, Any] = {"period": period,
                                 "revenueQoQ": _growth(now["revenue"], prev["revenue"]),
                                 "revenueYoY": _growth(now["revenue"], year_ago["revenue"]),
                                 "epsQoQ": _growth(now["eps"], prev["eps"]),
                                 "epsYoY": _growth(now["eps"], year_ago["eps"])}
        for key in ("grossMargin", "operatingMargin", "netMargin"):
            entry[key] = now[key]
            entry[f"{key}QoQ"] = _diff(now[key], prev[key])
            entry[f"{key}YoY"] = _diff(now[key], year_ago[key])
        quarterly.append(entry)

    balance_values = _pivot(history.get("TaiwanStockBalanceSheet", []))

    def cost_of_goods(period: str) -> float | None:
        values = income.get(period, {})
        if values.get("CostOfGoodsSold") is not None:
            return values["CostOfGoodsSold"]
        revenue_value, gross = values.get("Revenue"), values.get("GrossProfit")
        return revenue_value - gross if revenue_value is not None and gross is not None else None

    def balance_ratios(period: str) -> dict[str, float | None]:
        values = balance_values.get(period, {})
        inventory, cogs = values.get("Inventories"), cost_of_goods(period)
        return {"debtRatio": _ratio(values.get("Liabilities"), values.get("TotalAssets")),
                "currentRatio": _ratio(values.get("CurrentAssets"), values.get("CurrentLiabilities")),
                "equity": _pick(values, ("Equity", "TotalEquity", "EquityAttributableToOwnersOfParent")),
                "inventory": inventory,
                # Days of inventory: quarter-end inventory / single-quarter cost of goods sold x 91.25 days.
                "inventoryDays": round(inventory / cogs * 91.25, 2) if inventory is not None and cogs and cogs > 0 else None}

    balance = []
    for period in sorted(balance_values)[-8:]:
        now, prev, year_ago = balance_ratios(period), balance_ratios(_shift_quarter(period, 1)), balance_ratios(_shift_quarter(period, 4))
        balance.append({"period": period,
                        "debtRatio": now["debtRatio"], "debtRatioQoQ": _diff(now["debtRatio"], prev["debtRatio"]),
                        "debtRatioYoY": _diff(now["debtRatio"], year_ago["debtRatio"]),
                        "currentRatio": now["currentRatio"], "currentRatioYoY": _diff(now["currentRatio"], year_ago["currentRatio"]),
                        "equityYoY": _growth(now["equity"], year_ago["equity"]),
                        "inventoryDays": now["inventoryDays"],
                        "inventoryDaysQoQ": _diff(now["inventoryDays"], prev["inventoryDays"]),
                        "inventoryDaysYoY": _diff(now["inventoryDays"], year_ago["inventoryDays"]),
                        "inventoryQoQ": _growth(now["inventory"], prev["inventory"]),
                        "inventoryYoY": _growth(now["inventory"], year_ago["inventory"]),
                        # Inventory growth minus revenue growth (pp): above 0 means stock builds faster than sales.
                        "inventoryVsRevenueYoY": _diff(_growth(now["inventory"], year_ago["inventory"]),
                            _growth(income_ratios(period)["revenue"], income_ratios(_shift_quarter(period, 4))["revenue"]))})

    # Cash flow statements are year-to-date, so only same-period-last-year comparisons are like for like.
    cash_values = _pivot(history.get("TaiwanStockCashFlowsStatement", []))

    def cash_ratios(period: str) -> dict[str, float | None]:
        values = cash_values.get(period, {})
        ocf = _pick(values, ("CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities"))
        capex = values.get("PropertyAndPlantAndEquipment")
        return {"ocf": ocf,
                "cashConversion": _ratio(ocf, _pick(values, ("NetIncomeBeforeTax", "IncomeBeforeIncomeTaxFromContinuingOperations"))),
                "capexToOcf": _ratio(-capex if capex is not None else None, ocf) if ocf and ocf > 0 else None}

    cash_flow = []
    for period in sorted(cash_values)[-8:]:
        now, year_ago = cash_ratios(period), cash_ratios(_shift_quarter(period, 4))
        cash_flow.append({"period": period, "ocfYoY": _growth(now["ocf"], year_ago["ocf"]),
                          "cashConversion": now["cashConversion"], "cashConversionYoY": _diff(now["cashConversion"], year_ago["cashConversion"]),
                          "capexToOcf": now["capexToOcf"], "capexToOcfYoY": _diff(now["capexToOcf"], year_ago["capexToOcf"])})
    return {"monthly": monthly, "quarterly": quarterly, "balance": balance, "cashFlow": cash_flow}


def _first_number(row: dict, keys: tuple[str, ...]):
    for key in keys:
        value = row.get(key)
        if value is None or str(value).strip() in {"", "-", "--"}:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def _normalize_month(value: Any) -> str:
    text = str(value).strip().replace("/", "").replace("-", "")
    if text.isdigit() and len(text) == 5:
        return f"{1911 + int(text[:3]):04d}-{text[3:]}"
    if text.isdigit() and len(text) == 6:
        return f"{text[:4]}-{text[4:]}"
    return text


market_fundamentals_service = MarketFundamentalsService()
