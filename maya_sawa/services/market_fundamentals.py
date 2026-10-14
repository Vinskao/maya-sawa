"""Official TWSE current fundamentals plus quota-limited persisted FinMind history."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import csv
import io
from datetime import datetime, timezone
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


class MarketFundamentalsService:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()
        self._stale_sources: set[str] = set()
        self._finmind_task: asyncio.Task | None = None
        self._collector_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._collector_task is None or self._collector_task.done():
            self._collector_task = asyncio.create_task(self._collector_loop())

    async def close(self) -> None:
        if self._collector_task:
            self._collector_task.cancel()
            try:
                await self._collector_task
            except asyncio.CancelledError:
                pass
            self._collector_task = None

    async def _collector_loop(self) -> None:
        while True:
            try:
                await asyncio.to_thread(self._collect_low_frequency)
                await asyncio.sleep(24 * 60 * 60)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("FinMind background fundamentals collection failed")
                await asyncio.sleep(60 * 60)

    async def _official(self, key: str, url: str, ttl: int = 900) -> Any:
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] < ttl:
            return cached[1]
        async with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < ttl:
                return cached[1]
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
                if cached:
                    self._stale_sources.add(key)
                    logger.warning("Serving stale in-process official fundamentals cache: %s", key)
                    return cached[1]
                raise

    async def get(self, code: str) -> dict[str, Any]:
        code = code.strip().upper()
        if not code.isdigit() or len(code) != 4:
            raise ValueError("Fundamentals require a four-digit Taiwan stock code")
        monthly_url = f"{TWSE}/t187ap05_L"
        statements = await asyncio.gather(
            self._official("monthly:listed", monthly_url),
            self._official("income", f"{TWSE}/t187ap06_L_ci"),
            self._official("balance", f"{TWSE}/t187ap07_L_ci"),
            return_exceptions=True,
        )
        monthly_raw, income_raw, balance_raw = statements
        errors = [str(item) for item in statements if isinstance(item, Exception)]
        monthly = self._monthly_rows(monthly_raw, code) if not isinstance(monthly_raw, Exception) else []
        if not monthly:
            try:
                otc_text = await self._official("monthly:otc", TPEx_OTC_MONTHLY)
                monthly = self._monthly_rows(otc_text, code)
            except Exception as exc:
                errors.append(f"OTC monthly revenue: {exc}")
        income = self._statement_rows(income_raw, code, "income") if not isinstance(income_raw, Exception) else []
        balance = self._statement_rows(balance_raw, code, "balance") if not isinstance(balance_raw, Exception) else []
        finmind = await asyncio.to_thread(market_fundamentals_db.rows, code, "TaiwanStockCashFlowsStatement")
        for item in finmind:
            try:
                item["value"] = json.loads(item["value"])
            except (TypeError, json.JSONDecodeError):
                pass
        finmind_income = await asyncio.to_thread(market_fundamentals_db.rows, code, "TaiwanStockFinancialStatements")
        finmind_balance = await asyncio.to_thread(market_fundamentals_db.rows, code, "TaiwanStockBalanceSheet")
        for item in finmind_income + finmind_balance:
            try:
                item["value"] = json.loads(item["value"])
            except (TypeError, json.JSONDecodeError):
                pass
        return {"code": code, "monthlyRevenue": monthly, "incomeStatements": income,
                "balanceSheets": balance, "cashFlows": finmind,
                "finmindIncomeStatements": finmind_income, "finmindBalanceSheets": finmind_balance,
                "source": "TWSE OpenAPI / MOPS OTC CSV", "checkedAt": datetime.now(TZ).isoformat(),
                "staleSources": sorted(self._stale_sources),
                "errors": errors}

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
                           "unit": "新台幣元；每股項目為元", "reportedCumulative": reported,
                           "singleQuarter": single if statement == "income" else None, "epsReported": eps,
                           "basis": ("TWSE quarterly income values are cumulative year-to-date; single-quarter amounts subtract the preceding reported quarter. EPS stays as reported because share-count basis can change." if statement == "income" else "Quarter-end balance sheet amounts; not cumulative."),
                           "source": "TWSE OpenAPI", "raw": row})
        return sorted(result, key=lambda item: item["period"])[-12:]

    def _collect_low_frequency(self) -> None:
        token = os.getenv("FINMIND_TOKEN", "").strip()
        if not token or not market_fundamentals_db.sessions:
            return
        symbols = set()
        try:
            for item in market_dashboard_db.latest_auto().get("positions", []) + market_dashboard_db.custom_symbols():
                code = str(item.get("underlyingCode") or item.get("code") or "").upper()
                if code.isdigit() and len(code) == 4:
                    symbols.add(code)
            for code in sorted(symbols):
                for dataset in ("TaiwanStockCashFlowsStatement", "TaiwanStockFinancialStatements", "TaiwanStockBalanceSheet"):
                    if market_fundamentals_db.rows(code, dataset):
                        continue
                    reservation_id = market_fundamentals_db.claim_finmind_slot(dataset, code)
                    if reservation_id is None:
                        logger.info("FinMind collection paused at the reserved hourly quota or daily checkpoint")
                        return
                    query = urllib.parse.urlencode({"dataset": dataset, "data_id": code, "start_date": "2024-01-01"})
                    request = urllib.request.Request(f"https://api.finmindtrade.com/api/v4/data?{query}", headers={"Authorization": f"Bearer {token}", "User-Agent": "TY-Multiverse-MarketDashboard/1.0"})
                    try:
                        with urllib.request.urlopen(request, timeout=30) as response:
                            payload = json.loads(response.read().decode("utf-8"))
                        if payload.get("status") != 200:
                            raise RuntimeError(f"FinMind status {payload.get('status')}")
                        raw_rows = payload.get("data") or []
                        records = [{"period": str(row.get("date", "")), "item": str(row.get("type", "")), "value": row.get("value"), "unit": str(row.get("unit", "來源項目單位未提供"))} for row in raw_rows if row.get("date") and row.get("type")]
                        market_fundamentals_db.replace_dataset(dataset, code, records, "https://api.finmindtrade.com/api/v4/data")
                        market_fundamentals_db.record_finmind_result(reservation_id, "success", f"rows={len(records)}")
                    except urllib.error.HTTPError as exc:
                        market_fundamentals_db.record_finmind_result(reservation_id, "error", f"HTTP {exc.code}")
                        if exc.code in (402, 429):
                            logger.warning("FinMind quota or permission limit returned HTTP %s", exc.code)
                            return
                    except Exception as exc:
                        market_fundamentals_db.record_finmind_result(reservation_id, "error", str(exc))
                        logger.warning("FinMind low-frequency collection failed for %s/%s: %s", code, dataset, exc)
                    time.sleep(30)
        except Exception:
            logger.exception("FinMind low-frequency collector failed")


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
