from datetime import date

from maya_sawa.services.market_history_collector import (
    MarketHistoryCollector,
    _number,
    parse_tpex_borrow_short,
    parse_tpex_foreign_holding,
    parse_tpex_institutional,
    parse_tpex_margin,
    parse_tpex_daily_price,
    parse_twse_daily_price,
    parse_twse_foreign_holding,
    parse_twse_institutional,
    parse_twse_margin,
    parse_twse_borrow_short,
    parse_tdcc_distribution,
    parse_tdcc_distribution_html,
)


def test_number_parses_exchange_format_values():
    assert _number("-1,234") == -1234
    assert _number("+0.32%") == 0.32
    assert _number("--") is None


def test_twse_institutional_and_holding_fields_are_normalized():
    assert parse_twse_institutional({
        "fields": ["證券代號", "證券名稱", "外陸資買賣超股數(不含外資自營商)", "投信買賣超股數",
                   "自營商買賣超股數", "三大法人買賣超股數"],
        "data": [["2330", "台積電", "1,200", "-300", "40", "940"]],
    }) == [{"code": "2330", "name": "台積電", "values": {
        "foreign_net_shares": 1200, "investment_trust_net_shares": -300,
        "dealer_net_shares": 40, "all_institutions_net_shares": 940,
    }}]
    assert parse_twse_foreign_holding({
        "fields": ["證券代號", "證券名稱", "全體外資及陸資持有股數", "全體外資及陸資持股比率",
                   "外資及陸資共用法令投資上限比率", "發行股數"],
        "data": [["2330", "台積電", "8,000", "42.5", "100", "10,000"]],
    })[0]["values"] == {
        "foreign_holding_shares": 8000, "foreign_holding_percent": 42.5,
        "foreign_limit_percent": 100, "issued_shares": 10000,
    }


def test_twse_daily_price_and_margin_balances_use_named_columns():
    assert parse_twse_daily_price({"tables": [{
        "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價"],
        "data": [["2330", "台積電", "10,000", "200", "8,000,000", "800", "820", "790", "810"]],
    }]})[0]["values"] == {
        "open": 800, "high": 820, "low": 790, "close": 810,
        "volume_shares": 10000, "turnover_twd": 8000000, "trades": 200,
    }
    assert parse_twse_margin({"tables": [{
        "fields": ["代號", "名稱", "資買", "資賣", "現償", "前餘額", "今日餘額", "限額",
                   "券買回", "券賣", "現券", "前餘額", "今日餘額", "限額"],
        "data": [["2330", "台積電", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"]],
    }]})[0]["values"] == {
        "margin_buy_lots": 1, "margin_sell_lots": 2, "margin_repayment_lots": 3,
        "margin_balance_lots": 5, "short_cover_lots": 7, "short_sell_lots": 8,
        "short_repayment_lots": 9, "short_balance_lots": 11,
    }


def test_tpex_daily_prices_and_institutional_column_groups():
    quote_fields = ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數",
                    "成交金額(元)", "成交筆數"]
    assert parse_tpex_daily_price({"tables": [{"fields": quote_fields,
        "data": [["6488", "環球晶", "400", "+1", "399", "405", "398", "400", "10,000", "4,000,000", "100"]]}]})[0]["values"] == {
        "open": 399, "high": 405, "low": 398, "close": 400,
        "volume_shares": 10000, "turnover_twd": 4000000, "trades": 100,
    }
    fields = ["代號", "名稱"] + [f"metric-{i}" for i in range(21)] + ["三大法人買賣超股數合計"]
    values = ["6488", "環球晶"] + ["0"] * 21 + ["60"]
    values[10] = "10"
    values[13] = "20"
    values[22] = "30"
    assert parse_tpex_institutional({"tables": [{"fields": fields, "data": [values]}]})[0]["values"] == {
        "foreign_net_shares": 10, "investment_trust_net_shares": 20,
        "dealer_net_shares": 30, "all_institutions_net_shares": 60,
    }


def test_tpex_margin_and_borrow_short_have_distinct_balances():
    margin = ["2330", "台積電"] + [str(index) for index in range(2, 20)]
    assert parse_tpex_margin({"tables": [{"fields": ["代號", "名稱"] + [f"f{i}" for i in range(18)],
        "data": [margin]}]})[0]["values"] == {
        "margin_previous_balance_lots": 2, "margin_buy_lots": 3, "margin_sell_lots": 4,
        "margin_repayment_lots": 5, "margin_balance_lots": 6, "margin_utilization_percent": 8,
        "margin_quota_lots": 9, "short_previous_balance_lots": 10, "short_sell_lots": 11,
        "short_cover_lots": 12, "short_repayment_lots": 13, "short_balance_lots": 14,
        "short_utilization_percent": 16, "short_quota_lots": 17,
    }
    borrowed = ["2330", "台積電"] + [str(index) for index in range(2, 14)]
    result = parse_tpex_borrow_short({"tables": [{"fields": ["股票代號", "股票名稱"] + [f"f{i}" for i in range(13)],
        "data": [borrowed]}]})[0]["values"]
    assert result["short_balance_shares"] == 6
    assert result["borrow_short_balance_shares"] == 12
    assert "borrow_short_balance_shares" != "short_balance_shares"


def test_tpex_foreign_holding_maps_shares_percent_and_limit():
    assert parse_tpex_foreign_holding({"tables": [{"fields": ["排行", "代號", "名稱", "發行股數(A)",
            "僑外資及陸資尚可投資股數B=A*F-C", "僑外資及陸資持有股數(C)",
            "僑外資及陸資尚可投資比率(D=B/A)", "僑外資及陸資持股比率(E=C/A)", "法令投資上限比率(F)", "備註"],
        "data": [["1", "6488", "環球晶", "1,000,000", "300,000", "700,000", "30%", "70%", "100%", ""]]}]}) == [
        {"code": "6488", "name": "環球晶", "values": {"issued_shares": 1000000,
         "foreign_holding_shares": 700000, "foreign_holding_percent": 70,
         "foreign_limit_percent": 100}}]


def test_twse_borrow_short_uses_twt93u_share_columns():
    fields = ["代號", "名稱", "前日餘額", "賣出", "買進", "現券", "今日餘額", "次一營業日限額",
              "前日餘額", "當日賣出", "當日還券", "當日調整", "當日餘額", "次一營業日可限額"]
    result = parse_twse_borrow_short({"tables": [{"fields": fields,
        "data": [["2330", "台積電", "100", "20", "10", "0", "110", "500",
                  "1,000", "30", "5", "2", "1,027", "400"]]}]})
    assert result[0]["values"] == {
        "short_balance_shares": 110, "borrow_short_sell_shares": 30,
        "borrow_short_return_shares": 5, "borrow_short_adjustment_shares": 2,
        "borrow_short_balance_shares": 1027,
    }


def test_tdcc_distribution_rows_keep_tier_and_snapshot_date():
    result = parse_tdcc_distribution([
        {"證券代號": "2330", "資料日期": "20261008", "持股分級": "1", "人數": "10", "股數": "500", "占集保庫存數比例%": "0.01"},
        {"證券代號": "2330", "\ufeff資料日期": "20261008", "持股分級": "2", "人數": "20", "股數": "1,500", "占集保庫存數比例%": "0.02"},
    ], ["2330"])
    assert result == [{"code": "2330", "name": "2330", "trading_date": date(2026, 10, 8),
        "values": {"tiers": [{"tier": 1, "holders": 10, "shares": 500, "percent": 0.01},
                             {"tier": 2, "holders": 20, "shares": 1500, "percent": 0.02}]}}]


def test_tdcc_official_history_page_html_parser_extracts_named_stock_tiers():
    html = '''<div><p>證券代號：2330<br>證券名稱：台積電</p><span>資料日期：115年07月09日</span>
    <div class="table-frame securities-overview"><table>
    <tr><th>序</th><th>持股/單位數分級</th><th>人數</th><th>股數/單位數</th><th>占集保庫存數比例 (%)</th></tr>
    <tr><td>1</td><td>1-999</td><td>2,374,325</td><td>274,129,930</td><td>1.05</td></tr>
    <tr><td>15</td><td>1,000,001以上</td><td>1</td><td>100</td><td>0.00</td></tr></table></div></div>'''
    result = parse_tdcc_distribution_html(html, "2330")
    assert result == {"code": "2330", "name": "台積電", "trading_date": date(2026, 7, 9), "values": {
        "tiers": [{"tier": "1-999", "holders": 2374325, "shares": 274129930, "percent": 1.05},
                  {"tier": "1,000,001以上", "holders": 1, "shares": 100, "percent": 0.0}]}}
    assert parse_tdcc_distribution_html(html, "2317") is None


def test_tdcc_history_fetch_uses_published_date_and_real_form_response(monkeypatch):
    landing = '''<input name="SYNCHRONIZER_TOKEN" value="token"><input name="firDate" value="20261008">
    <option value="20261008">20261008</option><option value="20260709">20260709</option>'''
    result_html = '''<p>證券代號：2330<br>證券名稱：台積電</p><span>資料日期：115年07月09日</span>
    <div class="table-frame securities-overview"><table><tr><th>序</th><th>級距</th><th>人數</th><th>股數</th><th>比例</th></tr>
    <tr><td>1</td><td>1-999</td><td>1</td><td>2</td><td>3.00</td></tr></table></div>'''
    class FakeResponse:
        def __init__(self, body): self.body = body.encode()
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self): return self.body
    class FakeOpener:
        def __init__(self): self.calls = []
        def open(self, request, timeout):
            self.calls.append(request)
            return FakeResponse(landing if request.data is None else result_html)
    fake = FakeOpener()
    monkeypatch.setattr("maya_sawa.services.market_history_collector.urllib.request.build_opener", lambda *args: fake)
    monkeypatch.setattr("maya_sawa.services.market_history_collector.time.sleep", lambda _: None)
    result = MarketHistoryCollector._fetch_tdcc_history("https://tdcc.example/qryStock", date(2026, 7, 9), ["2330"])
    assert result["2330"]["trading_date"] == date(2026, 7, 9)
    assert len(fake.calls) == 2
    assert b"scaDate=20260709" in fake.calls[1].data
from datetime import date



def test_taifex_futures_csv_keeps_regular_session_and_delivery_month():
    from maya_sawa.services.market_history_collector import parse_taifex_daily_futures_csv

    csv_text = '''交易日期,契約,到期月份(週別),開盤價,最高價,最低價,收盤價,漲跌價,漲跌%,成交量,結算價,未沖銷契約數,最後最佳買價,最後最佳賣價,歷史最高價,歷史最低價,是否因訊息面暫停交易,交易時段,價差對單式委託成交量
2026/10/12,QFF,202610  ,2535,2560,2530,2550,-15,-0.58%,15653,2550,51049,2545,2550,2620,2356,,一般,,
2026/10/12,QFF,202610  ,2545,2555,2520,2525,-40,-1.56%,8124,-,-,2525,2535,2620,2356,,盤後,,
2026/10/12,QFF,202611  ,2545,2575,2540,2560,-15,-0.58%,5413,2560,16128,2560,2565,2635,2422,,一般,,'''
    rows = parse_taifex_daily_futures_csv(csv_text, {
        "QFFJ6": {"root": "QFF", "month": "202610", "name": "Mini TSMC Futures"}
    }, date(2026, 10, 12))
    assert rows == [{"code": "QFFJ6", "name": "Mini TSMC Futures", "values": {
        "open": 2535, "high": 2560, "low": 2530, "close": 2550, "change": -15,
        "volume_contracts": 15653, "settlement": 2550, "open_interest_contracts": 51049,
    }}]


def test_taifex_front_month_uses_third_wednesday_expiry():
    from maya_sawa.services.market_history_collector import _taifex_front_month

    assert _taifex_front_month(date(2026, 10, 20)) == "202610"
    assert _taifex_front_month(date(2026, 10, 22)) == "202611"


def test_taifex_futures_institutional_csv_maps_category_totals_and_participants():
    from maya_sawa.services.market_history_collector import parse_taifex_futures_institutional_csv

    document = '''日期,商品名稱,身份別,多方交易口數,多方交易契約金額(千元),空方交易口數,空方交易契約金額(千元),多空交易口數淨額,多空交易契約金額淨額(千元),多方未平倉口數,多方未平倉契約金額(千元),空方未平倉口數,空方未平倉契約金額(千元),多空未平倉口數淨額,多空未平倉契約金額淨額(千元)
2026/10/12,臺股期貨,自營商,5473,53837273,4806,47356229,667,6481044,4783,47255651,4636,45804198,147,1451453
2026/10/12,臺股期貨,投信,2063,20501204,1554,15404872,509,5096332,79560,785250462,2712,26764728,76848,758485734
2026/10/12,臺股期貨,外資及陸資,47775,469242877,47132,463058932,643,6183945,11899,117470052,94705,934899240,-82806,-817429188'''
    result = parse_taifex_futures_institutional_csv(document, date(2026, 10, 12))
    assert len(result) == 1
    assert result[0]["values"]["foreign_net_open_interest"] == -82806
    assert result[0]["values"]["trust_net_trade_contracts"] == 509
    assert result[0]["values"]["dealer_net_trade_contracts"] == 667
