import pytest
from datetime import date
from maya_sawa.services.market_fundamentals import MarketFundamentalsService, build_fundamental_metrics, fundamental_start_date


def test_fundamental_backfill_starts_five_calendar_years_ago_including_leap_day():
    assert fundamental_start_date(date(2026, 10, 29)) == "2021-10-29"
    assert fundamental_start_date(date(2024, 2, 29)) == "2019-02-28"


def test_fundamental_metrics_keep_five_years_of_monthly_and_quarterly_history():
    monthly = []
    income, balance, cash = [], [], []
    for offset in range(72):
        year, month = 2020 + offset // 12, (offset % 12) + 1
        monthly.append({"period": f"{year:04d}-{month:02d}", "item": "revenue", "value": 100 + offset})
    for offset in range(24):
        year, quarter = 2020 + offset // 4, offset % 4 + 1
        month = quarter * 3
        from calendar import monthrange
        end = f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"
        for item, value in (("Revenue", 100 + offset), ("GrossProfit", 50 + offset),
                            ("OperatingIncome", 30 + offset), ("EPS", 2 + offset)):
            income.append({"period": end, "item": item, "value": value})
        for item, value in (("TotalAssets", 1000 + offset), ("Liabilities", 500 + offset), ("Inventories", 100 + offset)):
            balance.append({"period": end, "item": item, "value": value})
        cash.append({"period": end, "item": "CashFlowsFromOperatingActivities", "value": 100 + offset})

    metrics = build_fundamental_metrics([], [], {
        "TaiwanStockMonthRevenue": monthly,
        "TaiwanStockFinancialStatements": income,
        "TaiwanStockBalanceSheet": balance,
        "TaiwanStockCashFlowsStatement": cash,
    })
    assert len(metrics["monthly"]) == 60 and metrics["monthly"][0]["period"] == "2021-01"
    assert len(metrics["quarterly"]) == len(metrics["balance"]) == len(metrics["cashFlow"]) == 20
    assert metrics["quarterly"][0]["period"] == "2021Q1"


def test_monthly_revenue_parser_maps_official_mops_otc_csv_fields():
    csv_text = (
        "出表日期,資料年月,公司代號,公司名稱,產業別,營業收入-當月營收,營業收入-上月營收,"
        "營業收入-去年當月營收,營業收入-上月比較增減(%),營業收入-去年同月增減(%),"
        "累計營業收入-當月累計營收\n"
        "1151014,11509,3081,聯亞,半導體業,321000,300000,250000,7,28.4,2600000\n"
    )
    result = MarketFundamentalsService._monthly_rows(csv_text, "3081")
    assert len(result) == 1
    assert result[0]["period"] == "2026-09"
    assert result[0]["revenue"] == 321000
    assert result[0]["momPercent"] == 7
    assert result[0]["yoyPercent"] == 28.4
    assert result[0]["unit"] == "新台幣千元"


def test_quarterly_statement_derives_single_quarter_from_ytd_values():
    rows = [
        {"公司代號": "2330", "年度": "115", "季別": "1", "出表日期": "1150501",
         "營業收入": "100", "營業毛利（毛損）淨額": "50", "營業利益（損失）": "30",
         "本期淨利（淨損）": "20", "基本每股盈餘（元）": "4.5"},
        {"公司代號": "2330", "年度": "115", "季別": "2", "出表日期": "1150810",
         "營業收入": "240", "營業毛利（毛損）淨額": "120", "營業利益（損失）": "70",
         "本期淨利（淨損）": "50", "基本每股盈餘（元）": "10.2"},
    ]
    result = MarketFundamentalsService._statement_rows(rows, "2330", "income")
    q2 = result[-1]
    assert q2["period"] == "2026Q2"
    assert q2["reportedCumulative"]["revenue"] == 240
    assert q2["singleQuarter"]["revenue"] == 140
    assert q2["singleQuarter"]["netIncome"] == 30
    assert q2["epsReported"] == 10.2


def test_quarterly_q1_eps_is_reported_without_quarter_addition():
    rows = [{"公司代號": "2330", "年度": "115", "季別": "1", "營業收入": "100",
             "營業毛利（毛損）淨額": "50", "營業利益（損失）": "30",
             "本期淨利（淨損）": "20", "基本每股盈餘（元）": "4.5"}]
    result = MarketFundamentalsService._statement_rows(rows, "2330", "income")
    assert result[0]["singleQuarter"]["revenue"] == 100
    assert result[0]["epsReported"] == 4.5


def test_metrics_report_growth_and_margin_changes_without_amounts():
    from maya_sawa.services.market_fundamentals import build_fundamental_metrics, _finmind_records

    def quarter(date, revenue, gross, operating, net, eps):
        return [{"period": date, "item": key, "value": value} for key, value in (
            ("Revenue", revenue), ("GrossProfit", gross), ("OperatingIncome", operating),
            ("IncomeAfterTaxes", net), ("EPS", eps))]

    income = (quarter("2025-03-31", 100, 50, 40, 30, 2.0) + quarter("2025-12-31", 150, 72, 60, 45, 3.0)
              + quarter("2026-03-31", 160, 80, 64, 48, 3.2))
    months = _finmind_records("TaiwanStockMonthRevenue", [
        {"revenue_year": 2025, "revenue_month": 3, "revenue": 1000},
        {"revenue_year": 2026, "revenue_month": 2, "revenue": 1100},
        {"revenue_year": 2026, "revenue_month": 3, "revenue": 1210},
    ])
    metrics = build_fundamental_metrics([], [], {"TaiwanStockFinancialStatements": income,
                                                 "TaiwanStockMonthRevenue": months})
    q1 = metrics["quarterly"][-1]
    assert q1["period"] == "2026Q1"
    assert q1["grossMargin"] == 50.0
    assert q1["grossMarginQoQ"] == 2.0      # 50% vs 48%
    assert q1["grossMarginYoY"] == 0.0
    assert q1["revenueYoY"] == 60.0
    assert q1["epsQoQ"] == 6.67
    march = metrics["monthly"][-1]
    assert march["period"] == "2026-03"
    assert march["momPercent"] == 10.0
    assert march["yoyPercent"] == 21.0
    assert "revenue" not in q1 and "revenue" not in march


def test_official_monthly_yoy_takes_precedence_and_thousands_are_scaled():
    from maya_sawa.services.market_fundamentals import build_fundamental_metrics
    official = [{"period": "2026-09", "revenue": 500, "yoyPercent": 31.4, "momPercent": -0.6}]
    history = {"TaiwanStockMonthRevenue": [{"period": "2026-08", "item": "revenue", "value": 400000}]}
    september = build_fundamental_metrics(official, [], history)["monthly"][-1]
    assert september["yoyPercent"] == 31.4 and september["momPercent"] == -0.6


def test_inventory_days_and_growth_from_real_finmind_rows():
    # Nanya (2408): inventory fell from NT$35.5bn (2025Q2) to NT$21.5bn (2026Q2) while revenue rose 684% YoY.
    import json
    from pathlib import Path
    from maya_sawa.services.market_fundamentals import build_fundamental_metrics, _finmind_records
    raw = json.loads((Path(__file__).parent / "fixtures" / "finmind_2408_inventory.json").read_text(encoding="utf-8"))
    history = {dataset: _finmind_records(dataset, raw[dataset]) for dataset in ("TaiwanStockBalanceSheet", "TaiwanStockFinancialStatements")}
    q2 = next(row for row in build_fundamental_metrics([], [], history)["balance"] if row["period"] == "2026Q2")
    days_now = 21530230000 / 16931613000 * 91.25
    days_year_ago = 35528632000 / 12689937000 * 91.25
    assert q2["inventoryDays"] == pytest.approx(days_now, abs=0.01)
    assert q2["inventoryDaysYoY"] == pytest.approx(days_now - days_year_ago, abs=0.01)
    assert q2["inventoryQoQ"] == pytest.approx((21530230000 / 24330735000 - 1) * 100, abs=0.01)
    assert q2["inventoryYoY"] == pytest.approx((21530230000 / 35528632000 - 1) * 100, abs=0.01)
    # Inventory growth minus revenue growth: negative = inventory building slower than sales (destocking).
    assert q2["inventoryVsRevenueYoY"] == pytest.approx(q2["inventoryYoY"] - (82549073000 / 10526094000 - 1) * 100, abs=0.02)
    assert "inventory" not in q2  # amounts never leave the metrics


def test_inventory_days_fall_back_to_revenue_minus_gross_profit_and_skip_missing_inventory():
    from maya_sawa.services.market_fundamentals import build_fundamental_metrics
    income = [{"period": "2026-06-30", "item": "Revenue", "value": 200}, {"period": "2026-06-30", "item": "GrossProfit", "value": 50}]
    balance = [{"period": "2026-06-30", "item": "Inventories", "value": 30}, {"period": "2026-06-30", "item": "TotalAssets", "value": 100}]
    row = build_fundamental_metrics([], [], {"TaiwanStockFinancialStatements": income, "TaiwanStockBalanceSheet": balance})["balance"][-1]
    assert row["inventoryDays"] == pytest.approx(30 / 150 * 91.25)
    no_inventory = build_fundamental_metrics([], [], {"TaiwanStockFinancialStatements": income,
        "TaiwanStockBalanceSheet": [{"period": "2026-06-30", "item": "TotalAssets", "value": 100}]})["balance"][-1]
    assert no_inventory["inventoryDays"] is None and no_inventory["inventoryYoY"] is None


def test_latest_fundamental_rows_are_bounded_to_the_requested_five_year_window():
    from maya_sawa.services.market_fundamentals import _latest_fundamental_rows
    months = [{"period": str(index)} for index in range(72)]
    quarters = [{"period": str(index)} for index in range(24)]
    assert len(_latest_fundamental_rows(months, 60)) == 60
    assert _latest_fundamental_rows(months, 60)[0]["period"] == "12"
    assert len(_latest_fundamental_rows(quarters, 20)) == 20
    assert _latest_fundamental_rows(quarters, 20)[0]["period"] == "4"
