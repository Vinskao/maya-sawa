"""Insiders' pre-filed share transfers (內部人持股轉讓事前申報) for TWSE and TPEx stocks.

The OpenAPI datasets list only the filings published on the latest business day, so a daily collector keeps them in
maya_sawa_insider_transfer and a stock is flagged while a filing's transfer window is open (docs/INSIDER_TRANSFERS.md).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, timedelta

logger = logging.getLogger(__name__)

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap12_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap12_O"
SOURCE_PAGES = {"TWSE": "https://openapi.twse.com.tw/", "TPEx": "https://www.tpex.org.tw/openapi/"}
# Transfers that put shares on the market. 贈與 (gift), 信託 (trust) and similar move shares without selling them.
SALE_METHODS = ("一般交易", "盤後定價", "鉅額", "洽特定人", "拍賣", "標購", "公開招募")
UPCOMING_DAYS = 7


def roc_date(text: str | None) -> date | None:
    """ROC calendar YYYMMDD (1151116) -> 2026-11-16."""
    text = (text or "").strip()
    if len(text) != 7 or not text.isdigit():
        return None
    try:
        return date(int(text[:3]) + 1911, int(text[3:5]), int(text[5:]))
    except ValueError:
        return None


def transfer_window(text: str | None) -> tuple[date | None, date | None]:
    parts = (text or "").split("~")
    if len(parts) != 2:
        return None, None
    return roc_date(parts[0]), roc_date(parts[1])


def _int(value) -> int:
    try:
        return int(str(value or "0").replace(",", "").strip() or 0)
    except ValueError:
        return 0


def parse_filings(rows: Iterable[dict], market: str) -> list[dict]:
    """One shape for both markets (TWSE uses Chinese keys, TPEx English ones for the company columns)."""
    output = []
    for row in rows:
        code = str(row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
        filed = roc_date(row.get("出表日期") or row.get("Date"))
        start, end = transfer_window(row.get("有效轉讓期間"))
        if not code or not filed or not start or not end:
            continue
        method = str(row.get("預定轉讓方式及股數-轉讓方式") or "").strip()
        output.append({
            "market": market, "code": code, "name": str(row.get("公司名稱") or row.get("CompanyName") or code).strip(),
            "role": str(row.get("申報人身分") or row.get("申請人身分") or "").strip(),
            "holder": str(row.get("姓名") or "").strip(), "method": method,
            "sale": any(keyword in method for keyword in SALE_METHODS),
            "shares": _int(row.get("預定轉讓總股數-自有持股")) + _int(row.get("預定轉讓總股數-保留運用決定權信託股數")),
            "held": _int(row.get("目前持有股數-自有持股")) + _int(row.get("目前持有股數-保留運用決定權信託股數")),
            "filed": filed, "start": start, "end": end,
        })
    return output


def insider_events(filings: Iterable[dict], codes: set[str], today: date) -> list[dict]:
    """One company event per stock with an open (or soon to open) sale window, totalling every filer's planned shares."""
    grouped: dict[str, list[dict]] = {}
    for filing in filings:
        if (filing["code"] in codes and filing["sale"] and filing["end"] >= today
                and filing["start"] <= today + timedelta(days=UPCOMING_DAYS)):
            grouped.setdefault(filing["code"], []).append(filing)
    events = []
    for code, rows in grouped.items():
        rows.sort(key=lambda row: (row["start"], -row["shares"]))
        start, end = min(row["start"] for row in rows), max(row["end"] for row in rows)
        total = sum(row["shares"] for row in rows)
        methods = "、".join(dict.fromkeys(row["method"] for row in rows))
        who = f"{rows[0]['role']} {rows[0]['holder']}" if len(rows) == 1 else f"{len(rows)} 位內部人"
        period = f"{who} 預定轉讓 {total:,} 股（{methods}），{start:%m/%d}–{end:%m/%d}"
        events.append({"code": code, "name": rows[0]["name"], "type": "insider_transfer", "date": start.isoformat(),
                       "status": "active" if start <= today else "upcoming", "highlight": True, "period": period,
                       "shares": total, "endDate": end.isoformat(), "filers": len(rows),
                       "source": f"{rows[0]['market']} OpenAPI 內部人持股轉讓事前申報", "sourceUrl": SOURCE_PAGES[rows[0]["market"]]})
    return sorted(events, key=lambda event: (event["date"], event["code"]))


def fetch_json(url: str) -> list[dict]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; maya-sawa market dashboard)",
                                                   "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8-sig"))


def collect(save: Callable[[list[dict]], None]) -> int:
    """Fetch both markets' latest filings and store them; one market failing does not drop the other."""
    total = 0
    for market, url in (("TWSE", TWSE_URL), ("TPEx", TPEX_URL)):
        try:
            rows = parse_filings(fetch_json(url), market)
        except Exception as exc:
            logger.warning("Insider transfer filings from %s unavailable: %s", market, str(exc)[:80])
            continue
        if rows:
            save(rows)
        total += len(rows)
    return total


# --- Untransferred filings (未轉讓申報): filed after a window closes with shares left unsold -----------------------------
UNTRANSFERRED_URLS = {"TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap13_L",
                      "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap13_O"}
UNTRANSFERRED_DAYS = 14


def _field(row: dict, name: str):
    """TWSE writes 未轉讓股數-自有持股, TPEx 未轉讓股數自有持股; accept either spelling."""
    return row.get(name, row.get(name.replace("-", "")))


def parse_untransferred(rows: Iterable[dict], market: str) -> list[dict]:
    output = []
    for row in rows:
        code = str(row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
        filed = roc_date(row.get("出表日期") or row.get("Date"))
        if not code or not filed:
            continue  # TPEx answers a day without filings with one all-blank row
        output.append({
            "market": market, "code": code, "name": str(row.get("公司名稱") or row.get("CompanyName") or code).strip(),
            "role": str(row.get("申報人身分") or row.get("申請人身分") or "").strip(), "holder": str(row.get("姓名") or "").strip(),
            "shares": _int(_field(row, "未轉讓股數-自有持股")) + _int(_field(row, "未轉讓股數-保留運用決定權信託股數")),
            "planned": _int(_field(row, "原申報預定轉讓股數-自有持股")) + _int(_field(row, "原申報預定轉讓股數-保留運用決定權信託股數")),
            "reason": str(row.get("未轉讓理由") or "").strip(), "filed": filed,
        })
    return output


def untransferred_events(rows: Iterable[dict], codes: set[str], today: date) -> list[dict]:
    events = []
    for row in rows:
        if row["code"] not in codes or not 0 <= (today - row["filed"]).days <= UNTRANSFERRED_DAYS:
            continue
        reason = f"；{row['reason']}" if row["reason"] else ""
        events.append({"code": row["code"], "name": row["name"], "type": "insider_untransferred", "date": row["filed"].isoformat(),
                       "status": "recent", "highlight": False,
                       "period": f"{row['role']} {row['holder']} 未轉讓 {row['shares']:,} 股（原申報 {row['planned']:,} 股{reason}）",
                       "source": f"{row['market']} OpenAPI 內部人持股未轉讓申報", "sourceUrl": SOURCE_PAGES[row["market"]]})
    return sorted(events, key=lambda event: (event["date"], event["code"]))


# --- Monthly insider holdings (董監事持股餘額): a month-over-month rise marks insider buying ------------------------------
HOLDING_URLS = {"TWSE": "https://openapi.twse.com.tw/v1/opendata/t187ap11_L",
                "TPEx": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap11_O"}
BUY_MIN_SHARES = 10_000        # ten lots
UNIFORM_TOLERANCE = 0.005      # every holder up by the same ratio (within ±0.5%) looks like a stock dividend
UNIFORM_MIN_SHARES = 1_000     # tiny holdings round too coarsely to judge the ratio


def parse_holdings(rows: Iterable[dict]) -> tuple[str | None, dict]:
    """(YYYY-MM, {code: {name, persons: {person: shares}}}). A person listed under several titles is counted once."""
    month, snapshot = None, {}
    for row in rows:
        code = str(row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
        period = str(row.get("資料年月") or "").strip()
        person = str(row.get("姓名") or "").strip()
        if not code or not person or len(period) != 5 or not period.isdigit():
            continue
        month = f"{int(period[:3]) + 1911}-{period[3:]}"
        entry = snapshot.setdefault(code, {"name": str(row.get("公司名稱") or row.get("CompanyName") or code).strip(), "persons": {}})
        entry["persons"][person] = max(entry["persons"].get(person, 0), _int(row.get("目前持股")))
    return month, snapshot


def holding_changes(previous: dict, current: dict) -> dict[str, dict]:
    """Per stock, the change summed over insiders listed in both months (newly elected or departed insiders do not count)."""
    output = {}
    for code, entry in current.items():
        before = previous.get(code, {}).get("persons", {})
        common = [person for person in entry["persons"] if person in before]
        deltas = {person: entry["persons"][person] - before[person] for person in common}
        if not any(deltas.values()):
            continue
        ratios = [entry["persons"][person] / before[person] for person in common if before[person] >= UNIFORM_MIN_SHARES]
        uniform = (len(ratios) >= 2 and all(ratio > 1 for ratio in ratios)
                   and max(ratios) - min(ratios) <= UNIFORM_TOLERANCE * 2)
        output[code] = {"name": entry["name"], "net": sum(deltas.values()),
                        "increased": sum(1 for delta in deltas.values() if delta > 0), "compared": len(common), "uniform": uniform}
    return output


def holding_events(changes: Iterable[dict], codes: set[str]) -> list[dict]:
    events = []
    for change in changes:
        if change["code"] not in codes or change["uniform"] or change["net"] < BUY_MIN_SHARES:
            continue
        events.append({"code": change["code"], "name": change.get("name") or change["code"], "type": "insider_buy",
                       "date": f"{change['month']}-01", "status": "recent", "highlight": True,
                       "period": (f"{change['month']} 董監經理人持股較上月增加 {change['net']:,} 股（{change['increased']} 人增加）；"
                                  "月持股比較，可能含員工認股等非市場取得"),
                       "source": f"{change['market']} OpenAPI 董監事持股餘額", "sourceUrl": SOURCE_PAGES[change["market"]]})
    return sorted(events, key=lambda event: event["code"])


def store_holdings(db, market: str, month: str, snapshot: dict) -> int:
    """Compare a newly published month with the stored previous one; returns how many stocks changed (0 if not new)."""
    stored = db.latest_snapshot(market)
    if stored and stored[0] >= month:
        return 0
    changes = holding_changes(stored[1], snapshot) if stored else {}
    db.save_holdings(market, month, snapshot,
                     [{"market": market, "code": code, "month": month, **change} for code, change in changes.items()])
    return len(changes)


def collect_monthly_and_untransferred(db) -> dict[str, int]:
    """Untransferred filings (daily) and insider holdings (monthly; a month already stored is skipped)."""
    counts = {}
    for market, url in UNTRANSFERRED_URLS.items():
        try:
            rows = parse_untransferred(fetch_json(url), market)
            db.save_untransferred(rows)
            counts[f"untransferred:{market}"] = len(rows)
        except Exception as exc:
            logger.warning("Untransferred filings from %s unavailable: %s", market, str(exc)[:80])
    for market, url in HOLDING_URLS.items():
        try:
            month, snapshot = parse_holdings(fetch_json(url))
            if month:
                counts[f"holdings:{market}"] = store_holdings(db, market, month, snapshot)
        except Exception as exc:
            logger.warning("Insider holdings from %s unavailable: %s", market, str(exc)[:80])
    return counts
