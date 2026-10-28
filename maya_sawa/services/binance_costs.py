"""Binance cost basis and P/L from trade history (phase 3).

Moving-average cost per asset from spot trades quoted in stablecoins
(GET /api/v3/myTrades) and stablecoin Convert orders
(GET /sapi/v1/convert/tradeFlow). Coins with no known purchase price, such as
deposits from elsewhere, Earn rewards, fiat card purchases and
crypto-to-crypto converts, stay "uncovered": they are valued but never treated
as zero cost. Commission paid in a third asset (BNB) is not added to cost.
"""
from __future__ import annotations

import math

STABLE_QUOTES = ('USDT', 'FDUSD', 'USDC')
_EPSILON = 1e-12


def _number(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


def tracked_pairs(assets, existing_symbols) -> list[str]:
    """Stablecoin-quoted spot pairs to read trades from, for the held non-stable assets."""
    pairs = set()
    for asset in assets:
        if asset in STABLE_QUOTES:
            continue
        for quote in STABLE_QUOTES:
            if asset + quote in existing_symbols:
                pairs.add(asset + quote)
    return sorted(pairs)


def cost_events(asset: str, trades_by_pair: dict[str, list[dict]], converts: list[dict]) -> list[dict]:
    events = []
    for pair, trades in trades_by_pair.items():
        if not pair.startswith(asset) or pair[len(asset):] not in STABLE_QUOTES:
            continue
        quote = pair[len(asset):]
        for row in trades:
            quantity, usdt = _number(row.get('qty')), _number(row.get('quoteQty'))
            commission, fee_asset = _number(row.get('commission')), row.get('commissionAsset')
            if quantity <= 0 or usdt <= 0:
                continue
            buy = bool(row.get('isBuyer'))
            if fee_asset == asset:
                quantity -= commission if buy else 0.0
                usdt -= 0.0 if buy else commission * _number(row.get('price'))
            elif fee_asset == quote:
                usdt += commission if buy else -commission
            events.append({'time': int(_number(row.get('time'))), 'side': 'buy' if buy else 'sell',
                           'quantity': quantity, 'usdt': usdt, 'source': 'trade'})
    for row in converts:
        if row.get('orderStatus') != 'SUCCESS':
            continue
        source, target = row.get('fromAsset'), row.get('toAsset')
        if target == asset and source in STABLE_QUOTES:
            side, quantity, usdt = 'buy', _number(row.get('toAmount')), _number(row.get('fromAmount'))
        elif source == asset and target in STABLE_QUOTES:
            side, quantity, usdt = 'sell', _number(row.get('fromAmount')), _number(row.get('toAmount'))
        else:
            continue
        if quantity > 0 and usdt > 0:
            events.append({'time': int(_number(row.get('createTime'))), 'side': side,
                           'quantity': quantity, 'usdt': usdt, 'source': 'convert'})
    return sorted(events, key=lambda event: event['time'])


def average_cost(events: list[dict]) -> dict:
    quantity = cost = realized = 0.0
    for event in events:
        if event['side'] == 'buy':
            quantity += event['quantity']
            cost += event['usdt']
            continue
        # Only the tracked part of a sale has a known cost; the rest came from deposits or rewards.
        sold = min(event['quantity'], quantity)
        if sold <= _EPSILON:
            continue
        average = cost / quantity
        realized += event['usdt'] * sold / event['quantity'] - average * sold
        quantity -= sold
        cost -= average * sold
        if quantity <= _EPSILON:
            quantity = cost = 0.0
    return {'quantity': quantity, 'costUsdt': cost, 'realizedPnlUsdt': realized, 'events': len(events)}


def apply_cost_basis(snapshot: dict, bases: dict[str, dict], computed_at: str) -> dict:
    """Attach per-asset cost and P/L (USDT and NT$) to a balance snapshot. Unknown stays None."""
    rate = snapshot['usdTwdRate']
    held: dict[str, dict] = {}
    for position in snapshot.get('positions', []):
        if position['asset'] in STABLE_QUOTES:
            continue
        entry = held.setdefault(position['asset'], {'quantity': 0.0, 'price': position['priceUsdt']})
        entry['quantity'] += position['quantity']
    cost_basis, unrealized, realized, known = {}, 0.0, 0.0, False
    for asset, entry in sorted(held.items()):
        basis = bases.get(asset)
        tracked = basis['quantity'] if basis else 0.0
        covered = min(tracked, entry['quantity'])
        average = basis['costUsdt'] / tracked if basis and tracked > _EPSILON else None
        pnl = (entry['price'] - average) * covered if average is not None else None
        cost_basis[asset] = {
            'heldQuantity': round(entry['quantity'], 10), 'coveredQuantity': round(covered, 10),
            'uncoveredQuantity': round(max(entry['quantity'] - covered, 0.0), 10),
            'averageCostUsdt': round(average, 8) if average is not None else None,
            'priceUsdt': entry['price'],
            'unrealizedPnlUsdt': round(pnl, 2) if pnl is not None else None,
            'unrealizedPnlTwd': round(pnl * rate, 2) if pnl is not None else None,
            'realizedPnlUsdt': round(basis['realizedPnlUsdt'], 2) if basis else None,
            'events': basis['events'] if basis else 0}
        if pnl is not None:
            known = True
            unrealized += pnl
        if basis:
            realized += basis['realizedPnlUsdt']
    snapshot['costBasis'] = cost_basis
    snapshot['costBasisAt'] = computed_at
    snapshot['usdt'] = {**snapshot['usdt'], 'unrealizedPnl': round(unrealized, 2) if known else None,
                        'realizedPnl': round(realized, 2) if bases else None}
    snapshot['twd'] = {**snapshot['twd'], 'unrealizedPnl': round(unrealized * rate, 2) if known else None}
    return snapshot
