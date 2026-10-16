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
from ..databases.market_fundamentals_db import market_fundamentals_db
from ..databases.market_history_db import market_history_db
from .market_fundamentals import MarketFundamentalsService, _quarter_label, build_fundamental_metrics, market_fundamentals_service
from .market_selection import current_selection, stock_code
from .shioaji_market import shioaji_market_service

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


def summarize_stock(code: str, daily: list[dict], ownership: list[dict], metrics: dict,
                    quote: dict[str, Any] | None = None) -> dict[str, Any]:
    closes = _series(daily, PRICE, "close")
    price_dates = [p["date"] for p in daily if _value(p, PRICE, "close") is not None]
    result: dict[str, Any] = {"code": code, "asOf": price_dates[-1] if price_dates else None}
    if closes:
        result["price"] = {"close": closes[-1], "change1dPct": _pct(closes[-1], closes[-2] if len(closes) > 1 else None),
                           "change5dPct": _pct(closes[-1], closes[-6] if len(closes) > 5 else None),
                           "change20dPct": _pct(closes[-1], closes[-21] if len(closes) > 20 else None)}
    quote_source = (quote or {}).get("quoteSource")
    if (quote and quote_source in {"live", "snapshot"}
            and isinstance(quote.get("close"), (int, float)) and quote["close"] > 0):
        # The Shioaji snapshot is the latest-price authority. Keep the official daily
        # history only as the baseline for multi-session returns.
        quote_date = str(quote.get("timestamp") or "")[:10]
        prior_closes = [_value(point, PRICE, "close") for point in daily
                        if quote_date and point.get("date", "") < quote_date
                        and _value(point, PRICE, "close") is not None]
        if not prior_closes:
            prior_closes = closes
        result["price"] = {
            "close": float(quote["close"]),
            "change1dPct": quote.get("changePercent") if isinstance(quote.get("changePercent"), (int, float)) else None,
            "change5dPct": _pct(float(quote["close"]), prior_closes[-5] if len(prior_closes) >= 5 else None),
            "change20dPct": _pct(float(quote["close"]), prior_closes[-20] if len(prior_closes) >= 20 else None),
            "quoteSource": quote_source,
            "timestamp": quote.get("timestamp"),
            "fetchedAt": quote.get("fetchedAt"),
        }
        if quote_date:
            result["asOf"] = quote_date
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


def _signals(s: dict) -> list[dict[str, str]]:
    """Plain-language facts derived from the numbers above, in both languages; no buy/sell advice."""
    out = []
    for key, zh, en in (("foreign", "外資", "Foreign investors"), ("trust", "投信", "Investment trusts")):
        flow = s.get("institutional", {}).get(key)
        if flow and abs(flow["streakDays"]) >= 3:
            days, buying = abs(flow["streakDays"]), flow["streakDays"] > 0
            out.append({"zh": f"{zh}連續 {days} 日{'買超' if buying else '賣超'}",
                        "en": f"{en} net {'bought' if buying else 'sold'} {days} days in a row"})
    tdcc = s.get("tdcc", {})
    change = tdcc.get("largeHolderChange1wPp")
    if change is not None and abs(change) >= 0.2:
        out.append({"zh": f"400 張以上大戶持股週{'增' if change > 0 else '減'} {abs(change):.2f} pp",
                    "en": f"Holders of 400+ lots {'up' if change > 0 else 'down'} {abs(change):.2f} pp this week"})
    margin_change = (s.get("margin") or {}).get("marginBalanceChange5dPct")
    if margin_change is not None and abs(margin_change) >= 5:
        out.append({"zh": f"融資餘額 5 日{'增' if margin_change > 0 else '減'} {abs(margin_change):.1f}%",
                    "en": f"Margin balance {'up' if margin_change > 0 else 'down'} {abs(margin_change):.1f}% over 5 days"})
    month = (s.get("fundamentals") or {}).get("latestMonth") or {}
    if isinstance(month.get("yoyPercent"), (int, float)):
        out.append({"zh": f"{month['period']} 營收年增 {month['yoyPercent']:+.1f}%",
                    "en": f"{month['period']} revenue {month['yoyPercent']:+.1f}% YoY"})
    quarter = (s.get("fundamentals") or {}).get("latestQuarter") or {}
    if isinstance(quarter.get("grossMarginQoQ"), (int, float)):
        q = quarter["grossMarginQoQ"]
        out.append({"zh": f"{quarter['period']} 毛利率季{'增' if q >= 0 else '減'} {abs(q):.2f} pp",
                    "en": f"{quarter['period']} gross margin {'up' if q >= 0 else 'down'} {abs(q):.2f} pp QoQ"})
    return out


_spot_code = stock_code


RELEASE_LABELS = {
    "TaiwanStockMonthRevenue": {"zh": "月營收", "en": "Monthly revenue"},
    "TaiwanStockFinancialStatements": {"zh": "季財報（損益表）", "en": "Quarterly income statement"},
    "TaiwanStockBalanceSheet": {"zh": "季財報（資產負債表）", "en": "Quarterly balance sheet"},
    "TaiwanStockCashFlowsStatement": {"zh": "季財報（現金流量表）", "en": "Quarterly cash flow statement"},
    "tdcc": {"zh": "集保股權分散表", "en": "TDCC shareholding distribution"},
}


def release_window_start(now: datetime | None = None):
    """Start of "前一天": the previous weekday (Monday looks back to Friday, covering weekend releases)."""
    today = (now or datetime.now(TZ)).date()
    start = today - timedelta(days=1)
    while start.weekday() >= 5:
        start -= timedelta(days=1)
    return start


def recent_releases(code: str, metrics: dict, ownership: list[dict], since, today) -> list[dict]:
    """Low-frequency data published since the previous weekday. Daily chips update every day, so are not flagged."""
    releases: dict[tuple[str, str], dict] = {}
    for month in metrics.get("monthly") or []:
        published = month.get("publishedAt")
        if published and since.isoformat() <= published[:10] <= today.isoformat():
            releases[("TaiwanStockMonthRevenue", month["period"])] = {"date": published[:10], "basis": "published"}
    since_dt = datetime.combine(since, datetime.min.time(), TZ)
    for row in market_fundamentals_db.releases_seen_since(code, since_dt):
        # Sources give no filing date for statements; the day this site first saw the period stands in for it.
        key = (row["dataset"], _quarter_label(row["period"]) if row["dataset"] != "TaiwanStockMonthRevenue" else row["period"])
        if key not in releases:
            seen = datetime.fromisoformat(row["firstSeenAt"]).astimezone(TZ).date().isoformat()
            releases[key] = {"date": seen, "basis": "firstSeen"}
    weeks = [p["date"] for p in ownership if isinstance(p["sources"].get(TDCC, {}).get("tiers"), list)]
    if weeks and since.isoformat() <= weeks[-1] <= today.isoformat():
        releases[("tdcc", weeks[-1])] = {"date": weeks[-1], "basis": "dataDate"}
    return [{"dataset": dataset, "label": RELEASE_LABELS.get(dataset, {"zh": dataset, "en": dataset}), "period": period, **info}
            for (dataset, period), info in sorted(releases.items(), key=lambda item: item[1]["date"], reverse=True)]


def selection_fingerprint(instruments: list[dict]) -> tuple:
    return tuple(sorted((i["group"], i.get("productType"), str(i.get("code", "")).upper(), _spot_code(i) or "") for i in instruments))


def build_brief(selection: tuple[dict[str, Any], list[dict]] | None = None,
                quotes: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    auto, instruments = selection or current_selection()
    today = datetime.now(TZ).date()
    stocks: dict[str, dict] = {}
    missing_history, missing_fundamentals = [], []
    for item in instruments:
        code = _spot_code(item)
        if not code or code in stocks:
            continue
        daily = market_history_db.history(code, today - timedelta(days=45), today,
                                          sources=[*PRICE, *INSTITUTIONAL, *MARGIN])["points"]
        ownership = market_history_db.history(code, today - timedelta(days=60), today,
                                              sources=[*HOLDING, TDCC])["points"]
        history = MarketFundamentalsService._finmind_history(code)
        # FinMind history may not be collected yet for a newly held stock; the official TWSE feeds already in
        # memory still give the latest month's YoY/MoM and the latest quarter's margins.
        monthly, income = market_fundamentals_service.cached_official(code)
        metrics = build_fundamental_metrics(monthly, income, history)
        stocks[code] = summarize_stock(code, daily, ownership, metrics, (quotes or {}).get(code))
        # The stock's own name (e.g. 台積電), not the futures contract that led to it (小型台積電期貨).
        stock_names = [p.get("name") for p in daily + ownership if p.get("name") and p.get("name") != code]
        own = next((item.get("name") for item in instruments if item.get("productType") == "stock" and str(item.get("code", "")).upper() == code), None)
        stocks[code]["name"] = own or (stock_names[-1] if stock_names else None)
        stocks[code]["recentReleases"] = recent_releases(code, metrics, ownership, release_window_start(), today)
        if not daily:
            missing_history.append(code)
        if not history.get("TaiwanStockFinancialStatements") or not history.get("TaiwanStockMonthRevenue"):
            missing_fundamentals.append(code)
    for item in instruments:
        code = _spot_code(item)
        if code in stocks:
            stocks[code].setdefault("via", []).append({"code": item.get("code"), "productType": item.get("productType"), "group": item["group"]})
    return {
        "generatedAt": datetime.now(TZ).isoformat(timespec="seconds"),
        "holdingsSnapshotAt": auto.get("snapshotAt"),
        "instruments": [{"code": item.get("code"), "name": item.get("name"), "productType": item.get("productType"),
                         "group": item["group"], "spotCode": _spot_code(item)} for item in instruments],
        "stocks": stocks,
        "collecting": {"history": missing_history, "fundamentals": missing_fundamentals},
        "notes": ["Holdings list only; no quantities, cost, P/L or account values.",
                  "Lots = 1,000 shares. pp = percentage points. TDCC large holders = 400 lots and above; retail = 10 lots and below.",
                  "Futures are summarised through their underlying stock."],
    }


def _fmt(value: Any, suffix: str = "", signed: bool = False, digits: int = 2) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    return f"{value:+,.{digits}f}{suffix}" if signed else f"{value:,.{digits}f}{suffix}"


def _release_text(release: dict, lang: str = "zh") -> str:
    when = {"zh": {"published": "公布", "firstSeen": "本站取得", "dataDate": "資料日"},
            "en": {"published": "published", "firstSeen": "first seen here", "dataDate": "data date"}}[lang].get(release.get("basis"), "")
    open_, close = ("（", "）") if lang == "zh" else (" (", ")")
    return f"{release['label'][lang]} {release['period']}{open_}{release['date'][5:]} {when}{close}"


def brief_markdown(brief: dict, lang: str = "zh") -> str:
    """Markdown digest for AI agents; `lang` is "zh" (default) or "en"."""
    zh = lang != "en"
    lang = "zh" if zh else "en"

    def t(zh_text: str, en_text: str) -> str:
        return zh_text if zh else en_text
    sep = "、" if zh else ", "
    lines = [t("# TY Multiverse · 持股籌碼摘要", "# TY Multiverse · Holdings chip summary"), "",
             f"- {t('產生時間', 'Generated')}: {brief['generatedAt']} ({t('台北時間', 'Taipei time')})",
             f"- {t('持股清單快照', 'Holdings snapshot')}: {brief.get('holdingsSnapshotAt') or '—'}",
             f"- {t('只列持有標的代號，不含張數、成本、損益或帳戶金額。', 'Instrument codes only; no quantities, cost, P/L or account values.')}",
             f"- {t('English version', '中文版 (Chinese)')}: /tymultiverse/brief.md{'?lang=en' if zh else ''}", ""]
    held_stock_names = {str(i["code"]).upper(): i.get("name") for i in brief["instruments"] if i.get("productType") == "stock"}
    names = {code: {"name": s.get("name") or held_stock_names.get(code) or ""} for code, s in brief["stocks"].items()}
    fresh = [f"{code} {names.get(code, {}).get('name') or ''}".strip() for code, s in brief["stocks"].items() if s.get("recentReleases")]
    if fresh:
        lines += [f"**🆕 {t('前一交易日起有新公布資料的標的', 'New data published since the previous trading day')}: {sep.join(fresh)}** "
                  f"{t('（細節見各標的段落）', '(details under each stock)')}", ""]
    lines += [f"## {t('標的', 'Instruments')}", ""]
    for item in brief["instruments"]:
        spot = (f" ({t('現股', 'stock')} {item['spotCode']})"
                if item.get("spotCode") and item["spotCode"] != str(item["code"]).upper() else "")
        kind = t("股票", "stock") if item["productType"] == "stock" else t("期貨", "futures")
        group = t("持有", "held") if item["group"] == "automatic" else t("自選", "watchlist")
        lines.append(f"- {item['code']} {item.get('name') or ''} · {kind} · {group}{spot}")
    for code, s in brief["stocks"].items():
        name = names.get(code, {}).get("name") or ""
        via = sep.join(f"{t('持有', 'held') if v['group'] == 'automatic' else t('自選', 'watchlist')}"
                       f"{' ' + str(v['code']) + ' ' + t('期貨', 'futures') if v['productType'] == 'futures' else ''}" for v in s.get("via", []))
        lines += ["", f"## {code} {name}".rstrip(), "",
                  f"{t('來源', 'From')}: {via or '—'} · {t('資料日', 'As of')}: {s.get('asOf') or '—'}", ""]
        if s.get("recentReleases"):
            lines += [f"**🆕 {t('前一交易日起有新公布資料', 'Newly published')}:** " + ("；" if zh else "; ").join(_release_text(r, lang) for r in s["recentReleases"]), ""]
        if s.get("signals"):
            lines += [f"{t('重點', 'Highlights')}: " + ("；" if zh else "; ").join(signal[lang] for signal in s["signals"]), ""]
        lines += [f"| {t('指標', 'Metric')} | {t('數值', 'Value')} |", "|---|---|"]
        price = s.get("price") or {}
        if price:
            price_label = "現價 / 1日 / 5日 / 20日" if price.get("quoteSource") != "dailyClose" else "收盤 / 1日 / 5日 / 20日"
            source_label = "Shioaji" if price.get("quoteSource") in {"live", "snapshot"} else (price.get("quoteSource") or "日線")
            quote_time = price.get("timestamp") or price.get("fetchedAt") or s.get("asOf") or "—"
            lines.append(f"| {t(price_label, 'Price / 1d / 5d / 20d')} | {_fmt(price.get('close'))} / {_fmt(price.get('change1dPct'), '%', True)} / {_fmt(price.get('change5dPct'), '%', True)} / {_fmt(price.get('change20dPct'), '%', True)} · {source_label} · {quote_time} |")
        for key, zh_label, en_label in (("foreign", "外資", "Foreign"), ("trust", "投信", "Investment trust"), ("dealer", "自營商", "Dealers")):
            flow = (s.get("institutional") or {}).get(key)
            if flow:
                days = flow["streakDays"]
                if abs(days) >= 2:
                    streak = t(f"最新連續{'買' if days > 0 else '賣'}超 {abs(days)} 日", f"net {'buying' if days > 0 else 'selling'} {abs(days)} days in a row")
                elif days:
                    streak = t(f"最新一日{'買' if days > 0 else '賣'}超（前一日方向相反）", f"net {'bought' if days > 0 else 'sold'} on the latest day (reversal)")
                else:
                    streak = t("最新一日持平", "flat on the latest day")
                lines.append(f"| {t(zh_label + '買賣超 1日 / 5日 / 20日（張）', en_label + ' net 1d / 5d / 20d (lots)')} | {flow['net1dLots']:+,} / {flow['net5dLots']:+,} / {flow['net20dLots']:+,} · {streak} |")
        margin = s.get("margin") or {}
        if margin:
            lines.append(f"| {t('融資 / 融券餘額 5日變化 · 券資比', 'Margin / short balance 5d change · short-to-margin')} | {_fmt(margin.get('marginBalanceChange5dPct'), '%', True)} / {_fmt(margin.get('shortBalanceChange5dPct'), '%', True)} · {_fmt(margin.get('shortToMarginPct'), '%')} |")
        holding = s.get("foreignHolding") or {}
        if holding:
            lines.append(f"| {t('外資持股比例 · 20日變化', 'Foreign holding · 20d change')} | {_fmt(holding.get('percent'), '%')} · {_fmt(holding.get('change20dPp'), ' pp', True)} |")
        tdcc = s.get("tdcc") or {}
        if tdcc:
            lines.append(f"| {t('集保 400 張以上大戶', 'TDCC holders of 400+ lots')} ({tdcc['week']}) · {t('週 / 4週變化', '1w / 4w change')} | {_fmt(tdcc.get('largeHolderPercent'), '%')} · {_fmt(tdcc.get('largeHolderChange1wPp'), ' pp', True)} / {_fmt(tdcc.get('largeHolderChange4wPp'), ' pp', True)} |")
            lines.append(f"| {t('集保 10 張以下散戶 · 週變化', 'TDCC holders of ≤10 lots · 1w change')} | {_fmt(tdcc.get('retailPercent'), '%')} · {_fmt(tdcc.get('retailChange1wPp'), ' pp', True)} |")
        fundamentals = s.get("fundamentals") or {}
        month, quarter = fundamentals.get("latestMonth") or {}, fundamentals.get("latestQuarter") or {}
        if month:
            lines.append(f"| {t('月營收', 'Revenue')} {month['period']} {t('年增 / 月增 / 累計年增', 'YoY / MoM / YTD YoY')} | {_fmt(month.get('yoyPercent'), '%', True)} / {_fmt(month.get('momPercent'), '%', True)} / {_fmt(month.get('ytdYoyPercent'), '%', True)} |")
        if quarter:
            for key, zh_label, en_label in (("grossMargin", "毛利率", "Gross margin"), ("operatingMargin", "營益率", "Operating margin"), ("netMargin", "淨利率", "Net margin")):
                lines.append(f"| {quarter['period']} {t(zh_label + ' · 季 / 年變化', en_label + ' · QoQ / YoY change')} | {_fmt(quarter.get(key), '%')} · {_fmt(quarter.get(key + 'QoQ'), ' pp', True)} / {_fmt(quarter.get(key + 'YoY'), ' pp', True)} |")
            lines.append(f"| {quarter['period']} EPS {t('年增', 'YoY')} | {_fmt(quarter.get('epsYoY'), '%', True)} |")
    collecting = brief.get("collecting") or {}
    pending = sorted(set(collecting.get("history", [])) | set(collecting.get("fundamentals", [])))
    if pending:
        lines += ["", t(f"註：{sep.join(pending)} 的部分歷史資料仍在背景蒐集中，數值為「—」者稍後會自動補上。",
                        f"Note: some history for {sep.join(pending)} is still being collected; values shown as \"—\" fill in automatically.")]
    lines += ["", f"## {t('定義', 'Definitions')}", ""]
    lines += [t("- 張 = 1,000 股；pp = 百分點；集保大戶 = 400 張以上，散戶 = 10 張以下。",
                "- Lot = 1,000 shares; pp = percentage points; TDCC large holders = 400+ lots, retail = 10 lots or fewer."),
              t("- 期貨以標的現股呈現。", "- Futures are summarised through their underlying stock."),
              t("- 紅色 / + 代表上升，綠色 / − 代表下降（台股慣例）。", "- Red / + means up, green / − means down (Taiwan convention)."),
              t("- 此摘要僅陳述公開市場資料，非投資建議。", "- Public market data only; not investment advice."),
              t("- JSON 版本：/tymultiverse/brief.json", "- JSON version: /tymultiverse/brief.json")]
    return "\n".join(lines) + "\n"


class MarketBriefService:
    TTL_SECONDS = 300

    def __init__(self) -> None:
        self._cached: tuple[float, tuple, dict] | None = None
        self._lock = asyncio.Lock()

    def invalidate(self) -> None:
        self._cached = None

    async def get(self) -> dict:
        # Rebuild immediately when the holdings/custom list changes, otherwise reuse for TTL_SECONDS.
        selection = await asyncio.to_thread(current_selection)
        fingerprint = selection_fingerprint(selection[1])

        def fresh() -> bool:
            return bool(self._cached and self._cached[1] == fingerprint
                        and time.monotonic() - self._cached[0] < self.TTL_SECONDS)
        if fresh():
            return self._cached[2]
        async with self._lock:
            if fresh():
                return self._cached[2]
            # Read the already refreshed Shioaji cache / persisted snapshots; never
            # initiate a broker request per dashboard or brief-page request.
            stock_codes = sorted({_spot_code(item) for item in selection[1] if _spot_code(item)})
            quote_instruments = [{"code": code, "productType": "stock"} for code in stock_codes]
            try:
                quote_rows = await shioaji_market_service.get_dashboard_quotes(quote_instruments)
                quotes = {str(row.get("symbol", "")).upper(): row for row in quote_rows}
            except Exception:
                quotes = {}
            brief = await asyncio.to_thread(build_brief, selection, quotes)
            self._cached = (time.monotonic(), fingerprint, brief)
            await self._request_missing(brief.get("collecting", {}))
            return brief

    @staticmethod
    async def _request_missing(collecting: dict) -> None:
        """Queue background collection for stocks whose data is not stored yet, so gaps fill themselves."""
        if collecting.get("fundamentals"):
            market_fundamentals_service.request_history(collecting["fundamentals"])
        if collecting.get("history"):
            from .market_history_collector import market_history_collector
            await market_history_collector.enqueue_codes(collecting["history"])


market_brief_service = MarketBriefService()
