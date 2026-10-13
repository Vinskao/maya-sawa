from maya_sawa.databases.market_dashboard_db import public_selection_from_portfolio


def test_selection_uses_stock_market_value_and_absolute_futures_exposure_without_private_fields():
    portfolio = {
        "balanceAvailable": True,
        "fetchedAt": "2026-10-13T13:00:00+00:00",
        "positions": [
            {"code": "2330", "name": "TSMC", "productType": "stock", "allocationValue": 800, "quantity": 99},
            {"code": "TXFJ6", "name": "TX Futures", "productType": "futures", "allocationValue": -1200, "direction": "Sell"},
            {"code": "2317", "name": "Hon Hai", "productType": "stock", "marketValue": 700},
            {"code": "2308", "name": "Delta", "productType": "stock", "marketValue": 600},
            {"code": "2454", "name": "MediaTek", "productType": "stock", "marketValue": 500},
            {"code": "2881", "name": "Fubon", "productType": "stock", "marketValue": 400},
            {"code": "9999", "name": "Below cutoff", "productType": "stock", "marketValue": 1},
        ],
    }
    result = public_selection_from_portfolio(portfolio)
    assert [item["code"] for item in result] == ["TXFJ6", "2330", "2317", "2308", "2454"]
    assert all(set(item) == {"code", "name", "productType"} for item in result)


def test_incomplete_or_partial_snapshot_does_not_replace_the_previous_selection():
    assert public_selection_from_portfolio({"balanceAvailable": False, "positions": []}) is None
    assert public_selection_from_portfolio({"balanceAvailable": True, "accountErrors": {"futures": "unavailable"}, "positions": []}) is None
    assert public_selection_from_portfolio({"balanceAvailable": True, "positions": []}) is None
