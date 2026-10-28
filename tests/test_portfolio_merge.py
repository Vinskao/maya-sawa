import asyncio

from maya_sawa.api import market


def taiwan_portfolio():
    return {"cashBalance": 100000.0, "totalAssetsEstimated": 500000.0, "totalPnl": 2000.0, "leverageRatio": 1.2,
            "summaryFormulas": {"totalAssetsEstimated": "400,000 + 100,000"}, "valuationNote": "Taiwan", "positions": []}


def stub_sources(monkeypatch, binance_snapshot):
    recorded = {}

    async def shioaji_portfolio():
        return taiwan_portfolio()

    async def no_txf():
        return None

    async def binance():
        if isinstance(binance_snapshot, Exception):
            raise binance_snapshot
        return binance_snapshot

    monkeypatch.setenv("IBKR_ENABLED", "false")
    monkeypatch.setattr(market.shioaji_market_service, "get_portfolio", shioaji_portfolio)
    monkeypatch.setattr(market.shioaji_market_service, "get_taiex_futures_quote", no_txf)
    monkeypatch.setattr(market.market_dashboard_db, "record_portfolio", lambda merged, fixed: None)
    monkeypatch.setattr(market.portfolio_history_db, "record_taiwan", lambda portfolio: None)
    monkeypatch.setattr(market.portfolio_history_db, "record_if_due", lambda merged: recorded.update(merged=merged))
    monkeypatch.setattr(market.binance_account_service, "get_snapshot", binance)
    return recorded


SNAPSHOT = {"source": "Binance", "usdTwdRate": 32.0, "usdt": {"total": 1700.0}, "twd": {"total": 54400.0}, "positions": []}


def test_portfolio_folds_binance_into_totals_and_history(monkeypatch):
    recorded = stub_sources(monkeypatch, SNAPSHOT)
    merged = asyncio.run(market._portfolio_with_ibkr())
    assert merged["totalAssetsEstimated"] == 554400.0
    assert merged["regions"]["crypto"]["totalAssets"] == 54400.0
    assert merged["regions"]["taiwan"]["totalAssets"] == 500000.0
    assert recorded["merged"]["binance"]["usdt"]["total"] == 1700.0


def test_portfolio_without_binance_is_taiwan_only(monkeypatch):
    stub_sources(monkeypatch, None)
    merged = asyncio.run(market._portfolio_with_ibkr())
    assert merged["totalAssetsEstimated"] == 500000.0
    assert "crypto" not in merged["regions"] and "binance" not in merged


def test_binance_failure_never_breaks_the_portfolio(monkeypatch):
    stub_sources(monkeypatch, RuntimeError("database down"))
    merged = asyncio.run(market._portfolio_with_ibkr())
    assert merged["totalAssetsEstimated"] == 500000.0 and "binance" not in merged
