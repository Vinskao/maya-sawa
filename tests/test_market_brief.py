from maya_sawa.services.market_brief import brief_markdown, summarize_stock


def _day(date, close, foreign, margin):
    return {"date": date, "sources": {
        "twse:daily-price": {"close": close},
        "twse:institutional": {"foreign_net_shares": foreign, "investment_trust_net_shares": 0},
        "twse:margin-balance": {"margin_balance_lots": margin, "short_balance_lots": margin / 10},
    }}


def _week(date, large, retail):
    return {"date": date, "sources": {"tdcc:distribution-history": {"tiers": [
        {"tier": "1-999", "percent": retail}, {"tier": "1,000,001以上", "percent": large},
        {"tier": "合計", "percent": 100},
    ]}}}


def test_summary_reports_streaks_holder_shifts_and_no_account_values():
    daily = [_day(f"2026-10-{d:02d}", 100 + d, -5000 if d < 8 else 3000, 1000 + d * 20) for d in range(1, 13)]
    ownership = [_week("2026-10-02", 80.0, 3.0), _week("2026-10-09", 80.5, 2.9)]
    metrics = {"monthly": [{"period": "2026-09", "yoyPercent": 31.4, "momPercent": -0.6, "ytdYoyPercent": 40.1}],
               "quarterly": [{"period": "2026Q2", "grossMargin": 67.7, "grossMarginQoQ": 1.47, "grossMarginYoY": 9.1}]}
    s = summarize_stock("2330", daily, ownership, metrics)
    assert s["institutional"]["foreign"]["streakDays"] == 5
    assert s["institutional"]["foreign"]["net5dLots"] == 15
    assert s["tdcc"]["largeHolderChange1wPp"] == 0.5
    assert s["tdcc"]["retailChange1wPp"] == -0.1
    assert "外資連續 5 日買超" in [signal["zh"] for signal in s["signals"]]
    assert "Foreign investors net bought 5 days in a row" in [signal["en"] for signal in s["signals"]]
    assert "400 張以上大戶持股週增 0.50 pp" in [signal["zh"] for signal in s["signals"]]

    markdown = brief_markdown({"generatedAt": "2026-10-14T08:00:00+08:00", "holdingsSnapshotAt": None,
                               "instruments": [{"code": "2330", "name": "台積電", "productType": "stock",
                                                "group": "automatic", "spotCode": "2330"}],
                               "stocks": {"2330": s}, "notes": []})
    assert "## 2330 台積電" in markdown
    assert "外資買賣超" in markdown and "毛利率" in markdown
    assert "成本" in markdown  # only in the privacy disclaimer line
    assert "quantity" not in markdown.lower()


def test_brief_follows_the_live_selection_and_maps_futures_to_their_stock(monkeypatch):
    from maya_sawa.services import market_brief, market_selection

    selection = {"custom": [{"code": "2337", "name": "旺宏", "productType": "stock"}]}
    monkeypatch.setattr(market_selection.market_dashboard_db, "latest_auto", lambda: {
        "snapshotAt": "2026-10-14", "positions": [{"code": "QFFJ6", "name": "小型台積電期貨", "productType": "futures"}]})
    monkeypatch.setattr(market_selection.market_dashboard_db, "custom_symbols", lambda: selection["custom"])
    monkeypatch.setattr(market_selection.market_fundamentals_db, "quote_snapshots", lambda instruments: [
        {"productType": "futures", "symbol": "QFFJ6", "underlyingCode": "2330"}])
    monkeypatch.setattr(market_brief.market_history_db, "history", lambda *a, **k: {"points": []})
    monkeypatch.setattr(market_brief.MarketFundamentalsService, "_finmind_history", staticmethod(lambda code: {}))

    brief = market_brief.build_brief()
    assert set(brief["stocks"]) == {"2330", "2337"}
    assert brief["stocks"]["2330"]["via"] == [{"code": "QFFJ6", "productType": "futures", "group": "automatic"}]
    assert brief["stocks"]["2337"]["name"] == "旺宏"

    before = market_brief.selection_fingerprint(market_brief.current_selection()[1])
    selection["custom"] = []  # user removes 旺宏
    after = market_brief.selection_fingerprint(market_brief.current_selection()[1])
    assert before != after
    assert set(market_brief.build_brief()["stocks"]) == {"2330"}


def test_futures_holding_gets_fundamentals_from_official_cache_and_queues_finmind(monkeypatch):
    from maya_sawa.services import market_brief, market_selection

    monkeypatch.setattr(market_selection.market_dashboard_db, "latest_auto", lambda: {
        "snapshotAt": "2026-10-15", "positions": [{"code": "UHFJ6", "name": "小型奇鋐期貨10", "productType": "futures"}]})
    monkeypatch.setattr(market_selection.market_dashboard_db, "custom_symbols", lambda: [])
    monkeypatch.setattr(market_selection.market_fundamentals_db, "quote_snapshots", lambda instruments: [
        {"productType": "futures", "symbol": "UHFJ6", "underlyingCode": "3017"}])
    monkeypatch.setattr(market_brief.market_history_db, "history", lambda *a, **k: {"points": []})
    monkeypatch.setattr(market_brief.MarketFundamentalsService, "_finmind_history", staticmethod(lambda code: {}))
    monkeypatch.setattr(market_brief.market_fundamentals_service, "cached_official", lambda code: (
        [{"period": "2026-09", "revenue": 100, "yoyPercent": 42.5, "momPercent": 3.1}],
        [{"period": "2026Q2", "singleQuarter": {"revenue": 200, "grossProfit": 50, "operatingIncome": 30, "netIncome": 20},
          "epsReported": None}]))

    brief = market_brief.build_brief()
    fundamentals = brief["stocks"]["3017"]["fundamentals"]
    assert fundamentals["latestMonth"]["yoyPercent"] == 42.5
    assert fundamentals["latestQuarter"]["grossMargin"] == 25.0
    assert brief["collecting"] == {"history": ["3017"], "fundamentals": ["3017"]}
    assert "3017 的部分歷史資料仍在背景蒐集中" in market_brief.brief_markdown(brief)


def test_release_window_looks_back_to_the_previous_weekday():
    from datetime import datetime
    from maya_sawa.services.market_brief import TZ, release_window_start
    assert release_window_start(datetime(2026, 10, 15, 8, tzinfo=TZ)).isoformat() == "2026-10-14"  # Thu -> Wed
    assert release_window_start(datetime(2026, 10, 19, 8, tzinfo=TZ)).isoformat() == "2026-10-16"  # Mon -> Fri


def test_recent_releases_flag_new_revenue_statements_and_tdcc_week(monkeypatch):
    from datetime import date
    from maya_sawa.services import market_brief
    monkeypatch.setattr(market_brief.market_fundamentals_db, "releases_seen_since", lambda code, since: [
        {"dataset": "TaiwanStockFinancialStatements", "period": "2026-09-30", "firstSeenAt": "2026-10-14T03:00:00+00:00"}])
    metrics = {"monthly": [{"period": "2026-08", "publishedAt": "2026-09-10"}, {"period": "2026-09", "publishedAt": "2026-10-14"}]}
    ownership = [_week("2026-10-09", 80.0, 3.0)]
    releases = market_brief.recent_releases("2330", metrics, ownership, date(2026, 10, 14), date(2026, 10, 15))
    labels = [(r["label"]["zh"], r["period"], r["basis"]) for r in releases]
    assert ("月營收", "2026-09", "published") in labels
    assert ("季財報（損益表）", "2026Q3", "firstSeen") in labels
    assert not any(r["dataset"] == "tdcc" for r in releases)            # 10-09 week is older than the window
    assert all(r["period"] != "2026-08" for r in releases)


def test_finmind_month_revenue_keeps_publication_date():
    from maya_sawa.services.market_fundamentals import _finmind_records, build_fundamental_metrics
    records = _finmind_records("TaiwanStockMonthRevenue", [
        {"revenue_year": 2026, "revenue_month": 9, "revenue": 500, "create_time": "2026-10-08"}])
    assert {"period": "2026-09", "item": "publishedAt", "value": "2026-10-08", "unit": ""} in records
    month = build_fundamental_metrics([], [], {"TaiwanStockMonthRevenue": records})["monthly"][-1]
    assert month["publishedAt"] == "2026-10-08"


def test_markdown_is_available_in_english():
    from maya_sawa.services.market_brief import brief_markdown
    brief = {"generatedAt": "2026-10-15T08:00:00+08:00", "holdingsSnapshotAt": None,
             "instruments": [{"code": "QFFJ6", "name": "小型台積電期貨", "productType": "futures", "group": "automatic", "spotCode": "2330"}],
             "stocks": {"2330": {"code": "2330", "name": "台積電", "asOf": "2026-10-14", "via": [{"code": "QFFJ6", "productType": "futures", "group": "automatic"}],
                                 "signals": [{"zh": "外資連續 3 日買超", "en": "Foreign investors net bought 3 days in a row"}],
                                 "recentReleases": [{"dataset": "TaiwanStockMonthRevenue", "label": {"zh": "月營收", "en": "Monthly revenue"},
                                                     "period": "2026-09", "date": "2026-10-14", "basis": "published"}]}},
             "notes": []}
    english = brief_markdown(brief, "en")
    assert "Holdings chip summary" in english and "Monthly revenue 2026-09 (10-14 published)" in english
    assert "Foreign investors net bought 3 days in a row" in english
    assert "## 2330 台積電" in english  # the stock's own name, not the futures contract's
    # Only names and the link to the Chinese version stay Chinese.
    lines = [line for line in english.splitlines() if "中文版" not in line]
    body = " ".join(lines).replace("小型台積電期貨", "").replace("台積電", "")
    assert not any(0x4E00 <= ord(ch) <= 0x9FFF for ch in body)
    assert "月營收 2026-09（10-14 公布）" in brief_markdown(brief)


def test_brief_carries_the_latest_inventory_quarter():
    metrics = {"quarterly": [{"period": "2026Q2", "grossMargin": 79.5}],
               "balance": [{"period": "2026Q2", "inventoryDays": 116.03, "inventoryYoY": -39.4, "inventoryVsRevenueYoY": -723.6, "debtRatio": 20.1}]}
    inventory = summarize_stock("2408", [], [], metrics)["fundamentals"]["latestInventory"]
    assert inventory == {"period": "2026Q2", "inventoryDays": 116.03, "inventoryDaysQoQ": None, "inventoryDaysYoY": None,
                         "inventoryQoQ": None, "inventoryYoY": -39.4, "inventoryVsRevenueYoY": -723.6}


# 2026-10-27: holdings that come from IBKR (Japan, Korea, US) were missing from the chip summary. They have no TWSE chip
# data, so the summary shows what is stored for them: price, technicals and the latest quarter's growth and margins.
import json
from pathlib import Path

from maya_sawa.services.market_brief import summarize_overseas


def overseas(code):
    return json.loads((Path(__file__).parent / "fixtures" / f"overseas_brief_{code}.json").read_text(encoding="utf-8"))


def test_japanese_holding_uses_operating_margin_when_the_filing_has_no_gross_profit():
    s = summarize_overseas("6857", "JP", overseas("6857"), name="ADVANTEST CORP")
    assert (s["code"], s["market"], s["name"], s["asOf"], s["currency"]) == ("6857", "JP", "ADVANTEST CORP", "2026-10-26", "JPY")
    assert s["price"] == {"close": 33330.0, "change1dPct": 7.27, "change5dPct": -1.59, "change20dPct": -1.19}
    assert s["technical"] == {"rsi14": 44.56, "vsMa20Pct": -8.92, "vsMa60Pct": -3.0}
    quarter = s["fundamentals"]["latestQuarter"]
    assert (quarter["period"], quarter["revenueYoYPercent"], quarter["grossMarginPercent"]) == ("2026-06-30", 39.31, None)
    assert (quarter["operatingMarginPercent"], quarter["operatingMarginYoYPp"]) == (51.7, 4.71)  # 51.7018 vs 46.9914 a year earlier
    assert [signal["zh"] for signal in s["signals"]] == ["收盤低於 20 日均線 8.92%", "2026-06-30 季營收年增 +39.31%"]


def test_us_holding_compares_with_the_same_quarter_a_year_earlier_and_skips_quarters_without_revenue():
    s = summarize_overseas("LITE", "US", overseas("LITE"), name="Lumentum")
    assert s["currency"] == "USD" and s["price"]["change20dPct"] == -13.12
    quarter = s["fundamentals"]["latestQuarter"]
    assert (quarter["period"], quarter["revenueYoYPercent"]) == ("2026-03-28", 90.12)  # 808.4M vs 425.2M of 2025-03-29
    assert (quarter["grossMarginPercent"], quarter["grossMarginYoYPp"]) == (44.16, 15.35)  # 2025-06-28 has no revenue and is not a base
    assert "Close is 14.20% below the 20-day average" in [signal["en"] for signal in s["signals"]]


def test_a_holding_with_no_stored_data_is_listed_without_numbers():
    s = summarize_overseas("000660", "KR", {"daily": [], "technical": None, "financials": {"quarterly": []}}, name="SK Hynix")
    assert s["asOf"] is None and s.get("price") is None and s["signals"] == []


def test_markdown_lists_overseas_holdings_with_the_chip_data_they_do_not_have():
    jp = summarize_overseas("6857", "JP", overseas("6857"), name="ADVANTEST CORP")
    brief = {"generatedAt": "2026-10-27T08:00:00+08:00", "holdingsSnapshotAt": None, "stocks": {}, "notes": [],
             "instruments": [{"code": "6857", "name": "ADVANTEST CORP", "productType": "stock", "group": "automatic", "spotCode": None}],
             "overseas": {"6857-JP": jp}}
    markdown = brief_markdown(brief)
    assert "## 6857 ADVANTEST CORP（日本）" in markdown
    assert "收盤 / 1日 / 5日 / 20日" in markdown and "33,330.00 / +7.27% / -1.59% / -1.19%" in markdown
    assert "RSI(14)" in markdown and "營益率" in markdown and "季營收年增" in markdown
    assert "沒有外資、投信、融資與集保籌碼資料" in markdown
