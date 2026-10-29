"""Taiwan fundamentals for the whole market from MOPS summary tables (公開資訊觀測站彙總報表), replacing FinMind.

2026-10-29: the owner wants five years for every listed and OTC company without paying, and FinMind Free is licensed
for non-commercial use only. MOPS publishes one page per month (revenue, t21sc03) and per quarter (income t163sb04,
balance sheet t163sb05, cash flow t163sb20) with every company in it; amounts are NT$ thousand and statements are
year-to-date, so single quarters are the difference of consecutive YTD values. Items are written with FinMind's names
so the metrics code reads them unchanged. Inventory and capex are not in the summaries (see docs).

Fixtures are real 2026 MOPS pages with only the rows of 2330, 1101, 2801, 2855 and 6488 kept (every table and header).
"""
from datetime import date
from pathlib import Path

import pytest

from maya_sawa.services import mops_fundamentals as mops

FIX = Path(__file__).parent / "fixtures" / "mops"
read = lambda name: (FIX / name).read_text(encoding="utf-8")


def test_tables_are_read_by_header_across_industry_formats():
    rows = mops.parse_tables(read("t163sb04_sii_115Q2.html"))
    by_code = {row["公司代號"]: row for row in rows}
    assert by_code["2330"]["營業收入"] == "2,404,483,690"          # general industry table
    assert by_code["2801"]["利息淨收益"] == "15,221,502"            # bank table has its own columns
    assert "營業收入" not in by_code["2801"]


def test_income_is_year_to_date_in_yuan_with_eps_as_reported():
    ytd = mops.income_ytd(mops.parse_tables(read("t163sb04_sii_115Q2.html")))
    tsmc = ytd["2330"]
    assert tsmc["Revenue"] == 2_404_483_690_000
    assert tsmc["GrossProfit"] == 1_611_606_116_000
    assert tsmc["OperatingIncome"] == 1_425_568_793_000
    assert tsmc["IncomeAfterTaxes"] == 1_279_582_227_000
    assert tsmc["PreTaxIncome"] == 1_550_229_773_000
    assert tsmc["EPS"] == 49.33
    # A bank has no revenue or gross profit line; only what it reports is kept.
    assert "Revenue" not in ytd["2801"] and ytd["2801"]["IncomeAfterTaxes"] == 11_314_353_000 and ytd["2801"]["EPS"] == 0.94


def test_single_quarter_is_the_difference_of_consecutive_year_to_date_values():
    q1 = mops.income_ytd(mops.parse_tables(read("t163sb04_sii_115Q1.html")))
    q2 = mops.income_ytd(mops.parse_tables(read("t163sb04_sii_115Q2.html")))
    single = mops.single_quarter({1: q1, 2: q2}, 2)
    assert single["2330"]["Revenue"] == 1_270_380_250_000
    assert single["2330"]["CostOfGoodsSold"] == 410_069_555_000
    assert single["2330"]["EPS"] == pytest.approx(27.25)
    assert mops.single_quarter({1: q1, 2: q2}, 1)["2330"]["Revenue"] == 1_134_103_440_000
    # Without the previous quarter a later quarter cannot be split, so nothing is invented.
    assert mops.single_quarter({2: q2}, 2) == {}


def test_balance_sheet_items_for_general_and_bank_formats():
    balance = mops.balance_items(mops.parse_tables(read("t163sb05_sii_115Q2.html")))
    assert balance["2330"] == {"CurrentAssets": 4_565_700_742_000, "TotalAssets": 9_375_654_727_000,
        "CurrentLiabilities": 1_857_761_825_000, "Liabilities": 2_901_183_746_000,
        "EquityAttributableToOwnersOfParent": 6_432_518_334_000, "TotalEquity": 6_474_470_981_000}
    assert balance["2801"]["TotalAssets"] == 3_535_310_278_000 and balance["2801"]["Liabilities"] == 3_305_610_200_000


def test_cash_flow_keeps_year_to_date_operating_cash_and_pre_tax_income():
    income = mops.income_ytd(mops.parse_tables(read("t163sb04_sii_115Q2.html")))
    cash = mops.cash_items(mops.parse_tables(read("t163sb20_sii_115Q2.html")), income)
    assert cash["2330"] == {"CashFlowsFromOperatingActivities": 1_482_341_242_000, "NetIncomeBeforeTax": 1_550_229_773_000}
    assert cash["2801"]["CashFlowsFromOperatingActivities"] == -37_473_949_000


def test_monthly_revenue_in_yuan():
    revenue = mops.revenue_items(mops.parse_tables(read("t21sc03_sii_115_9.html")))
    assert revenue["2330"] == {"revenue": 511_857_399_000}


def test_periods_and_urls():
    assert mops.quarter_end(2026, 2) == "2026-06-30" and mops.quarter_end(2025, 4) == "2025-12-31"
    assert mops.revenue_url("sii", 2026, 9) == "https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_115_9_0.html"
    assert mops.revenue_url("otc", 2021, 1) == "https://mopsov.twse.com.tw/nas/t21/otc/t21sc03_110_1_0.html"


def test_backlog_is_newest_first_and_skips_finished_periods():
    jobs = mops.backlog(year=2026, month=10, years=5, done={("income", "sii", "2026Q2"), ("revenue", "otc", "2026-08")})
    assert jobs[0] == ("revenue", "sii", "2026-09")              # October revenue is not out yet; September first
    assert ("revenue", "otc", "2026-08") not in jobs and ("income", "sii", "2026Q2") not in jobs
    assert ("income", "otc", "2026Q2") in jobs and ("balance", "sii", "2021Q4") in jobs
    assert ("revenue", "sii", "2021-10") in jobs and ("revenue", "sii", "2021-09") not in jobs


def test_a_throttled_page_is_detected():
    assert mops.throttled("<html>查詢過於頻繁，請稍後再試</html>")
    assert not mops.throttled(read("t163sb05_sii_115Q2.html"))


def _db():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from maya_sawa.databases import market_fundamentals_db as module
    db = object.__new__(module.MarketFundamentalsDatabase)
    db.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    db.sessions = sessionmaker(bind=db.engine)
    module.Base.metadata.create_all(db.engine)
    return db


def test_bulk_upsert_keeps_items_from_other_sources_and_labels_the_source():
    db = _db()
    db.upsert_many("TaiwanStockBalanceSheet", [{"code": "2330", "period": "2026-06-30", "item": "Inventories", "value": 1.0, "unit": "新台幣元"}],
                   "https://api.finmindtrade.com/api/v4/data")
    db.upsert_many("TaiwanStockBalanceSheet", [{"code": "2330", "period": "2026-06-30", "item": "TotalAssets", "value": 9.0, "unit": "新台幣元"},
                                               {"code": "2330", "period": "2026-06-30", "item": "TotalAssets", "value": 9.5, "unit": "新台幣元"}],
                   "https://mopsov.twse.com.tw/mops/web/t163sb05")
    rows = {row["item"]: row for row in db.rows("2330", "TaiwanStockBalanceSheet")}
    assert rows["Inventories"]["source"] == "FinMind" and rows["TotalAssets"]["source"] == "MOPS"
    assert rows["TotalAssets"]["value"] == "9.5"                        # last write of a duplicate wins


def test_checkpoints_mark_successful_periods_done():
    db = _db()
    db.record_mops("income", "sii", "2026Q2", "success")
    db.record_mops("income", "otc", "2026Q2", "empty")
    db.record_mops("income", "otc", "2026Q2", "error")
    assert db.mops_done() == {("income", "sii", "2026Q2")}


def test_a_pass_writes_single_quarters_and_stops_when_throttled():
    db = _db()
    calls = []

    def statement(kind, market, year, quarter):
        calls.append((kind, market, quarter))
        if market == "otc":
            return "<html>查詢過於頻繁</html>"
        return read({("income", 1): "t163sb04_sii_115Q1.html", ("income", 2): "t163sb04_sii_115Q2.html",
                     ("balance", 2): "t163sb05_sii_115Q2.html", ("cash", 2): "t163sb20_sii_115Q2.html"}.get((kind, quarter), "t163sb05_sii_115Q2.html"))

    collector = mops.MopsCollector(db, fetch_statement=statement, fetch_revenue=lambda market, year, month: read("t21sc03_sii_115_9.html"),
                                   sleep=lambda seconds: None)
    collector.run_job("income", "sii", "2026Q2")
    collector.run_job("cash", "sii", "2026Q2")
    income = {row["item"]: row["value"] for row in db.rows("2330", "TaiwanStockFinancialStatements") if row["period"] == "2026-06-30"}
    assert float(income["Revenue"]) == 1_270_380_250_000 and float(income["EPS"]) == pytest.approx(27.25)
    cash = {row["item"]: row["value"] for row in db.rows("2330", "TaiwanStockCashFlowsStatement")}
    assert float(cash["NetIncomeBeforeTax"]) == 1_550_229_773_000
    # A pass for 2026-07: September revenue (sii) is written, then the OTC page is throttled and the pass stops.
    done_before = db.mops_done()
    collector.run_pass(date(2026, 10, 29), max_jobs=40)
    assert ("revenue", "sii", "2026-09") in db.mops_done() - done_before
    assert ("income", "otc", "2026Q3") not in db.mops_done()


def test_the_latest_two_months_and_quarters_are_refetched_even_when_done():
    assert mops.recent_periods(date(2026, 10, 29)) == {"2026-09", "2026-08", "2026Q3", "2026Q2"}
    assert mops.recent_periods(date(2026, 1, 5)) == {"2025-12", "2025-11", "2025Q4", "2025Q3"}
