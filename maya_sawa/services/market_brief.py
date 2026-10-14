"""Public, agent-readable chip summary for the dashboard's selected holdings.

Uses only data the public /market/dashboard already exposes (instrument codes) plus public market data
(prices, institutional flows, margin, TDCC distribution, fundamentals ratios). It never includes account
values, quantities, cost or P/L.
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..databases.market_dashboard_db import market_dashboard_db
from ..databases.market_history_db import market_history_db
from .market_fundamentals import MarketFundamentalsService, build_fundamental_metrics

TZ = ZoneInfo("Asia/Taipei")
PRICE = ("twse:daily-price", "tpex:daily-price")
INSTITUTIONAL = ("twse:institutional", "tpex:institutional")
MARGIN = ("twse:margin-balance", "tpex:margin-balance")
HOLDING = ("twse:foreign-holding", "tpex:foreign-holding")
TDCC = "tdcc:distribution-history"
LARGE_HOLDER_MIN_SHARES = 400_001  # TDCC "大戶" convention: 400 lots and above
RETAIL_MAX_SHARES = 10_000         # 10 lots and below


def _value(point: dict, sources: tuple[str, ...], field: str) -> float | None:
    for source in sources:
        value = point["sources"].get(source, {}).get(field)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _series(points: list[dict], sources: tuple[str, ...], field: str) -> list[float]:
    return [v for v in (_value(p, sources, field) for p in points) if v is not None]


def _pct(current: float | None, base: float | None) -> float | None:
    return None if current is None or not base else round((current / base - 1) * 100, 2)


def _lots(shares: float) -> int:
    return round(shares / 1000)


def _streak(values: list[float]) -> int:
    """Consecutive same-sign days ending at the latest value; positive = buying streak."""
    if not values or values[-1] == 0:
        return 0
    sign = 1 if values[-1] > 0 else -1
    count = 0
    for value in reversed(values):
        if value * sign <= 0:
            break
        count += 1
    return sign * count


def _tier_lower_bound(tier: str) -> int | None:
    match = re.match(r"\s*([\d,]+)", str(tier))
    return int(match.group(1).replace(",", "")) if match else None


def _tier_share(tiers: list[dict], predicate) -> float | None:
    picked = [float(t["percent"]) for t in tiers if isinstance(t.get("percent"), (int, float))
              and (bound := _tier_lower_bound(t.get("tier", ""))) is not None and predicate(bound)]
    return round(sum(picked), 2) if picked else None


def summarize_stock(code: str, daily: list[dict], ownership: list[dict], metrics: dict) -> dict[str, Any]:
    closes = _series(daily, PRICE, "close")
    price_dates = [p["date"] for p in daily if _value(p, PRICE, "close") is not None]
    result: dict[str, Any] = {"code": code, "asOf": price_dates[-1] if price_dates else None}
    if closes:
        result["price"] = {"close": closes[-1], "change1dPct": _pct(closes[-1], closes[-2] if len(closes) > 1 else None),
                           "change5dPct": _pct(closes[-1], closes[-6] if len(closes) > 5 else None),
                           "change20dPct": _pct(closes[-1], closes[-21] if len(closes) > 20 else None)}
    flows = {}
    for key, field in (("foreign", "foreign_net_shares"), ("trust", "investment_trust_net_shares"), ("dealer", "dealer_net_shares")):
        values = _series(daily, INSTITUTIONAL, field)
        if values:
            flows[key] = {"net1dLots": _lots(values[-1]), "net5dLots": _lots(sum(values[-5:])),
                          "net20dLots": _lots(sum(values[-20:])), "streakDays": _streak(values)}
    if flows:
        result["institutional"] = flows
    margin = _series(daily, MARGIN, "margin_balance_lots")
    short = _series(daily, MARGIN, "short_balance_lots")
    if margin:
        result["margin"] = {"marginBalanceChange5dPct": _pct(margin[-1], margin[-6] if len(margin) > 5 else None),
                            "shortBalanceChange5dPct": _pct(short[-1], short[-6] if len(short) > 5 else None) if short else None,
                            "shortToMarginPct": round(short[-1] / margin[-1] * 100, 2) if short and margin[-1] else None}
    holding = _series(ownership, HOLDING, "foreign_holding_percent")
    if holding:
        result["foreignHolding"] = {"percent": holding[-1],
                                    "change20dPp": round(holding[-1] - holding[-21], 2) if len(holding) > 20 else None}
    weeks = [(p["date"], p["sources"][TDCC]["tiers"]) for p in ownership if isinstance(p["sources"].get(TDCC, {}).get("tiers"), list)]
    if weeks:
        large = [_tier_share(t, lambda b: b >= LARGE_HOLDER_MIN_SHARES) for _, t in weeks]
        retail = [_tier_share(t, lambda b: b <= RETAIL_MAX_SHARES) for _, t in weeks]

        def delta(series: list, back: int) -> float | None:
            return round(series[-1] - series[-1 - back], 2) if len(series) > back and series[-1] is not None and series[-1 - back] is not None else None
        result["tdcc"] = {"week": weeks[-1][0], "largeHolderPercent": large[-1], "largeHolderChange1wPp": delta(large, 1),
                          "largeHolderChange4wPp": delta(large, 4), "retailPercent": retail[-1], "retailChange1wPp": delta(retail, 1)}
    monthly, quarterly = metrics.get("monthly") or [], metrics.get("quarterly") or []
    if monthly or quarterly:
        result["fundamentals"] = {"latestMonth": monthly[-1] if monthly else None, "latestQuarter": quarterly[-1] if quarterly else None}
    result["signals"] = _signals(result)
    return result


def _signals(s: dict) -> list[str]:
    """Plain-language facts derived from the numbers above; no buy/sell advice."""
    out = []
    for key, label in (("foreign", "外資"), ("trust", "投信")):
        flow = s.get("institutional", {}).get(key)
        if flow and abs(flow["streakDays"]) >= 3:
            out.append(f"{label}連續 {abs(flow['streakDays'])} 日{'買超' if flow['streakDays'] > 0 else '賣超'}")
    tdcc = s.get("tdcc", {})
    if tdcc.get("largeHolderChange1wPp") is not None and abs(tdcc["largeHolderChange1wPp"]) >= 0.2:
        out.append(f"400 張以上大戶持股週{'增' if tdcc['largeHolderChange1wPp'] > 0 else '減'} {abs(tdcc['largeHolderChange1wPp']):.2f} pp")
    margin = s.get("margin", {})
    if margin.get("marginBalanceChange5dPct") is not None and abs(margin["marginBalanceChange5dPct"]) >= 5:
        out.append(f"融資餘額 5 日{'增' if margin['marginBalanceChange5dPct'] > 0 else '減'} {abs(margin['marginBalanceChange5dPct']):.1f}%")
    month = (s.get("fundamentals") or {}).get("latestMonth") or {}
    if isinstance(month.get("yoyPercent"), (int, float)):
        out.append(f"{month['period']} 營收年增 {month['yoyPercent']:+.1f}%")
    quarter = (s.get("fundamentals") or {}).get("latestQuarter") or {}
    if isinstance(quarter.get("grossMarginQoQ"), (int, float)):
        out.append(f"{quarter['period']} 毛利率季{'增' if quarter['grossMarginQoQ'] >= 0 else '減'} {abs(quarter['grossMarginQoQ']):.2f} pp")
    return out


def _spot_code(item: dict) -> str | None:
    code = str(item.get("underlyingCode") or (item.get("code") if item.get("productType") == "stock" else "") or "").upper()
    return code if code.isdigit() and len(code) == 4 else None


def build_brief() -> dict[str, Any]:
    auto = market_dashboard_db.latest_auto()
    instruments, seen = [], set()
    for group, rows in (("automatic", auto.get("positions", [])), ("custom", market_dashboard_db.custom_symbols())):
        for item in rows:
            key = (item.get("productType"), str(item.get("code", "")).upper())
            if key not in seen:
                seen.add(key)
                instruments.append({**item, "group": group})
    today = datetime.now(TZ).date()
    stocks: dict[str, dict] = {}
    for item in instruments:
        code = _spot_code(item)
        if not code or code in stocks:
            continue
        daily = market_history_db.history(code, today - timedelta(days=45), today,
                                          sources=[*PRICE, *INSTITUTIONAL, *MARGIN])["points"]
        ownership = market_history_db.history(code, today - timedelta(days=60), today,
                                              sources=[*HOLDING, TDCC])["points"]
        metrics = build_fundamental_metrics([], [], MarketFundamentalsService._finmind_history(code))
        stocks[code] = summarize_stock(code, daily, ownership, metrics)
    return {
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "holdingsSnapshotAt": auto.get("snapshotAt"),
        "instruments": [{"code": item.get("code"), "name": item.get("name"), "productType": item.get("productType"),
                         "group": item["group"], "spotCode": _spot_code(item)} for item in instruments],
        "stocks": stocks,
        "notes": ["Holdings list only; no quantities, cost, P/L or account values.",
                  "Lots = 1,000 shares. pp = percentage points. TDCC large holders = 400 lots and above; retail = 10 lots and below.",
                  "Futures are summarised through their underlying stock."],
    }


def _fmt(value: Any, suffix: str = "", signed: bool = False, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:+,.{digits}f}{suffix}" if signed else f"{value:,.{digits}f}{suffix}"


def brief_markdown(brief: dict) -> str:
    lines = ["# TY Multiverse · 持股籌碼摘要", "",
             f"- 產生時間：{brief['generatedAt']}（台北時間）",
             f"- 持股清單快照：{brief.get('holdingsSnapshotAt') or '—'}",
             "- 只列持有標的代號，不含張數、成本、損益或帳戶金額。", ""]
    names = {i["spotCode"]: i for i in brief["instruments"] if i.get("spotCode")}
    lines += ["## 標的", ""]
    for item in brief["instruments"]:
        spot = f"（現貨 {item['spotCode']}）" if item.get("spotCode") and item["spotCode"] != str(item["code"]).upper() else ""
        lines.append(f"- {item['code']} {item.get('name') or ''} · {item['productType']} · {'自動前五大' if item['group'] == 'automatic' else '自選'}{spot}")
    for code, s in brief["stocks"].items():
        name = names.get(code, {}).get("name") or ""
        lines += ["", f"## {code} {name}".rstrip(), "", f"資料日：{s.get('asOf') or '—'}", ""]
        if s.get("signals"):
            lines += ["重點：" + "；".join(s["signals"]), ""]
        lines += ["| 指標 | 數值 |", "|---|---|"]
        price = s.get("price") or {}
        if price:
            lines.append(f"| 收盤 / 1日 / 5日 / 20日 | {_fmt(price.get('close'))} / {_fmt(price.get('change1dPct'), '%', True)} / {_fmt(price.get('change5dPct'), '%', True)} / {_fmt(price.get('change20dPct'), '%', True)} |")
        for key, label in (("foreign", "外資"), ("trust", "投信"), ("dealer", "自營商")):
            flow = (s.get("institutional") or {}).get(key)
            if flow:
                streak = f"連{'買' if flow['streakDays'] > 0 else '賣'} {abs(flow['streakDays'])} 日" if flow["streakDays"] else "—"
                lines.append(f"| {label}買賣超 1日 / 5日 / 20日（張） | {flow['net1dLots']:+,} / {flow['net5dLots']:+,} / {flow['net20dLots']:+,} · {streak} |")
        margin = s.get("margin") or {}
        if margin:
            lines.append(f"| 融資 / 融券餘額 5日變化 · 券資比 | {_fmt(margin.get('marginBalanceChange5dPct'), '%', True)} / {_fmt(margin.get('shortBalanceChange5dPct'), '%', True)} · {_fmt(margin.get('shortToMarginPct'), '%')} |")
        holding = s.get("foreignHolding") or {}
        if holding:
            lines.append(f"| 外資持股比例 · 20日變化 | {_fmt(holding.get('percent'), '%')} · {_fmt(holding.get('change20dPp'), ' pp', True)} |")
        tdcc = s.get("tdcc") or {}
        if tdcc:
            lines.append(f"| 集保 400 張以上大戶（{tdcc['week']}） · 週 / 4週變化 | {_fmt(tdcc.get('largeHolderPercent'), '%')} · {_fmt(tdcc.get('largeHolderChange1wPp'), ' pp', True)} / {_fmt(tdcc.get('largeHolderChange4wPp'), ' pp', True)} |")
            lines.append(f"| 集保 10 張以下散戶 · 週變化 | {_fmt(tdcc.get('retailPercent'), '%')} · {_fmt(tdcc.get('retailChange1wPp'), ' pp', True)} |")
        fundamentals = s.get("fundamentals") or {}
        month, quarter = fundamentals.get("latestMonth") or {}, fundamentals.get("latestQuarter") or {}
        if month:
            lines.append(f"| 月營收 {month['period']} 年增 / 月增 / 累計年增 | {_fmt(month.get('yoyPercent'), '%', True)} / {_fmt(month.get('momPercent'), '%', True)} / {_fmt(month.get('ytdYoyPercent'), '%', True)} |")
        if quarter:
            for key, label in (("grossMargin", "毛利率"), ("operatingMargin", "營益率"), ("netMargin", "淨利率")):
                lines.append(f"| {quarter['period']} {label} · 季 / 年變化 | {_fmt(quarter.get(key), '%')} · {_fmt(quarter.get(key + 'QoQ'), ' pp', True)} / {_fmt(quarter.get(key + 'YoY'), ' pp', True)} |")
            lines.append(f"| {quarter['period']} EPS 年增 | {_fmt(quarter.get('epsYoY'), '%', True)} |")
    lines += ["", "## 定義", ""] + [f"- {note}" for note in brief["notes"]]
    lines += ["- 此摘要僅陳述公開市場資料，非投資建議。", "- JSON 版本：/tymultiverse/brief.json"]
    return "\n".join(lines) + "\n"


class MarketBriefService:
    TTL_SECONDS = 300

    def __init__(self) -> None:
        self._cached: tuple[float, dict] | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> dict:
        if self._cached and time.monotonic() - self._cached[0] < self.TTL_SECONDS:
            return self._cached[1]
        async with self._lock:
            if self._cached and time.monotonic() - self._cached[0] < self.TTL_SECONDS:
                return self._cached[1]
            brief = await asyncio.to_thread(build_brief)
            self._cached = (time.monotonic(), brief)
            return brief


market_brief_service = MarketBriefService()
