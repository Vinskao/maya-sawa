"""Single place that turns the dashboard selection (holdings snapshot + custom picks) into stock codes.

Stock futures are always resolved to their underlying stock, because every chart, chip and fundamentals
dataset is keyed by the stock. Positions do not store the underlying code; quotes do, so this uses the
persisted dashboard quote snapshots (and live quotes when a caller already has them).
"""
from __future__ import annotations

from typing import Any

from ..databases.market_dashboard_db import market_dashboard_db
from ..databases.market_fundamentals_db import market_fundamentals_db


def is_taiwan(item: dict) -> bool:
    """Rows without a market predate overseas holdings and are Taiwan instruments."""
    return str(item.get("market") or "TW").upper() == "TW"


def stock_code(item: dict) -> str | None:
    # Taiwan collectors (TWSE/TPEx/TDCC/MOPS) only: an overseas code such as Tokyo 6857 is not Taiwan 6857.
    if not is_taiwan(item):
        return None
    code = str(item.get("underlyingCode") or (item.get("code") if item.get("productType") == "stock" else "") or "").upper()
    return code if code.isdigit() and len(code) == 4 else None


def attach_underlying(instruments: list[dict], live_quotes: list[dict] | None = None) -> list[dict]:
    quotes: dict[tuple, dict] = {}
    for row in market_fundamentals_db.quote_snapshots(instruments) + list(live_quotes or []):
        quotes[(row.get("productType"), str(row.get("symbol", "")).upper())] = row  # live quotes win
    for item in instruments:
        if not is_taiwan(item):
            continue
        quote = quotes.get((item.get("productType"), str(item.get("code", "")).upper())) or {}
        if not item.get("underlyingCode") and quote.get("underlyingCode"):
            item["underlyingCode"] = quote["underlyingCode"]
    return instruments


def current_selection() -> tuple[dict[str, Any], list[dict]]:
    auto = market_dashboard_db.latest_auto()
    instruments, seen = [], set()
    for group, rows in (("automatic", auto.get("positions", [])), ("custom", [*market_dashboard_db.custom_symbols(), *market_dashboard_db.watch_symbols()])):
        for item in rows:
            key = (item.get("productType"), str(item.get("code", "")).upper())
            if key not in seen:
                seen.add(key)
                instruments.append({**item, "group": group})
    return auto, attach_underlying(instruments)


def selected_stock_codes() -> list[str]:
    return sorted({code for item in current_selection()[1] if (code := stock_code(item))})
