from maya_sawa.databases.market_dashboard_db import MarketDashboardDatabase, public_selection_from_portfolio


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
    assert [item["code"] for item in result] == ["TXFJ6", "2330", "2317", "2308", "2454", "2881", "9999"]
    # Labels only (no quantity, value or direction); market says which exchange the code belongs to.
    assert all(set(item) == {"code", "name", "productType", "market"} for item in result)
    assert {item["market"] for item in result} == {"TW"}


def test_incomplete_or_partial_snapshot_does_not_replace_the_previous_selection():
    assert public_selection_from_portfolio({"balanceAvailable": False, "positions": []}) is None
    assert public_selection_from_portfolio({"balanceAvailable": True, "accountErrors": {"futures": "unavailable"}, "positions": []}) is None
    assert public_selection_from_portfolio({"balanceAvailable": True, "positions": []}) is None


def test_successful_portfolio_snapshot_records_candidate_membership(monkeypatch):
    db = MarketDashboardDatabase.__new__(MarketDashboardDatabase)
    db.sessions = object()
    class Context:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, *_args, **_kwargs): pass

    class SessionFactory:
        def begin(self): return Context()

    db.sessions = SessionFactory()
    candidates = []
    monkeypatch.setattr(db, "record_candidates", lambda source, symbols: candidates.append((source, symbols)) or len(symbols))
    monkeypatch.setattr("maya_sawa.databases.market_dashboard_db.insert", lambda _model: type("Values", (), {
        "values": lambda self, **_kwargs: self,
        "on_conflict_do_update": lambda self, **_kwargs: self,
    })())
    portfolio = {"balanceAvailable": True, "fetchedAt": "2026-10-13T13:00:00+00:00", "positions": [
        {"code": "2330", "name": "TSMC", "productType": "stock", "marketValue": 100},
    ]}
    assert db.record_portfolio(portfolio)
    assert candidates[0][0] == "portfolio-auto"
    assert candidates[0][1][0]["code"] == "2330"


def test_overseas_holdings_keep_their_market_so_codes_do_not_collide_with_taiwan():
    portfolio = {
        "balanceAvailable": True, "fetchedAt": "2026-10-16T10:00:00+00:00", "usdTwdRate": 32.27,
        "positions": [{"code": "2330", "name": "TSMC", "productType": "stock", "marketValue": 900}],
        "ibkr": {"positions": [
            {"code": "6857", "name": "ADVANTEST", "assetClass": "STK", "currency": "JPY", "marketValueTwd": 800},
            {"code": "LITE", "name": "LUMENTUM", "assetClass": "STK", "currency": "USD", "marketValueTwd": 700},
            {"code": "000660", "name": "SK HYNIX", "assetClass": "STK", "currency": "KRW", "marketValueTwd": 600},
            {"code": "BOND1", "name": "Bond", "assetClass": "BOND", "currency": "USD", "marketValueTwd": 999},
        ]},
    }
    result = public_selection_from_portfolio(portfolio)
    assert [(item["code"], item["market"]) for item in result] == [("2330", "TW"), ("6857", "JP"), ("LITE", "US"), ("000660", "KR")]
    assert all("quantity" not in item and "marketValueTwd" not in item for item in result)


def test_dashboard_quotes_overseas_codes_from_ibkr_not_from_a_taiwan_stock_with_the_same_code(monkeypatch):
    import asyncio
    from maya_sawa.api import market
    auto = {"snapshotAt": "2026-10-16T10:00:00+00:00", "positions": [
        {"code": "2330", "name": "TSMC", "productType": "stock", "market": "TW"},
        {"code": "6857", "name": "ADVANTEST", "productType": "stock", "market": "JP"},
        {"code": "6524", "name": "KOHOKU", "productType": "stock"},  # stored before markets existed
    ]}
    asked = []

    async def shioaji_quotes(rows):
        asked.extend(row["code"] for row in rows)
        return [{"symbol": row["code"], "productType": "stock", "name": "Taiwan " + row["code"], "close": 91.0} for row in rows]

    async def ibkr_snapshot():
        return {"fetchedAt": "2026-10-16T10:00:00+00:00", "positions": [
            {"code": "6857", "name": "ADVANTEST", "assetClass": "STK", "currency": "JPY", "lastPrice": 24150.0},
            {"code": "6524", "name": "KOHOKU", "assetClass": "STK", "currency": "JPY", "lastPrice": 5350.8}]}

    async def no_txf():
        return None

    monkeypatch.setattr(market.market_dashboard_db, "latest_auto", lambda: auto)
    monkeypatch.setattr(market.market_dashboard_db, "custom_symbols", lambda: [])
    monkeypatch.setattr(market.shioaji_market_service, "get_dashboard_quotes", shioaji_quotes)
    monkeypatch.setattr(market.shioaji_market_service, "get_taiex_futures_quote", no_txf)
    monkeypatch.setattr(market.ibkr_market_service, "get_snapshot", ibkr_snapshot)
    monkeypatch.setattr(market, "attach_underlying", lambda *args, **kwargs: None)
    payload = asyncio.run(market.get_market_dashboard())
    rows = {row["code"]: row for row in payload["automatic"]["positions"]}
    assert asked == ["2330"]
    assert rows["6857"]["quote"]["close"] == 24150.0 and rows["6857"]["market"] == "JP"
    assert rows["6524"]["market"] == "JP" and rows["6524"]["quote"]["quoteSource"] == "Interactive Brokers CPAPI"
    # The position snapshot has no previous close: change and the day range are unknown, not zero.
    assert rows["6857"]["quote"]["change"] is None and rows["6857"]["quote"]["changePercent"] is None and rows["6857"]["quote"]["high"] is None
    assert rows["2330"]["market"] == "TW" and rows["2330"]["quote"]["close"] == 91.0


def test_taiwan_collectors_skip_overseas_holdings(monkeypatch):
    from maya_sawa.services import market_selection
    auto = {"snapshotAt": None, "positions": [
        {"code": "2330", "name": "TSMC", "productType": "stock", "market": "TW"},
        {"code": "6857", "name": "ADVANTEST", "productType": "stock", "market": "JP"},
        {"code": "LITE", "name": "LUMENTUM", "productType": "stock", "market": "US"}]}
    monkeypatch.setattr(market_selection.market_dashboard_db, "latest_auto", lambda: auto)
    monkeypatch.setattr(market_selection.market_dashboard_db, "custom_symbols", lambda: [])
    monkeypatch.setattr(market_selection.market_fundamentals_db, "quote_snapshots",
        lambda instruments: [{"productType": "stock", "symbol": "6857", "underlyingCode": "9999"}])
    assert market_selection.selected_stock_codes() == ["2330"]
    rows = {row["code"]: row for row in market_selection.current_selection()[1]}
    assert "underlyingCode" not in rows["6857"]  # a Taiwan quote for the same digits must not attach
