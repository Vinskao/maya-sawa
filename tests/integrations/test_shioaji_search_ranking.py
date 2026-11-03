from types import SimpleNamespace

from maya_sawa.services.shioaji_market import ShioajiMarketService, _is_warrant


def _stock(code, name):
    return SimpleNamespace(code=code, name=name, security_type="STK")


def test_warrants_are_recognised_by_code_range_and_name():
    assert _is_warrant("040629", "創意統一5A購03")
    assert _is_warrant("04618T", "創意中信63售03")
    assert _is_warrant("712345", "某某元大購01")
    assert not _is_warrant("3443", "創意")
    assert not _is_warrant("00878", "國泰永續高股息")
    assert not _is_warrant("00631L", "元大台灣50正2")


def test_name_search_puts_the_common_stock_first_and_drops_warrants(monkeypatch):
    contracts = [_stock("040629", "創意統一5A購03"), _stock("04618T", "創意中信63售03"),
                 _stock("3443", "創意"), _stock("00999", "創意概念ETF")]
    monkeypatch.setattr(ShioajiMarketService, "_iter_contracts", staticmethod(lambda _stocks: contracts))
    api = SimpleNamespace(Contracts=SimpleNamespace(Stocks=object()))
    results = ShioajiMarketService._search_contracts(api, "創意", "stock")
    assert [row["code"] for row in results] == ["3443", "00999"]


def test_dashboard_quotes_fall_back_per_instrument_to_saved_snapshot_then_daily_close(monkeypatch):
    import asyncio
    from maya_sawa.services import shioaji_market
    from maya_sawa.databases import market_fundamentals_db as fundamentals_module, market_history_db as history_module

    service = shioaji_market.ShioajiMarketService.__new__(shioaji_market.ShioajiMarketService)
    instruments = [{"code": "QFFJ6", "productType": "futures"}, {"code": "3081", "productType": "stock"},
                   {"code": "UHFJ6", "productType": "futures"}]
    # Redis holds only an off-session row with close=0 for QFFJ6: it must not hide the saved price.
    monkeypatch.setattr(service, "_read_cached_payload", lambda key: [
        {"symbol": "QFFJ6", "productType": "futures", "close": 0}], raising=False)
    monkeypatch.setattr(fundamentals_module.market_fundamentals_db, "quote_snapshots", lambda items: [
        {"symbol": code, "productType": kind, "close": price, "change": -5, "changePercent": -0.2}
        for code, kind, price in (("QFFJ6", "futures", 2490.0), ("3081", "stock", 2880.0))
        if any(i["code"] == code for i in items)])
    monkeypatch.setattr(history_module.market_history_db, "history", lambda code, start, end, sources=None: {"points": [
        {"date": "2026-10-13", "name": code, "sources": {"taifex:daily-futures-price": {"close": 3300.0}}},
        {"date": "2026-10-14", "name": code, "sources": {"taifex:daily-futures-price": {"close": 3315.0}}},
    ] if code == "UHFJ6" else []})

    quotes = {row["symbol"]: row for row in asyncio.run(service.get_dashboard_quotes(instruments))}
    assert quotes["QFFJ6"]["close"] == 2490.0 and quotes["QFFJ6"]["quoteSource"] == "snapshot"
    assert quotes["3081"]["quoteSource"] == "snapshot"
    assert quotes["UHFJ6"]["close"] == 3315.0 and quotes["UHFJ6"]["quoteSource"] == "dailyClose"
    assert quotes["UHFJ6"]["change"] == 15.0
