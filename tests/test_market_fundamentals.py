from maya_sawa.services.market_fundamentals import MarketFundamentalsService


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
