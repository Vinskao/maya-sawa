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
    assert "外資連續 5 日買超" in s["signals"]
    assert "400 張以上大戶持股週增 0.50 pp" in s["signals"]

    markdown = brief_markdown({"generatedAt": "2026-10-14T08:00:00+08:00", "holdingsSnapshotAt": None,
                               "instruments": [{"code": "2330", "name": "台積電", "productType": "stock",
                                                "group": "automatic", "spotCode": "2330"}],
                               "stocks": {"2330": s}, "notes": []})
    assert "## 2330 台積電" in markdown
    assert "外資買賣超" in markdown and "毛利率" in markdown
    assert "成本" in markdown  # only in the privacy disclaimer line
    assert "quantity" not in markdown.lower()
