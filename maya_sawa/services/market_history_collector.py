"""Collect public daily exchange data for instruments on the market dashboard."""

from __future__ import annotations

import asyncio
import csv
import io
import calendar
import http.client
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from ..databases.market_dashboard_db import market_dashboard_db
from ..databases.market_history_db import market_history_db
from ..services.shioaji_market import shioaji_market_service

logger = logging.getLogger(__name__)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    raw = str(value).strip().replace(",", "").replace("+", "").replace("%", "")
    if not raw or raw in {"--", "－", "-", "N/A"}:
        return None
    raw = re.sub(r"<[^>]*>", "", raw).strip()
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def _dict_rows(payload: dict[str, Any], fields_alias: dict[str, str]) -> list[dict[str, Any]]:
    """Read a TWSE/TPEx {fields,data} table using its actual field names."""
    fields = payload.get("fields") or []
    result = []
    for values in payload.get("data") or []:
        row = dict(zip(fields, values))
        code = str(row.get("證券代號") or row.get("代號") or row.get("股票代號") or "").strip().upper()
        name = str(row.get("證券名稱") or row.get("名稱") or row.get("股票名稱") or code).strip()
        metrics = {target: _number(row.get(source)) for source, target in fields_alias.items()}
        result.append({"code": code, "name": name, "values": {key: value for key, value in metrics.items() if value is not None}})
    return result


def _download_taifex_csv(request: urllib.request.Request, *, required_fields: set[str],
                         timeout: float = 45, attempts: int = 3) -> str:
    """Download a TAIFEX CSV, retry transient throttling/timeouts, and reject alert HTML."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                document = response.read().decode("cp950", errors="replace")
            headers = set(next(csv.reader(io.StringIO(document)), []))
            if not required_fields.issubset(headers):
                raise ValueError("TAIFEX endpoint returned a non-CSV response")
            return document
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError,
                UnicodeError, ValueError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            time.sleep(min(2 ** attempt, 8))
    raise last_error or ValueError("TAIFEX CSV download failed")


def parse_twse_daily_price(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for table in payload.get("tables") or []:
        fields = table.get("fields") or []
        if not {"證券代號", "收盤價"}.issubset(fields):
            continue
        return _dict_rows(table, {
            "開盤價": "open", "最高價": "high", "最低價": "low", "收盤價": "close",
            "成交股數": "volume_shares", "成交金額": "turnover_twd", "成交筆數": "trades",
        })
    return []


def parse_twse_institutional(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _dict_rows(payload, {
        "外陸資買賣超股數(不含外資自營商)": "foreign_net_shares",
        "投信買賣超股數": "investment_trust_net_shares",
        "自營商買賣超股數": "dealer_net_shares",
        "三大法人買賣超股數": "all_institutions_net_shares",
    })


def parse_twse_foreign_holding(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _dict_rows(payload, {
        "全體外資及陸資持有股數": "foreign_holding_shares",
        "全體外資及陸資持股比率": "foreign_holding_percent",
        "外資及陸資共用法令投資上限比率": "foreign_limit_percent",
        "發行股數": "issued_shares",
    })


def parse_twse_margin(payload: dict[str, Any]) -> list[dict[str, Any]]:
    table = next((item for item in payload.get("tables") or []
                  if {"代號", "名稱", "今日餘額"}.issubset(item.get("fields") or [])), None)
    if not table:
        return []
    fields = table.get("fields") or []
    data = {"fields": fields, "data": table.get("data") or []}
    rows = _dict_rows(data, {})
    for parsed, raw in zip(rows, table.get("data") or []):
        parsed["values"] = {
            "margin_buy_lots": _number(raw[2]), "margin_sell_lots": _number(raw[3]),
            "margin_repayment_lots": _number(raw[4]), "margin_balance_lots": _number(raw[6]),
            "short_cover_lots": _number(raw[8]), "short_sell_lots": _number(raw[9]),
            "short_repayment_lots": _number(raw[10]), "short_balance_lots": _number(raw[12]),
        }
    return rows


def parse_twse_borrow_short(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """TWSE TWT93U publishes short-sale and borrowed-stock-sale balances in shares."""
    table = next((item for item in payload.get("tables") or []
                  if {"代號", "名稱", "今日餘額", "當日餘額"}.issubset(item.get("fields") or [])), None)
    # TWT93U returns its fields/data at the JSON root, unlike MI_MARGN's
    # nested tables. Accept the published shape so valid rows are not lost.
    if table is None and {"代號", "名稱", "今日餘額", "當日餘額"}.issubset(payload.get("fields") or []):
        table = payload
    if not table:
        return []
    fields = table.get("fields") or []
    rows = _dict_rows({"fields": fields, "data": table.get("data") or []}, {})
    for parsed, raw in zip(rows, table.get("data") or []):
        parsed["values"] = {
            "short_balance_shares": _number(raw[6]),
            "borrow_short_sell_shares": _number(raw[9]),
            "borrow_short_return_shares": _number(raw[10]),
            "borrow_short_adjustment_shares": _number(raw[11]),
            "borrow_short_balance_shares": _number(raw[12]),
        }
    return rows


def _tpex_table(payload: dict[str, Any]) -> tuple[list[str], list[list[Any]]]:
    table = next((item for item in payload.get("tables") or []
                  if isinstance(item, dict) and item.get("fields")), {})
    return table.get("fields") or [], table.get("data") or []


def _indexed_rows(payload: dict[str, Any], metrics: dict[int, str], *, code_index: int = 0,
                  name_index: int = 1) -> list[dict[str, Any]]:
    _, data = _tpex_table(payload)
    rows = []
    for raw in data:
        if len(raw) <= max([code_index, name_index, *metrics.keys()]):
            continue
        values = {name: _number(raw[index]) for index, name in metrics.items()}
        rows.append({"code": str(raw[code_index]).strip().upper(),
                     "name": str(raw[name_index]).strip(),
                     "values": {key: value for key, value in values.items() if value is not None}})
    return rows


def parse_tpex_daily_price(payload: dict[str, Any]) -> list[dict[str, Any]]:
    fields, _ = _tpex_table(payload)
    if not {"代號", "收盤", "成交股數"}.issubset(fields):
        return []
    indexes = {"開盤": "open", "最高": "high", "最低": "low", "收盤": "close",
               "成交股數": "volume_shares", "成交金額(元)": "turnover_twd", "成交筆數": "trades"}
    return _dict_rows({"fields": fields, "data": _tpex_table(payload)[1]}, indexes)


def parse_tpex_institutional(payload: dict[str, Any]) -> list[dict[str, Any]]:
    # The API repeats generic headings; the official schema order groups them by participant.
    return _indexed_rows(payload, {10: "foreign_net_shares", 13: "investment_trust_net_shares",
                                   22: "dealer_net_shares", 23: "all_institutions_net_shares"})


def parse_tpex_margin(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _indexed_rows(payload, {
        2: "margin_previous_balance_lots", 3: "margin_buy_lots", 4: "margin_sell_lots",
        5: "margin_repayment_lots", 6: "margin_balance_lots", 8: "margin_utilization_percent",
        9: "margin_quota_lots", 10: "short_previous_balance_lots", 11: "short_sell_lots",
        12: "short_cover_lots", 13: "short_repayment_lots", 14: "short_balance_lots",
        16: "short_utilization_percent", 17: "short_quota_lots",
    })


def parse_tpex_borrow_short(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return _indexed_rows(payload, {
        2: "short_previous_balance_shares", 3: "short_sell_shares", 4: "short_buy_shares",
        5: "short_spot_repayment_shares", 6: "short_balance_shares", 8: "borrow_short_previous_balance_shares",
        9: "borrow_short_sell_shares", 10: "borrow_short_return_shares",
        11: "borrow_short_adjustment_shares", 12: "borrow_short_balance_shares",
        13: "borrow_short_next_day_limit_shares",
    })


def parse_tpex_foreign_holding(payload: dict[str, Any]) -> list[dict[str, Any]]:
    table = next((item for item in payload.get("tables") or []
                  if {"代號", "名稱", "僑外資及陸資持有股數(C)"}.issubset(item.get("fields") or [])), None)
    if not table:
        return []
    return _dict_rows({"fields": table.get("fields") or [], "data": table.get("data") or []}, {
        "發行股數(A)": "issued_shares",
        "僑外資及陸資持有股數(C)": "foreign_holding_shares",
        "僑外資及陸資持股比率(E=C/A)": "foreign_holding_percent",
        "法令投資上限比率(F)": "foreign_limit_percent",
    })


def parse_taifex_futures_institutional_csv(document: str, trading_date: date) -> list[dict[str, Any]]:
    """Parse TAIFEX product-category futures institutional positions CSV."""
    reader = csv.DictReader(io.StringIO(document))
    required = {"日期", "身份別", "多方交易口數"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("TAIFEX institutional endpoint returned a non-CSV response")
    rows = []
    for raw in reader:
        if _normalize_date(raw.get("日期")) != trading_date:
            continue
        participant = str(raw.get("身份別") or "").strip()
        prefix = {"自營商": "dealer", "投信": "trust", "外資及陸資": "foreign"}.get(participant)
        if not prefix:
            continue
        metrics = {
            f"{prefix}_long_trade_contracts": _number(raw.get("多方交易口數")),
            f"{prefix}_long_trade_amount_thousands": _number(raw.get("多方交易契約金額(千元)")),
            f"{prefix}_short_trade_contracts": _number(raw.get("空方交易口數")),
            f"{prefix}_short_trade_amount_thousands": _number(raw.get("空方交易契約金額(千元)")),
            f"{prefix}_net_trade_contracts": _number(raw.get("多空交易口數淨額")),
            f"{prefix}_net_trade_amount_thousands": _number(raw.get("多空交易契約金額淨額(千元)")),
            f"{prefix}_long_open_interest": _number(raw.get("多方未平倉口數")),
            f"{prefix}_long_open_interest_amount_thousands": _number(raw.get("多方未平倉契約金額(千元)")),
            f"{prefix}_short_open_interest": _number(raw.get("空方未平倉口數")),
            f"{prefix}_short_open_interest_amount_thousands": _number(raw.get("空方未平倉契約金額(千元)")),
            f"{prefix}_net_open_interest": _number(raw.get("多空未平倉口數淨額")),
            f"{prefix}_net_open_interest_amount_thousands": _number(raw.get("多空未平倉契約金額淨額(千元)")),
        }
        rows.append({"code": "", "name": "", "values": {key: value for key, value in metrics.items() if value is not None}})
    if not rows:
        return []
    combined = {key: value for row in rows for key, value in row["values"].items()}
    return [{"code": "", "name": "", "values": combined}]


def parse_taifex_daily_futures_csv(document: str, selected_contracts: dict[str, dict[str, str]],
                                  trading_date: date) -> list[dict[str, Any]]:
    """Parse TAIFEX Big5 daily CSV, keeping regular-session rows only."""
    reader = csv.DictReader(io.StringIO(document))
    required = {"交易日期", "契約", "到期月份(週別)", "交易時段"}
    if not reader.fieldnames or not required.issubset(reader.fieldnames):
        raise ValueError("TAIFEX daily endpoint returned a non-CSV response")
    rows = []
    for raw in reader:
        raw_date = _normalize_date(raw.get("交易日期"))
        root = str(raw.get("契約") or "").strip().upper()
        month = str(raw.get("到期月份(週別)") or "").strip()
        session = str(raw.get("交易時段") or "").strip()
        if raw_date != trading_date or session != "一般":
            continue
        for code, identity in selected_contracts.items():
            if root != identity.get("root", "").upper() or month != identity.get("month", ""):
                continue
            metrics = {
                "open": _number(raw.get("開盤價")), "high": _number(raw.get("最高價")),
                "low": _number(raw.get("最低價")), "close": _number(raw.get("收盤價")),
                "change": _number(raw.get("漲跌價")), "volume_contracts": _number(raw.get("成交量")),
                "settlement": _number(raw.get("結算價")), "open_interest_contracts": _number(raw.get("未沖銷契約數")),
            }
            rows.append({"code": code.upper(), "name": identity.get("name") or code,
                         "values": {key: value for key, value in metrics.items() if value is not None}})
    return rows


def parse_tdcc_distribution(payload: list[dict[str, Any]], codes: list[str] | None = None) -> list[dict[str, Any]]:
    """Normalize the latest TDCC weekly distribution snapshot by security and tier."""
    allowed = {code.strip().upper() for code in codes or []}
    grouped: dict[str, dict[str, Any]] = {}
    for raw in payload:
        code = str(raw.get("證券代號") or "").strip().upper()
        if allowed and code not in allowed:
            continue
        date_value = raw.get("\ufeff資料日期") or raw.get("資料日期") or ""
        tier = _number(raw.get("持股分級"))
        if not code or tier is None:
            continue
        item = grouped.setdefault(code, {"code": code, "name": code, "values": {"tiers": []},
                                         "trading_date": _normalize_date(date_value)})
        item["values"]["tiers"].append({
            "tier": tier, "holders": _number(raw.get("人數")), "shares": _number(raw.get("股數")),
            "percent": _number(raw.get("占集保庫存數比例%")),
        })
    return list(grouped.values())


class _TdccDistributionHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_table = False
        self.table_depth = 0
        self.in_row = False
        self.in_cell = False
        self.current: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []
        self.texts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "div" and "securities-overview" in attrs_dict.get("class", ""):
            self.in_table = True
        elif self.in_table and tag == "div":
            self.table_depth += 1
        elif self.in_table and tag == "table":
            self.table_depth += 1
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.row = []
        elif self.in_row and tag in ("td", "th"):
            self.in_cell = True
            self.current = []

    def handle_data(self, data: str) -> None:
        clean = data.strip()
        if clean:
            self.texts.append(clean)
        if self.in_cell:
            self.current.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if self.in_cell and tag in ("td", "th"):
            self.row.append(" ".join(part for part in self.current if part))
            self.in_cell = False
        elif self.in_row and tag == "tr":
            if self.row:
                self.rows.append(self.row)
            self.in_row = False
        elif self.in_table and tag == "table":
            self.table_depth -= 1
        elif self.in_table and tag == "div":
            self.table_depth -= 1
            if self.table_depth == 0:
                self.in_table = False


def parse_tdcc_distribution_html(document: str, expected_code: str) -> dict[str, Any] | None:
    parser = _TdccDistributionHtml()
    parser.feed(document)
    text = " ".join(parser.texts)
    code_match = re.search(r"證券代號\s*：\s*([A-Z0-9]+)", text)
    name_match = re.search(r"證券名稱\s*：\s*([^\s]+)", text)
    date_match = re.search(r"資料日期\s*：\s*(\d{2,3})年(\d{1,2})月(\d{1,2})日", text)
    if not code_match or code_match.group(1).upper() != expected_code.upper() or not date_match:
        return None
    trading_date = date(1911 + int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3)))
    tiers = []
    for row in parser.rows:
        if len(row) < 5 or row[0] in {"序", ""}:
            continue
        tier = row[1].strip()
        if not tier or not re.match(r"\d", tier):
            continue
        tiers.append({"tier": tier, "holders": _number(row[2]), "shares": _number(row[3]),
                      "percent": _number(row[4])})
    if not tiers:
        return None
    return {"code": expected_code.upper(), "name": name_match.group(1) if name_match else expected_code,
            "trading_date": trading_date, "values": {"tiers": tiers}}


class MarketHistoryCollector:
    SOURCES = (
        "twse:daily-price", "twse:institutional", "twse:foreign-holding", "twse:margin-balance", "twse:borrow-short",
        "tpex:daily-price", "tpex:institutional", "tpex:foreign-holding", "tpex:margin-balance", "tpex:borrow-short",
        "tdcc:distribution-history",
    )
    SOURCE_CONFIG: dict[str, tuple[str, str, str]] = {
        "twse:daily-price": ("stock", "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={compact}&type=ALLBUT0999&response=json", "shares"),
        "twse:institutional": ("stock", "https://www.twse.com.tw/rwd/zh/fund/T86?date={compact}&selectType=ALLBUT0999&response=json", "shares"),
        "twse:foreign-holding": ("stock", "https://www.twse.com.tw/rwd/zh/fund/MI_QFIIS?date={compact}&selectType=ALLBUT0999&response=json", "shares_and_percent"),
        "twse:margin-balance": ("stock", "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={compact}&selectType=ALL&response=json", "trading_lots"),
        "twse:borrow-short": ("stock", "https://www.twse.com.tw/rwd/zh/marginTrading/TWT93U?date={compact}&response=json", "shares"),
        "tpex:daily-price": ("stock", "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={slash}&response=json", "shares"),
        "tpex:institutional": ("stock", "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?date={slash}&type=Daily&sect=EW&response=json", "shares"),
        "tpex:foreign-holding": ("stock", "https://www.tpex.org.tw/www/zh-tw/insti/qfii", "shares_and_percent"),
        "tpex:margin-balance": ("stock", "https://www.tpex.org.tw/www/zh-tw/margin/balance?date={slash}&response=json", "trading_lots"),
        "tpex:borrow-short": ("stock", "https://www.tpex.org.tw/www/zh-tw/margin/sbl?date={slash}&response=json", "shares"),
        "tdcc:distribution-history": ("stock", "https://www.tdcc.com.tw/portal/zh/smWeb/qryStock", "weekly_shares_holders_percent"),
    }

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._request_delay = float(os.getenv("MARKET_HISTORY_REQUEST_DELAY_SECONDS", "0.2"))
        self._backfill_days = max(1, min(int(os.getenv("MARKET_HISTORY_BACKFILL_DAYS", "92")), 366))
        self._futures_task: asyncio.Task[None] | None = None

    async def enqueue_codes(self, codes: list[str]) -> None:
        if codes:
            asyncio.create_task(self.collect_codes(codes, self._backfill_days))

    async def enqueue_futures(self, instruments: list[dict[str, str]]) -> None:
        if instruments:
            asyncio.create_task(asyncio.to_thread(self._collect_futures_codes_sync, instruments, self._backfill_days))

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._daily_loop())
        if self._futures_task is None or self._futures_task.done():
            self._futures_task = asyncio.create_task(self._daily_futures_loop())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._futures_task:
            self._futures_task.cancel()
            try:
                await self._futures_task
            except asyncio.CancelledError:
                pass
            self._futures_task = None

    async def collect_codes(self, codes: list[str], days: int | None = None) -> None:
        clean = sorted({str(code).strip().upper() for code in codes if str(code).strip()})
        if not clean:
            return
        async with self._lock:
            await asyncio.to_thread(self._collect_codes_sync, clean, days or self._backfill_days)

    async def _daily_loop(self) -> None:
        # Seed current selections at startup; subsequent passes keep the latest trading day current.
        while True:
            try:
                # Persisted quote snapshots map futures to their underlying stock even when Shioaji is down;
                # a live quote, when available, can add a contract the snapshots have not seen yet.
                from .market_selection import attach_underlying, current_selection, stock_code
                _, selections = await asyncio.to_thread(current_selection)
                futures = [item for item in selections if item.get("productType") == "futures" and not item.get("underlyingCode")]
                if futures:
                    try:
                        live = await shioaji_market_service.get_dashboard_quotes(futures)
                        await asyncio.to_thread(attach_underlying, futures, live)
                    except Exception as exc:
                        logger.info("Could not resolve futures underlying stocks for history: %s", exc)
                codes = {code for item in selections if (code := stock_code(item))}
                await self.collect_codes(sorted(code for code in codes if code), self._backfill_days)
                now = datetime.now(TAIPEI_TZ)
                next_run = now.replace(hour=18, minute=20, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                await asyncio.sleep(max(60, (next_run - now).total_seconds()))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Market history daily collection failed")
                await asyncio.sleep(900)

    async def _daily_futures_loop(self) -> None:
        while True:
            try:
                instruments = await asyncio.to_thread(market_dashboard_db.latest_futures_selections)
                quote_targets = [item for item in instruments if item.get("code", "").upper() != "TXF"]
                if quote_targets:
                    try:
                        quotes = await shioaji_market_service.get_dashboard_quotes(quote_targets)
                        delivery_months = {item["symbol"].upper(): item.get("deliveryMonth", "") for item in quotes}
                        instruments = [{**item,
                                        "deliveryMonth": item.get("deliveryMonth") or delivery_months.get(item["code"].upper(), "")}
                                       for item in instruments]
                    except Exception as exc:
                        logger.info("Could not resolve selected futures delivery months from Shioaji quotes: %s", exc)
                collected = await asyncio.to_thread(self._collect_futures_codes_sync, instruments, self._backfill_days)
                if not collected:
                    # TAIFEX may temporarily throttle a range request or an
                    # individual daily price request. Retry those uncovered
                    # dates in this process instead of sleeping until tomorrow.
                    await asyncio.sleep(300)
                    continue
                now = datetime.now(TAIPEI_TZ)
                next_run = now.replace(hour=18, minute=30, second=0, microsecond=0)
                if next_run <= now:
                    next_run += timedelta(days=1)
                await asyncio.sleep(max(60, (next_run - now).total_seconds()))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("TAIFEX daily history collection failed")
                await asyncio.sleep(900)

    def _collect_futures_codes_sync(self, instruments: list[dict[str, str]], days: int) -> bool:
        if not market_history_db.sessions:
            return False
        # Stock and futures backfills share an advisory lock. Do not skip this
        # startup pass when the stock backfill currently owns the lock.
        for attempt in range(6):
            with market_history_db.collection_lock() as acquired:
                if acquired:
                    return not self.collect_futures_codes(instruments, days)
            if attempt < 5:
                time.sleep(10)
        logger.info("Market history lock stayed busy; futures collection will retry")
        return False

    def _collect_codes_sync(self, codes: list[str], days: int) -> None:
        if not market_history_db.sessions:
            logger.info("Skipping market history collection because the history database is not configured")
            return
        with market_history_db.collection_lock() as acquired:
            if not acquired:
                logger.info("Another Maya Sawa pod is collecting market history")
                return
            self._collect_codes_locked(codes, days)

    def _collect_codes_locked(self, codes: list[str], days: int) -> None:
        now = datetime.now(TAIPEI_TZ)
        today = now.date() if (now.hour, now.minute) >= (18, 20) else now.date() - timedelta(days=1)
        dates = [today - timedelta(days=offset) for offset in range(days)
                 if (today - timedelta(days=offset)).weekday() < 5]
        covered = market_history_db.covered_codes(list(self.SOURCES), codes, dates, retry_no_data=False)
        ordered_dates = sorted(dates)
        sources = [source for source in self.SOURCES if source != "tdcc:distribution-history"]
        # Finish one source across the selected dates before moving to the next.
        # This keeps a long backfill from repeatedly serving recent dates while
        # older history (and weekly ownership) never reaches the front of queue.
        for source_key in sources:
            source_covered = covered
            if source_key == "twse:borrow-short":
                # Recheck prior no_data rows after parser/source corrections;
                # TWT93U's root-level JSON payload used to be misparsed.
                source_covered = market_history_db.covered_codes(
                    [source_key], codes, dates, retry_no_data=True)
            for trading_date in ordered_dates:
                refresh_recent = (today - trading_date).days <= 3
                if not refresh_recent and all((source_key, code, trading_date) in source_covered for code in codes):
                    continue
                self._collect_source_day(source_key, trading_date, codes)
                if self._request_delay:
                    time.sleep(self._request_delay)
        tdcc_covered = market_history_db.covered_codes(["tdcc:distribution-history"], codes, dates)
        self._collect_tdcc_history_range(codes, dates, tdcc_covered)

    def collect_futures_codes(self, instruments: list[dict[str, str]], days: int | None = None) -> bool:
        """Backfill regular-session daily TAIFEX prices for selected listed contracts."""
        selected = {}
        for item in instruments:
            code = str(item.get("code") or "").strip().upper()
            month = str(item.get("deliveryMonth") or "").replace("/", "").strip()
            suffix = re.search(r"([FGHJKMNQUVXZ])(\d)$", code)
            # Shioaji's continuous TAIEX future is TXF; TAIFEX's daily CSV
            # identifies the same contract root as TX.
            root = ("TX" if code == "TXF" else code[:-2] if suffix else
                    re.match(r"^([A-Z]+)", code).group(1) if re.match(r"^([A-Z]+)", code) else "")
            if not month and suffix:
                month_number = {"F": "01", "G": "02", "H": "03", "J": "04", "K": "05", "M": "06",
                                "N": "07", "Q": "08", "U": "09", "V": "10", "X": "11", "Z": "12"}[suffix.group(1)]
                year = datetime.now(TAIPEI_TZ).year // 10 * 10 + int(suffix.group(2))
                month = f"{year:04d}{month_number}"
            if code and root and (re.fullmatch(r"\d{6}", month) or code == "TXF"):
                selected[code] = {"root": root, "month": month, "name": item.get("name", code)}
        if not selected or not market_history_db.sessions:
            return False
        had_errors = False
        now = datetime.now(TAIPEI_TZ)
        latest = now.date() if (now.hour, now.minute) >= (18, 20) else now.date() - timedelta(days=1)
        period = max(1, min(days or self._backfill_days, 366))
        dates = [latest - timedelta(days=offset) for offset in range(period)
                 if (latest - timedelta(days=offset)).weekday() < 5]
        source = "taifex:daily-futures-price"
        institutional_source = "taifex:futures-institutional"
        covered = market_history_db.covered_codes([source, institutional_source], list(selected), dates)
        price_url = "https://www.taifex.com.tw/cht/3/futDataDown"
        institutional_url = "https://www.taifex.com.tw/cht/3/futContractsDateDown"
        for trading_date in sorted(dates):
            refresh_recent = (latest - trading_date).days <= 3
            price_targets = [code for code in selected if refresh_recent or (source, code, trading_date) not in covered]
            institutional_targets = [code for code in selected if refresh_recent or (institutional_source, code, trading_date) not in covered]
            date_contracts = {}
            for code in price_targets:
                identity = selected[code].copy()
                if code == "TXF" and not identity["month"]:
                    identity["month"] = _taifex_front_month(trading_date)
                date_contracts[code] = identity
            for root in sorted({date_contracts[code]["root"] for code in price_targets}):
                target_codes = [code for code in price_targets if date_contracts[code]["root"] == root]
                form = urllib.parse.urlencode({"down_type": "1", "queryStartDate": trading_date.strftime("%Y/%m/%d"),
                                               "queryEndDate": trading_date.strftime("%Y/%m/%d"),
                                               "commodity_id": "specialid", "commodity_id2": root}).encode()
                request = urllib.request.Request(price_url, data=form, headers={"Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "TY-Multiverse-MarketDashboard/1.0"})
                try:
                    document = _download_taifex_csv(request, required_fields={
                        "交易日期", "契約", "到期月份(週別)", "交易時段"}, timeout=25)
                    rows = parse_taifex_daily_futures_csv(document,
                        {code: date_contracts[code] for code in target_codes}, trading_date)
                    market_history_db.write_source_day(source, trading_date, "futures", rows, target_codes,
                        status="ok" if rows else "no_data", detail="regular session; one row per listed contract month",
                        source_url=price_url, unit="points / contracts")
                except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError,
                        UnicodeError, ValueError) as exc:
                    had_errors = True
                    logger.warning("TAIFEX history source failed: %s %s: %s", root, trading_date, exc)
                    market_history_db.write_source_day(source, trading_date, "futures", [], target_codes,
                        status="error", detail=str(exc)[:300], source_url=price_url, unit="points / contracts")
                time.sleep(max(self._request_delay, 0.5))
        # The official endpoint accepts a date range and returns all daily
        # category rows. Fetch once per commodity instead of once per day; this
        # avoids TAIFEX rate limits during a 92-day startup backfill.
        institutional_by_date: dict[date, list[str]] = {}
        commodity_by_code: dict[str, str] = {}
        for trading_date in sorted(dates):
            refresh_recent = (latest - trading_date).days <= 3
            for code in selected:
                if not refresh_recent and (institutional_source, code, trading_date) in covered:
                    continue
                root = selected[code]["root"]
                # TAIFEX publishes stock-futures institutions only as a
                # combined stock-futures product (STF). Do not attribute
                # that aggregate to every individual contract. Keep exact
                # contract-level coverage explicitly non-applicable.
                if root not in {"TX", "STF"}:
                    market_history_db.write_source_day(
                        institutional_source, trading_date, "futures", [], [code],
                        status="no_data", detail="TAIFEX institutional positions are not published per stock-futures contract",
                        source_url=institutional_url, unit="contracts / TWD thousands")
                    continue
                commodity = "TXF" if code == "TXF" else root
                commodity_by_code[code] = commodity
                institutional_by_date.setdefault(trading_date, []).append(code)
        for commodity in sorted(set(commodity_by_code.values())):
            commodity_codes = [code for code, value in commodity_by_code.items() if value == commodity]
            commodity_dates = [trading_date for trading_date, codes in institutional_by_date.items()
                               if any(code in commodity_codes for code in codes)]
            if not commodity_dates:
                continue
            form = urllib.parse.urlencode({
                "queryStartDate": min(commodity_dates).strftime("%Y/%m/%d"),
                "queryEndDate": max(commodity_dates).strftime("%Y/%m/%d"),
                "commodityId": commodity,
            }).encode()
            request = urllib.request.Request(institutional_url, data=form, headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.taifex.com.tw/cht/3/futContractsDateView",
                "User-Agent": "TY-Multiverse-MarketDashboard/1.0"})
            try:
                document = _download_taifex_csv(request, required_fields={"日期", "身份別", "多方交易口數"})
                for trading_date in sorted(commodity_dates):
                    target_codes = [code for code in institutional_by_date[trading_date]
                                    if commodity_by_code.get(code) == commodity]
                    aggregate = parse_taifex_futures_institutional_csv(document, trading_date)
                    rows = [{"code": code, "name": selected[code]["name"], "values": aggregate[0]["values"]}
                            for code in target_codes] if aggregate else []
                    category = "股票期貨商品彙總" if commodity == "STF" else f"{commodity}商品彙總"
                    market_history_db.write_source_day(institutional_source, trading_date, "futures", rows,
                        target_codes, status="ok" if rows else "no_data",
                        detail=f"{category}; not specific-contract positions", source_url=institutional_url,
                        unit="contracts / TWD thousands")
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError,
                    UnicodeError, ValueError) as exc:
                had_errors = True
                logger.warning("TAIFEX futures institutional history failed: %s %s–%s: %s", commodity,
                               min(commodity_dates), max(commodity_dates), exc)
                for trading_date in commodity_dates:
                    target_codes = [code for code in institutional_by_date[trading_date]
                                    if commodity_by_code.get(code) == commodity]
                    market_history_db.write_source_day(institutional_source, trading_date, "futures", [],
                        target_codes, status="error", detail=str(exc)[:300], source_url=institutional_url,
                        unit="contracts / TWD thousands")
            if self._request_delay:
                time.sleep(self._request_delay)
        return had_errors

    def _collect_source_day(self, source_key: str, trading_date: date, codes: list[str]) -> None:
        product_type, template, unit = self.SOURCE_CONFIG[source_key]
        url = template.format(compact=trading_date.strftime("%Y%m%d"),
                              slash=trading_date.strftime("%Y/%m/%d"))
        try:
            request_data = None
            request_headers = {"User-Agent": "TY-Multiverse-MarketDashboard/1.0"}
            if source_key == "tpex:foreign-holding":
                request_data = urllib.parse.urlencode({"date": trading_date.strftime("%Y/%m/%d"),
                                                       "response": "json"}).encode()
                request_headers["Content-Type"] = "application/x-www-form-urlencoded"
            request = urllib.request.Request(url, data=request_data, headers=request_headers)
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.load(response)
            response_date = _normalize_date(payload.get("date"))
            if response_date and response_date != trading_date:
                raise ValueError(f"Source returned {response_date} for requested {trading_date}")
            rows = self._parse_source(source_key, payload)
            status = "ok" if rows else "no_data"
            detail = str(payload.get("stat") or "").strip()
            market_history_db.write_source_day(source_key, trading_date, product_type, rows, codes,
                                               status=status, detail=detail, source_url=url, unit=unit)
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError,
                json.JSONDecodeError, ValueError) as exc:
            logger.warning("Market history source failed: %s %s: %s", source_key, trading_date, exc)
            try:
                market_history_db.write_source_day(source_key, trading_date, product_type, [], codes,
                                                   status="error", detail=str(exc)[:300], source_url=url, unit=unit)
            except Exception:
                logger.exception("Could not record market source failure")

    def _collect_tdcc_history_range(self, codes: list[str], dates: list[date],
                                    covered: set[tuple[str, str, date]]) -> None:
        source_key = "tdcc:distribution-history"
        product_type, url, unit = self.SOURCE_CONFIG[source_key]
        if not dates:
            return
        try:
            # The synchronizer token is bound to a short-lived landing-page
            # cookie. Refresh the form session for each date/code POST.
            _, _, _, available_dates = self._open_tdcc_history(url)
            lower, upper = min(dates).strftime("%Y%m%d"), max(dates).strftime("%Y%m%d")
            weeks = sorted(value for value in available_dates if lower <= value <= upper)
            for raw_date in weeks:
                week_date = datetime.strptime(raw_date, "%Y%m%d").date()
                # Retry no_data/error coverage as well: it can reflect a
                # transient source response or a parser fix, not a final result.
                missing_codes = [code for code in codes
                                 if (source_key, code, week_date) not in covered]
                if not missing_codes:
                    continue
                for code in missing_codes:
                    try:
                        opener, token, first_date, current_dates = self._open_tdcc_history(url)
                        if raw_date not in current_dates:
                            raise ValueError(f"TDCC date {raw_date} is no longer available")
                        row = self._fetch_tdcc_stock(opener, url, token, first_date, raw_date, code)
                        market_history_db.write_source_day(source_key, week_date, product_type,
                                                           [row] if row else [], [code],
                                                           status="ok" if row else "no_data",
                                                           detail="historical weekly snapshot" if row else "no matching TDCC row",
                                                           source_url=url, unit=unit)
                    except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError, ValueError) as exc:
                        logger.warning("TDCC history source failed: %s %s: %s", raw_date, code, exc)
                        market_history_db.write_source_day(source_key, week_date, product_type, [], [code],
                                                           status="error", detail=str(exc)[:300], source_url=url, unit=unit)
                    if self._request_delay:
                        time.sleep(self._request_delay)
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError, ValueError) as exc:
            logger.warning("TDCC history date list unavailable: %s", exc)

    @staticmethod
    def _open_tdcc_history(url: str):
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 TY-Multiverse-MarketDashboard/1.0"})
        with opener.open(request, timeout=25) as response:
            landing = response.read().decode("utf-8", errors="replace")
        token = re.search(r'name="SYNCHRONIZER_TOKEN" value="([^"]+)"', landing)
        first_date = re.search(r'name="firDate" value="(\d{8})"', landing)
        available_dates = set(re.findall(r'<option value="(\d{8})"', landing))
        if not token or not first_date:
            raise ValueError("TDCC query form is missing synchronization fields")
        return opener, token.group(1), first_date.group(1), available_dates

    @staticmethod
    def _fetch_tdcc_history(url: str, trading_date: date, codes: list[str]) -> dict[str, dict[str, Any]]:
        opener, token, first_date, available_dates = MarketHistoryCollector._open_tdcc_history(url)
        requested = trading_date.strftime("%Y%m%d")
        selected_date = requested if requested in available_dates else max(
            (value for value in available_dates if value <= requested), default=None
        )
        if not selected_date:
            return {}
        result = {}
        for code in codes:
            row = MarketHistoryCollector._fetch_tdcc_stock(opener, url, token, first_date, selected_date, code)
            if row:
                result[code] = row
            time.sleep(0.15)
        return result

    @staticmethod
    def _fetch_tdcc_stock(opener, url: str, token: str, first_date: str,
                          selected_date: str, code: str) -> dict[str, Any] | None:
        session_path = "/portal/zh/smWeb/qryStock"
        form = urllib.parse.urlencode({
            "SYNCHRONIZER_TOKEN": token, "SYNCHRONIZER_URI": session_path,
            "method": "submit", "firDate": first_date, "scaDate": selected_date,
            "sqlMethod": "StockNo", "stockNo": code, "stockName": "",
        }).encode()
        post = urllib.request.Request(url, data=form, headers={
            "User-Agent": "Mozilla/5.0 TY-Multiverse-MarketDashboard/1.0",
            "Content-Type": "application/x-www-form-urlencoded", "Referer": url,
        })
        with opener.open(post, timeout=25) as response:
            document = response.read().decode("utf-8", errors="replace")
        parsed = parse_tdcc_distribution_html(document, code)
        expected = datetime.strptime(selected_date, "%Y%m%d").date()
        return parsed if parsed and parsed["trading_date"] == expected else None

    @staticmethod
    def _parse_source(source_key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        if source_key == "twse:daily-price": return parse_twse_daily_price(payload)
        if source_key == "twse:institutional": return parse_twse_institutional(payload)
        if source_key == "twse:foreign-holding": return parse_twse_foreign_holding(payload)
        if source_key == "twse:margin-balance": return parse_twse_margin(payload)
        if source_key == "twse:borrow-short": return parse_twse_borrow_short(payload)
        if source_key == "tpex:daily-price": return parse_tpex_daily_price(payload)
        if source_key == "tpex:institutional": return parse_tpex_institutional(payload)
        if source_key == "tpex:foreign-holding": return parse_tpex_foreign_holding(payload)
        if source_key == "tpex:margin-balance": return parse_tpex_margin(payload)
        if source_key == "tpex:borrow-short": return parse_tpex_borrow_short(payload)
        if source_key == "tdcc:distribution-latest": return parse_tdcc_distribution(payload)
        raise ValueError(f"Unknown market data source: {source_key}")


def _taifex_front_month(trading_date: date) -> str:
    """Return the monthly contract whose third-Wednesday expiry has not passed."""
    year, month = trading_date.year, trading_date.month
    for offset in range(3):
        candidate_month = month + offset
        candidate_year = year + (candidate_month - 1) // 12
        candidate_month = (candidate_month - 1) % 12 + 1
        first_weekday, days_in_month = calendar.monthrange(candidate_year, candidate_month)
        first_wednesday = 1 + ((2 - first_weekday) % 7)
        expiry = date(candidate_year, candidate_month, first_wednesday + 14)
        if expiry >= trading_date:
            return f"{candidate_year:04d}{candidate_month:02d}"
    raise ValueError(f"Could not resolve futures month for {trading_date}")


def _normalize_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip().replace("/", "")
    if text.isdigit() and len(text) == 8:
        return datetime.strptime(text, "%Y%m%d").date()
    if text.isdigit() and len(text) == 7:
        return date(1911 + int(text[:3]), int(text[3:5]), int(text[5:]))
    return None


market_history_collector = MarketHistoryCollector()
