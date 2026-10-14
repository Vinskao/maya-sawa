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
