import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from maya_sawa.services.shioaji_market import (
    ReadOnlyShioajiClient,
    ShioajiCacheUnavailableError,
    ShioajiMarketService,
)


def test_nearest_txf_contract_ignores_expired_contracts():
    today = date.today()
    expired = SimpleNamespace(code="TXFOLD", delivery_date=today - timedelta(days=1))
    near = SimpleNamespace(code="TXFNEAR", delivery_date=today + timedelta(days=5))
    far = SimpleNamespace(code="TXFFAR", delivery_date=today + timedelta(days=35))
    api = SimpleNamespace(
        Contracts=SimpleNamespace(
            Futures=SimpleNamespace(TXF=[far, expired, near])
        )
    )

    selected = ShioajiMarketService._nearest_txf_contract(api)

    assert selected.code == "TXFNEAR"


def test_mini_tsmc_contract_prefers_qffr1():
    qffr1 = SimpleNamespace(code="QFFR1", underlying_code="2330")
    dated = SimpleNamespace(
        code="QFFF6",
        underlying_code="2330",
        delivery_date=date.today() + timedelta(days=5),
    )
    api = SimpleNamespace(
        Contracts=SimpleNamespace(
            Futures=SimpleNamespace(QFF=[dated, qffr1])
        )
    )

    selected = ShioajiMarketService._mini_tsmc_contract(api)

    assert selected.code == "QFFR1"


def test_position_payload_omits_account_identifiers():
    position = SimpleNamespace(
        code="QFFF6",
        direction=SimpleNamespace(value="Buy"),
        quantity=2,
        yd_quantity=1,
        price=1000,
        last_price=1010,
        pnl=2000,
        account_id="secret",
    )

    payload = ShioajiMarketService._position_payload(
        position, "futures", 202000
    )

    assert payload["marketValue"] == 202000
    assert payload["ydQuantity"] == 1
    assert payload["signedQuantity"] == 2
    assert "account_id" not in payload


def test_position_payload_signs_short_futures_quantity():
    position = SimpleNamespace(
        code="TXFF6",
        direction=SimpleNamespace(value="Sell"),
        quantity=3,
        yd_quantity=0,
        price=22000,
        last_price=21900,
        pnl=-3000,
    )

    payload = ShioajiMarketService._position_payload(position, "futures", 65700)

    assert payload["signedQuantity"] == -3
    assert payload["lastPrice"] == 21900


def test_stock_portfolio_uses_only_successful_stock_apis():
    balance = SimpleNamespace(acc_balance=100_000, date="2026-06-12")
    position = SimpleNamespace(
        code="2330",
        direction=SimpleNamespace(value="Buy"),
        quantity=1,
        yd_quantity=1,
        price=1000,
        last_price=1100,
        pnl=100_000,
    )
    api = SimpleNamespace(
        stock_account=SimpleNamespace(),
        Contracts=SimpleNamespace(
            Stocks={"2330": SimpleNamespace(name="台積電")}
        ),
        account_balance=lambda account: balance,
        list_stock_positions=lambda: [position],
    )

    payload = ShioajiMarketService._fetch_portfolio(api)

    assert payload["totalPositionExposure"] == 101_000
    assert payload["totalAssetsEstimated"] == 201_000
    assert payload["totalPnl"] == 100_000
    assert payload["positionCount"] == 1
    assert payload["positions"][0]["assetPercentage"] == 50.25
    assert payload["positions"][0]["name"] == "台積電"


def test_portfolio_includes_futures_summary_and_positions():
    balance = SimpleNamespace(acc_balance=100_000, date="2026-06-12")
    stock_position = SimpleNamespace(
        code="2330",
        direction=SimpleNamespace(value="Buy"),
        quantity=1,
        yd_quantity=1,
        price=1000,
        last_price=1100,
        pnl=100_000,
    )
    futures_position = SimpleNamespace(
        code="TXFF6",
        direction=SimpleNamespace(value="Sell"),
        quantity=2,
        price=22000,
        last_price=21950,
        pnl=5000,
    )
    margin = SimpleNamespace(
        equity=250000,
        equity_amount=255000,
        available_margin=180000,
        future_open_position=5000,
        maintenance_margin=90000,
        initial_margin=110000,
    )
    api = SimpleNamespace(
        stock_account=SimpleNamespace(),
        futopt_account=SimpleNamespace(),
        Contracts=SimpleNamespace(
            Stocks={"2330": SimpleNamespace(name="台積電")}
        ),
        account_balance=lambda account: balance,
        list_stock_positions=lambda: [stock_position],
        list_positions=lambda account: [futures_position],
        margin=lambda account: margin,
    )

    payload = ShioajiMarketService._fetch_portfolio(api)

    assert payload["futuresSummary"]["equity"] == 250000
    assert payload["futuresSummary"]["positionCount"] == 1
    assert payload["futuresPositions"][0]["signedQuantity"] == -2
    assert payload["positions"][1]["productType"] == "futures"


def test_public_account_error_omits_request_identity():
    error = RuntimeError(
        "request /PYAPI/PERSON_ID/IP_ADDRESS code: 406, detail: Account Not Acceptable."
    )

    assert ShioajiMarketService._public_account_error(error) == "Account Not Acceptable"


def test_format_timestamp_supports_nanoseconds():
    value = ShioajiMarketService._format_timestamp(1_700_000_000_000_000_000)

    assert value == "2023-11-14T22:13:20+08:00"


def test_format_timestamp_assumes_taipei_for_naive_datetime():
    value = ShioajiMarketService._format_timestamp(datetime(2026, 6, 12, 15, 28, 27, 435000))

    assert value == "2026-06-12T15:28:27.435000+08:00"


def test_usage_payload_converts_to_megabytes():
    usage = SimpleNamespace(
        connections=16,
        bytes=650_942_370,
        limit_bytes=2_147_483_648,
        remaining_bytes=1_496_541_278,
    )

    mb = 1024 * 1024
    assert round(usage.bytes / mb, 2) == 620.79


def test_get_cached_payload_returns_stale_cache_when_expired():
    service = ShioajiMarketService()
    stale_payload = {"symbol": "TXF", "close": 123}
    service._read_cached_payload = lambda key: stale_payload  # type: ignore[method-assign]
    result = asyncio.run(service._get_cached_payload("TXF"))

    assert result == stale_payload


def test_get_cached_payload_raises_when_cache_missing():
    service = ShioajiMarketService()
    service._read_cached_payload = lambda key: None  # type: ignore[method-assign]

    try:
        asyncio.run(service._get_cached_payload("TXF"))
    except ShioajiCacheUnavailableError as exc:
        assert "TXF" in str(exc)
    else:
        raise AssertionError("Expected cache miss to raise")


def test_reset_api_does_not_delete_redis_cache():
    service = ShioajiMarketService()
    deleted_keys = []
    service._redis.delete = lambda *keys: deleted_keys.extend(keys)  # type: ignore[method-assign]

    asyncio.run(service._reset_api())

    assert deleted_keys == []


def test_redis_cache_envelope_round_trip():
    service = ShioajiMarketService()
    stored: dict[str, str] = {}
    service._redis.set = lambda key, value: stored.__setitem__(key, value)  # type: ignore[method-assign]
    service._redis.get = lambda key: stored.get(key)  # type: ignore[method-assign]

    service._write_cached_payload("TXF", {"close": 123})

    assert service._read_cached_payload("TXF") == {"close": 123}
    assert "maya-sawa:market:txf" in stored


def test_read_only_client_does_not_expose_order_methods():
    api = SimpleNamespace(
        Contracts=SimpleNamespace(),
        stock_account=SimpleNamespace(),
        futopt_account=SimpleNamespace(),
        snapshots=lambda contracts: [],
        usage=lambda: None,
        account_balance=lambda account: None,
        list_positions=lambda account: [],
        logout=lambda: None,
        place_order=lambda contract, order: "must not be exposed",
        update_order=lambda trade: "must not be exposed",
        cancel_order=lambda trade: "must not be exposed",
    )

    client = ReadOnlyShioajiClient(api, share_unit="Share")

    assert not hasattr(client, "place_order")
    assert not hasattr(client, "update_order")
    assert not hasattr(client, "cancel_order")
