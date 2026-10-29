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
    monkeypatch.setenv("BINANCE_SYMBOLS", "")  # no crypto rows, so no database read
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


def _crypto_collector(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from maya_sawa.databases.ibkr_research_db import IbkrResearchDatabase
    from maya_sawa.services import binance_market
    db = IbkrResearchDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))
    collector = binance_market.BinanceMarketCollector(db=db)
    monkeypatch.setattr(binance_market, "binance_market_collector", collector)
    monkeypatch.setenv("BINANCE_SYMBOLS", "BTC,ETH")
    db.save("BTC", "CRYPTO", 0, "quote", {"close": 80724.72, "change": 508.08, "changePercent": 0.633,
                                          "sourceUpdatedAt": 1793192840013}, period="2026-10-28T13")
    db.save("BTC", "CRYPTO", 0, "daily", {"date": "2026-10-28", "open": 80909.77, "high": 81823.0,
                                          "low": 80621.22, "close": 80724.72, "volume": 5652.61}, period="2026-10-28")
    return collector


def test_binance_coins_join_the_holdings_by_value_including_usdt():
    """2026-10-29: the owner wants every coin they hold, USDT included, in the holdings list (largest first), not a separate quote box."""
    portfolio = {
        "balanceAvailable": True, "fetchedAt": "2026-10-29T03:00:00+00:00",
        "positions": [{"code": "2330", "name": "TSMC", "productType": "stock", "marketValue": 900},
                      {"code": "3008", "name": "LARGAN", "productType": "stock", "marketValue": 100}],
        "binance": {"positions": [
            {"asset": "ETH", "name": "Ethereum", "wallet": "Spot", "quantity": 0.1, "valueTwd": 200},
            {"asset": "ETH", "name": "Ethereum", "wallet": "Earn", "quantity": 0.1, "valueTwd": 200},  # one row per coin
            {"asset": "BTC", "name": "Bitcoin", "wallet": "Spot", "quantity": 0.001, "valueTwd": 50},
            {"asset": "USDT", "name": "USDT", "wallet": "Funding", "quantity": 5000, "valueTwd": 160000},  # USDT is a holding too
            {"asset": "DUST", "name": "DUST", "wallet": "Spot", "quantity": 1, "valueTwd": 0},
        ]},
    }
    result = public_selection_from_portfolio(portfolio)
    assert [(item["code"], item["market"], item["productType"]) for item in result] == [
        ("USDT", "CRYPTO", "crypto"), ("2330", "TW", "stock"), ("ETH", "CRYPTO", "crypto"), ("3008", "TW", "stock"), ("BTC", "CRYPTO", "crypto")]
    assert all(set(item) == {"code", "name", "productType", "market"} for item in result)


def test_held_coins_are_quoted_from_binance_and_there_is_no_separate_crypto_box(monkeypatch):
    import asyncio
    from maya_sawa.api import market
    _crypto_collector(monkeypatch)

    async def nothing(*_args):
        return []

    async def no_snapshot():
        return {}

    monkeypatch.setattr(market.market_dashboard_db, "latest_auto", lambda: {"snapshotAt": None, "positions": [
        {"code": "BTC", "name": "Bitcoin", "productType": "crypto", "market": "CRYPTO"},
        {"code": "SOL", "name": "Solana", "productType": "crypto", "market": "CRYPTO"}]})
    monkeypatch.setattr(market.market_dashboard_db, "custom_symbols", lambda: [])
    monkeypatch.setattr(market.market_dashboard_db, "watch_symbols", lambda: [])
    monkeypatch.setattr(market.shioaji_market_service, "get_dashboard_quotes", nothing)
    monkeypatch.setattr(market.shioaji_market_service, "get_taiex_futures_quote", no_snapshot)
    monkeypatch.setattr(market.ibkr_market_service, "get_snapshot", no_snapshot)
    monkeypatch.setattr(market, "attach_underlying", lambda *args, **kwargs: None)
    payload = asyncio.run(market.get_market_dashboard())
    assert "crypto" not in payload
    rows = {row["code"]: row for row in payload["automatic"]["positions"]}
    assert rows["BTC"]["market"] == "CRYPTO" and rows["BTC"]["productType"] == "crypto"
    assert rows["BTC"]["quote"]["close"] == 80724.72 and rows["BTC"]["quote"]["currency"] == "USDT"
    assert rows["SOL"]["quote"] is None  # not collected yet: no quote, never a zero price


def test_overseas_endpoint_serves_crypto_from_binance_and_rejects_unknown_symbols(monkeypatch):
    import asyncio
    import pytest
    from fastapi import HTTPException
    from maya_sawa.api import market
    _crypto_collector(monkeypatch)
    result = asyncio.run(market.get_overseas_research("btc", "crypto"))
    assert result["source"] == "Binance" and result["daily"][0]["close"] == 80724.72
    with pytest.raises(HTTPException) as error:
        asyncio.run(market.get_overseas_research("DOGE", "CRYPTO"))
    assert error.value.status_code == 404


def test_a_held_coin_outside_binance_symbols_is_collected_and_charted(monkeypatch):
    from maya_sawa.services import binance_market
    monkeypatch.setenv("BINANCE_SYMBOLS", "BTC")
    monkeypatch.setattr("maya_sawa.databases.market_dashboard_db.market_dashboard_db.latest_auto", lambda: {"snapshotAt": None, "positions": [
        {"code": "2330", "name": "TSMC", "productType": "stock", "market": "TW"},
        {"code": "SOL", "name": "Solana", "productType": "crypto", "market": "CRYPTO"},
        {"code": "BTC", "name": "Bitcoin", "productType": "crypto", "market": "CRYPTO"},
        {"code": "USDT", "name": "USDT", "productType": "crypto", "market": "CRYPTO"}]})
    assert binance_market.tracked_symbols() == ["BTC", "SOL"]  # USDT is the quote asset: there is no USDT/USDT pair


def test_crypto_instruments_can_carry_an_ai_analysis():
    from maya_sawa.api.market import analysis_target
    assert analysis_target("btc-crypto", "crypto") == ("crypto", "BTC-CRYPTO")


def test_instrument_names_skip_codes_shared_by_two_companies(monkeypatch):
    from maya_sawa.api import market
    monkeypatch.setattr(market.market_dashboard_db, "latest_auto", lambda: {"snapshotAt": None, "positions": [
        {"code": "3008", "name": "大立光", "productType": "stock", "market": "TW"},
        {"code": "6857", "name": "ADVANTEST", "productType": "stock", "market": "JP"}]})
    monkeypatch.setattr(market.market_dashboard_db, "custom_symbols", lambda: [
        {"code": "6857", "name": "宏碁智醫", "productType": "stock"}, {"code": "TXF", "name": "TXF", "productType": "futures"}])
    monkeypatch.setattr(market.market_dashboard_db, "watch_symbols", lambda: [{"code": "3008", "name": "大立光"}])
    assert market.instrument_names() == {"3008": "大立光"}
