"""Held Taiwan stocks with a notable event must not be left out of the daily reading (2026-11-19).

The 11/19 draft was rejected for covering two of five holdings: 創意 (volume top five), 世芯 (Q3 gross margin) and
Advantest were missing. The reviewer found it after the fact; the same check now refuses the draft at POST so the
writer fixes it in the same run. Only holdings are required (never the AI opportunity pool or watch list), only Taiwan
names (foreign names are written in many spellings), and only events the dashboard marks as highlights.
"""
import re

REQUIRED_EVENTS = {"volume_spike": "成交量進入近一年前幾大", "financial_report": "新一季財報", "monthly_revenue": "新一期月營收"}
_NOISE = re.compile(r"[-－]?KY|\*|-DR|小型|期貨|選擇權|\d+|\s")


def short_name(name: str) -> str:
    return _NOISE.sub("", str(name or ""))


def mentioned(content: str, name: str) -> bool:
    """A company counts as covered when its name, or its first two characters for longer names, is in the text."""
    full = short_name(name)
    return bool(full) and (full in content or (len(full) >= 3 and full[:2] in content))


def uncovered_holdings(content: str, positions: list[dict], events: list[dict]) -> list[str]:
    """'創意（成交量進入近一年前幾大）' for every held Taiwan stock with a highlighted event that the text never mentions."""
    held = {str(p.get("code")): p for p in positions
            if p.get("productType", "stock") == "stock" and (p.get("market") or "TW").upper() == "TW"}
    missing: dict[str, list[str]] = {}
    for event in events:
        code, kind = str(event.get("code")), event.get("type")
        if code not in held or kind not in REQUIRED_EVENTS or not event.get("highlight"):
            continue
        if (event.get("market") or "TW").upper() != "TW" or mentioned(content, held[code].get("name") or event.get("name")):
            continue
        label = REQUIRED_EVENTS[kind]
        if label not in missing.setdefault(code, []):
            missing[code].append(label)
    return [f"{short_name(held[code].get('name') or code)}（{'、'.join(labels)}）" for code, labels in missing.items()]


def message(missing: list[str]) -> str:
    return ("持股有重大事件但稿子沒有提到：" + "、".join(missing)
            + "。事件清單（GET /market/dashboard/events）裡這些持股有新事件，請在個股段落補上，可與相關事件合併，再重新提交。")
