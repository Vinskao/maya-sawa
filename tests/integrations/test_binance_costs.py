import pytest

from maya_sawa.services.binance_costs import apply_cost_basis, average_cost, cost_events, tracked_pairs

# GET /api/v3/myTrades rows (Binance docs shape), BTCUSDT.
TRADES = [
    {"symbol": "BTCUSDT", "id": 1, "price": "60000", "qty": "0.010", "quoteQty": "600", "commission": "0.00001",
     "commissionAsset": "BTC", "time": 1700000000000, "isBuyer": True},
    {"symbol": "BTCUSDT", "id": 2, "price": "80000", "qty": "0.010", "quoteQty": "800", "commission": "0.8",
     "commissionAsset": "USDT", "time": 1710000000000, "isBuyer": True},
    {"symbol": "BTCUSDT", "id": 3, "price": "90000", "qty": "0.005", "quoteQty": "450", "commission": "0.45",
     "commissionAsset": "USDT", "time": 1720000000000, "isBuyer": False},
]
# GET /sapi/v1/convert/tradeFlow list rows.
CONVERTS = [
    {"orderId": 9, "orderStatus": "SUCCESS", "fromAsset": "USDT", "fromAmount": "300", "toAsset": "BTC",
     "toAmount": "0.005", "createTime": 1715000000000},
    {"orderId": 10, "orderStatus": "PROCESS", "fromAsset": "USDT", "fromAmount": "999", "toAsset": "BTC",
     "toAmount": "1", "createTime": 1716000000000},
    {"orderId": 11, "orderStatus": "SUCCESS", "fromAsset": "ETH", "fromAmount": "1", "toAsset": "BTC",
     "toAmount": "0.03", "createTime": 1717000000000},  # crypto-to-crypto: no USDT cost, skipped
]


def test_trades_and_stable_converts_become_time_ordered_events():
    events = cost_events('BTC', {'BTCUSDT': TRADES}, CONVERTS)
    assert [e['source'] for e in events] == ['trade', 'trade', 'convert', 'trade']
    assert events[0] == {'time': 1700000000000, 'side': 'buy', 'quantity': pytest.approx(0.00999), 'usdt': 600.0, 'source': 'trade'}
    assert events[1]['usdt'] == 800.8      # quote commission adds to the buy cost
    assert events[3] == {'time': 1720000000000, 'side': 'sell', 'quantity': 0.005, 'usdt': pytest.approx(449.55), 'source': 'trade'}
    assert events[2]['usdt'] == 300.0 and events[2]['quantity'] == 0.005


def test_moving_average_cost_and_realized_pnl():
    basis = average_cost(cost_events('BTC', {'BTCUSDT': TRADES}, CONVERTS))
    # Buys: 0.00999 for 600, 0.01 for 800.8, 0.005 for 300 -> 0.02499 for 1700.8
    # Sell 0.005 at avg 68059.22... -> proceeds 449.55
    avg_before = 1700.8 / 0.02499
    assert basis['quantity'] == pytest.approx(0.01999)
    assert basis['costUsdt'] == pytest.approx(1700.8 - avg_before * 0.005)
    assert basis['realizedPnlUsdt'] == pytest.approx(449.55 - avg_before * 0.005)
    assert basis['events'] == 4


def test_selling_more_than_tracked_never_goes_negative():
    events = [{'time': 1, 'side': 'sell', 'quantity': 1.0, 'usdt': 100.0, 'source': 'trade'},
              {'time': 2, 'side': 'buy', 'quantity': 2.0, 'usdt': 200.0, 'source': 'trade'}]
    basis = average_cost(events)
    assert basis['quantity'] == 2.0 and basis['costUsdt'] == 200.0
    assert basis['realizedPnlUsdt'] == 0.0  # coins that came from deposits have no known cost


def test_tracked_pairs_use_stable_quotes_that_exist():
    assert tracked_pairs(['BTC', 'ETH', 'USDT', 'DOGE'], {'BTCUSDT', 'BTCFDUSD', 'ETHUSDT', 'ETHBTC'}) == ['BTCFDUSD', 'BTCUSDT', 'ETHUSDT']


def snapshot():
    return {'usdTwdRate': 32.0, 'twd': {'total': 54400.0}, 'usdt': {'total': 1700.0}, 'positions': [
        {'asset': 'BTC', 'wallet': 'Spot', 'quantity': 0.015, 'priceUsdt': 80000.0, 'valueUsdt': 1200.0, 'valueTwd': 38400.0},
        {'asset': 'BTC', 'wallet': 'Earn', 'quantity': 0.01, 'priceUsdt': 80000.0, 'valueUsdt': 800.0, 'valueTwd': 25600.0},
        {'asset': 'USDT', 'wallet': 'Funding', 'quantity': 50.0, 'priceUsdt': 1.0, 'valueUsdt': 50.0, 'valueTwd': 1600.0}]}


def test_cost_basis_covers_only_the_tracked_quantity():
    bases = {'BTC': {'quantity': 0.02, 'costUsdt': 1400.0, 'realizedPnlUsdt': 10.0, 'events': 3}}
    result = apply_cost_basis(snapshot(), bases, '2026-10-28T16:00:00+00:00')
    btc = result['costBasis']['BTC']
    assert btc['heldQuantity'] == pytest.approx(0.025)
    assert btc['coveredQuantity'] == pytest.approx(0.02) and btc['uncoveredQuantity'] == pytest.approx(0.005)
    assert btc['averageCostUsdt'] == 70000.0
    assert btc['unrealizedPnlUsdt'] == pytest.approx((80000 - 70000) * 0.02)
    assert result['usdt']['unrealizedPnl'] == pytest.approx(200.0)
    assert result['twd']['unrealizedPnl'] == pytest.approx(6400.0)
    assert result['usdt']['realizedPnl'] == 10.0
    assert 'USDT' not in result['costBasis']  # stablecoins are the unit, not a position with P/L


def test_more_tracked_than_held_caps_cost_at_the_held_quantity():
    bases = {'BTC': {'quantity': 0.05, 'costUsdt': 3500.0, 'realizedPnlUsdt': 0.0, 'events': 2}}
    btc = apply_cost_basis(snapshot(), bases, 'now')['costBasis']['BTC']
    assert btc['coveredQuantity'] == pytest.approx(0.025) and btc['uncoveredQuantity'] == 0
    assert btc['unrealizedPnlUsdt'] == pytest.approx((80000 - 70000) * 0.025)


def test_assets_without_history_are_unknown_not_zero():
    result = apply_cost_basis(snapshot(), {}, 'now')
    assert result['costBasis']['BTC']['averageCostUsdt'] is None
    assert result['costBasis']['BTC']['unrealizedPnlUsdt'] is None
    assert result['usdt']['unrealizedPnl'] is None and result['twd']['unrealizedPnl'] is None
