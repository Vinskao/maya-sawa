"""TAIEX 乖離率 (bias): how far the close sits above or below its simple moving average, in percent.

2026-11-18: drawn on the macro page for the 20 (月線), 60 (季線) and 240 (年線) session averages. Derived from the stored
TW_TAIEX closes, so it needs no extra request; the first (window - 1) sessions have no value.
"""
BIAS_WINDOWS = {20: "TW_TAIEX_BIAS_20", 60: "TW_TAIEX_BIAS_60", 240: "TW_TAIEX_BIAS_240"}


def bias_series(closes: dict[str, float], window: int) -> dict[str, str]:
    """{period: bias percent, 2 decimals} for every session that has `window` closes up to and including it."""
    periods = sorted(period for period, value in closes.items() if value and value > 0)
    out: dict[str, str] = {}
    total = 0.0
    for index, period in enumerate(periods):
        total += closes[period]
        if index >= window: total -= closes[periods[index - window]]
        if index >= window - 1:
            average = total / window
            out[period] = f"{(closes[period] / average - 1) * 100:.2f}"
    return out
