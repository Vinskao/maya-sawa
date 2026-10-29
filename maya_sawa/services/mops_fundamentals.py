"""Whole-market Taiwan fundamentals from MOPS summary tables (公開資訊觀測站彙總報表), five years, no API key.

One request returns every listed (sii) or OTC (otc) company for one month or one quarter:

    revenue  t21sc03   monthly revenue                         NT$ thousand
    income   t163sb04  income statement, year to date          NT$ thousand (EPS in NT$)
    balance  t163sb05  balance sheet at quarter end            NT$ thousand
    cash     t163sb20  cash flow summary, year to date         NT$ thousand

Values are stored in yuan with FinMind's dataset and item names, so `build_fundamental_metrics` reads them unchanged.
Single-quarter income is the difference of consecutive year-to-date values; a quarter whose previous quarter is missing is
skipped rather than estimated. Inventory and capex are not in the summaries. Pure parsing here; the collector loop is
`MopsCollector`. Covered by tests/test_mops_fundamentals.py; docs: ty-multiverse-frontend/docs/FUNDAMENTALS_HISTORY_COVERAGE.md.
"""
from __future__ import annotations

import html as html_lib
import logging
import re
import time
import urllib.parse
import urllib.request
from datetime import date

logger = logging.getLogger(__name__)
BASE = "https://mopsov.twse.com.tw"
STATEMENT_PAGES = {"income": "t163sb04", "balance": "t163sb05", "cash": "t163sb20"}
DATASETS = {"revenue": "TaiwanStockMonthRevenue", "income": "TaiwanStockFinancialStatements",
            "balance": "TaiwanStockBalanceSheet", "cash": "TaiwanStockCashFlowsStatement"}
MARKETS = ("sii", "otc")
KIND_ORDER = {"revenue": 0, "income": 1, "balance": 2, "cash": 3}

# Column names differ by industry format (general, bank, securities, insurance, holding, other); first match wins.
INCOME_COLUMNS = {
    "Revenue": ("營業收入", "收益", "收入"),
    "CostOfGoodsSold": ("營業成本",),
    "GrossProfit": ("營業毛利（毛損）淨額", "營業毛利（毛損）"),
    "OperatingIncome": ("營業利益（損失）", "營業利益"),
    "PreTaxIncome": ("稅前淨利（淨損）", "繼續營業單位稅前淨利（淨損）", "繼續營業單位稅前損益", "繼續營業單位稅前純益（純損）"),
    "IncomeAfterTaxes": ("本期淨利（淨損）", "本期稅後淨利（淨損）"),
    "EPS": ("基本每股盈餘（元）", "基本每股盈餘"),
}
BALANCE_COLUMNS = {
    "CurrentAssets": ("流動資產",), "TotalAssets": ("資產總計", "資產總額"),
    "CurrentLiabilities": ("流動負債",), "Liabilities": ("負債總計", "負債總額"),
    "EquityAttributableToOwnersOfParent": ("歸屬於母公司業主之權益合計", "歸屬於母公司業主權益合計"),
    "TotalEquity": ("權益總計", "權益總額"),
}


def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", "", cell))).strip()


def parse_tables(document: str) -> list[dict[str, str]]:
    """Every company row of every table, keyed by that table's own header row (the one containing 公司代號)."""
    rows = []
    for table in re.findall(r"<table.*?</table>", document, flags=re.S | re.I):
        header = None
        for row in re.findall(r"<tr.*?</tr>", table, flags=re.S | re.I):
            cells = [_text(cell) for cell in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S | re.I)]
            if "公司代號" in cells:
                header = cells
            elif header and cells and re.fullmatch(r"\d{4,6}[A-Z]?", cells[0]):   # revenue rows carry an extra 備註 cell
                rows.append(dict(zip(header, cells)))
    return rows


def _number(value: str | None) -> float | None:
    raw = str(value or "").replace(",", "").strip()
    if raw in ("", "--", "-", "N/A"):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _pick(row: dict[str, str], names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in row:
            return _number(row[name])
    return None


def _items(rows: list[dict[str, str]], columns: dict[str, tuple[str, ...]], per_share: tuple[str, ...] = ()) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for row in rows:
        values = {}
        for item, names in columns.items():
            value = _pick(row, names)
            if value is not None:
                values[item] = value if item in per_share else round(value * 1000)
        if values:
            result[row["公司代號"]] = values
    return result


def income_ytd(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    return _items(rows, INCOME_COLUMNS, per_share=("EPS",))


def balance_items(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    return _items(rows, BALANCE_COLUMNS)


def cash_items(rows: list[dict[str, str]], income: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    """Operating cash flow (YTD) plus YTD pre-tax income from the same quarter's income table, for cash conversion."""
    result = _items(rows, {"CashFlowsFromOperatingActivities": ("營業活動之淨現金流入（流出）",)})
    for code, values in result.items():
        if income.get(code, {}).get("PreTaxIncome") is not None:
            values["NetIncomeBeforeTax"] = income[code]["PreTaxIncome"]
    return result


def single_quarter(ytd_by_quarter: dict[int, dict[str, dict[str, float]]], quarter: int) -> dict[str, dict[str, float]]:
    """Q1 is its YTD; later quarters subtract the previous quarter's YTD. EPS is rounded to cents like MOPS reports it."""
    current = ytd_by_quarter.get(quarter)
    if current is None:
        return {}
    if quarter == 1:
        return {code: {item: value for item, value in values.items() if item != "PreTaxIncome"} for code, values in current.items()}
    previous = ytd_by_quarter.get(quarter - 1)
    if previous is None:
        return {}
    result = {}
    for code, values in current.items():
        before = previous.get(code, {})
        single = {item: (round(value - before[item], 2) if item == "EPS" else value - before[item])
                  for item, value in values.items() if item != "PreTaxIncome" and before.get(item) is not None}
        if single:
            result[code] = single
    return result


def revenue_items(rows: list[dict[str, str]]) -> dict[str, dict[str, float]]:
    return _items(rows, {"revenue": ("當月營收",)})


def quarter_end(year: int, quarter: int) -> str:
    return f"{year:04d}-" + ("03-31", "06-30", "09-30", "12-31")[quarter - 1]


def revenue_url(market: str, year: int, month: int) -> str:
    return f"{BASE}/nas/t21/{market}/t21sc03_{year - 1911}_{month}_0.html"


def throttled(document: str) -> bool:
    return "查詢過於頻繁" in document or "Overrun" in document


def backlog(year: int, month: int, years: int = 5, done: set[tuple[str, str, str]] = frozenset()) -> list[tuple[str, str, str]]:
    """(kind, market, period) jobs newest first: 12*years months ending last month, 4*years quarters ending last
    quarter. Periods not yet published come back empty and are simply retried on a later pass."""
    jobs = []
    y, m = (year, month - 1) if month > 1 else (year - 1, 12)
    for _ in range(12 * years):
        for market in MARKETS:
            jobs.append((date(y, m, 1), "revenue", market, f"{y:04d}-{m:02d}"))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    y, q = year, (month - 1) // 3
    if q == 0:
        y, q = year - 1, 4
    for _ in range(4 * years):
        for kind in ("income", "balance", "cash"):
            for market in MARKETS:
                jobs.append((date(y, q * 3, 1), kind, market, f"{y:04d}Q{q}"))
        y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    jobs.sort(key=lambda job: (-job[0].toordinal(), KIND_ORDER[job[1]], MARKETS.index(job[2])))
    return [job[1:] for job in jobs if job[1:] not in done]


def recent_periods(today: date) -> set[str]:
    """The last two published months and quarters: refetched every pass for late filers and restatements."""
    months, quarters = [], []
    y, m = today.year, today.month
    for _ in range(2):
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
        months.append(f"{y:04d}-{m:02d}")
    y, q = today.year, (today.month - 1) // 3
    if q == 0:
        y, q = y - 1, 4
    for _ in range(2):
        quarters.append(f"{y:04d}Q{q}")
        y, q = (y, q - 1) if q > 1 else (y - 1, 4)
    return set(months + quarters)


def _fetch(url: str, form: dict | None = None) -> str:
    data = urllib.parse.urlencode(form).encode() if form else None
    request = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0 (compatible; TYMultiverseResearch/1.0)"})
    with urllib.request.urlopen(request, timeout=60) as response:
        raw = response.read()
    for encoding in ("utf-8", "cp950"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_statement(kind: str, market: str, year: int, quarter: int) -> str:
    form = {"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", "isQuery": "Y",
            "TYPEK": market, "year": str(year - 1911), "season": f"{quarter:02d}"}
    return _fetch(f"{BASE}/mops/web/ajax_{STATEMENT_PAGES[kind]}", form)


def fetch_revenue(market: str, year: int, month: int) -> str:
    return _fetch(revenue_url(market, year, month))


class MopsCollector:
    """Works through `backlog` one page at a time, writing every company of each page in bulk.

    Finished past periods are checkpointed and never refetched; the latest two months and quarters are refetched daily
    (late filers, restatements). MOPS throttles bursts, so pages are spaced `gap_seconds` apart and a throttle page
    pauses the pass."""

    def __init__(self, db, fetch_statement=fetch_statement, fetch_revenue=fetch_revenue, sleep=time.sleep, gap_seconds: float = 8):
        self.db, self.fetch_statement, self.fetch_revenue, self.sleep, self.gap = db, fetch_statement, fetch_revenue, sleep, gap_seconds

    def _write(self, kind: str, period: str, by_code: dict[str, dict[str, float]], source_url: str) -> int:
        records = [{"code": code, "period": period, "item": item, "value": value,
                    "unit": "元" if item == "EPS" else "新台幣元"} for code, values in by_code.items() for item, value in values.items()]
        return self.db.upsert_many(DATASETS[kind], records, source_url)

    def run_job(self, kind: str, market: str, period: str) -> int:
        if kind == "revenue":
            year, month = int(period[:4]), int(period[5:])
            document = self.fetch_revenue(market, year, month)
            if throttled(document):
                raise RuntimeError("mops_throttled")
            return self._write(kind, period, revenue_items(parse_tables(document)), revenue_url(market, year, month))
        year, quarter = int(period[:4]), int(period[-1])
        source = f"{BASE}/mops/web/{STATEMENT_PAGES[kind]}"
        pages = {}
        for q in ([quarter - 1, quarter] if kind == "income" and quarter > 1 else [quarter]):
            document = self.fetch_statement("income" if kind in ("income", "cash") and q != quarter else kind, market, year, q)
            if throttled(document):
                raise RuntimeError("mops_throttled")
            pages[q] = document
            self.sleep(self.gap)
        if kind == "income":
            ytd = {q: income_ytd(parse_tables(document)) for q, document in pages.items()}
            return self._write(kind, quarter_end(year, quarter), single_quarter(ytd, quarter), source)
        if kind == "balance":
            return self._write(kind, quarter_end(year, quarter), balance_items(parse_tables(pages[quarter])), source)
        income_page = self.fetch_statement("income", market, year, quarter)
        if throttled(income_page):
            raise RuntimeError("mops_throttled")
        return self._write(kind, quarter_end(year, quarter),
                           cash_items(parse_tables(pages[quarter]), income_ytd(parse_tables(income_page))), source)

    def run_pass(self, today: date, max_jobs: int = 60) -> int:
        """Up to max_jobs pages per pass; returns how many jobs wrote rows."""
        recent = recent_periods(today)
        done = {job for job in self.db.mops_done() if job[2] not in recent}
        jobs = backlog(today.year, today.month, done=done)[:max_jobs]
        written = 0
        for kind, market, period in jobs:
            try:
                rows = self.run_job(kind, market, period)
            except RuntimeError as exc:
                if str(exc) == "mops_throttled":
                    logger.warning("MOPS throttled the collector; pausing this pass")
                    return written
                raise
            except Exception as exc:
                logger.warning("MOPS %s/%s/%s failed: %s", kind, market, period, type(exc).__name__)
                self.db.record_mops(kind, market, period, "error")
                self.sleep(self.gap)
                continue
            self.db.record_mops(kind, market, period, "success" if rows else "empty")
            written += bool(rows)
            self.sleep(self.gap)
        return written
