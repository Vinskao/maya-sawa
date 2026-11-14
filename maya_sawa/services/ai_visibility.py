"""AI-search visibility: where tymultiverse.cc shows up when someone asks ChatGPT, Grok, Gemini or Claude (docs/AI_VISIBILITY.md).

Pure rules (keyword list, validation, summary). The GPT task that probes the platforms cannot be trusted, so everything it
sends goes through validate_results and waits for review before the dashboard counts it.
"""
from collections import defaultdict

PLATFORMS = ("chatgpt", "grok", "gemini", "claude")
# Keywords people would plausibly type to find this site, taken from docs/HOME_SEARCH_POSITIONING.md. Changing the list
# starts a new comparison baseline, so edit deliberately; the dashboard compares a cell only with the same keyword.
KEYWORDS = (
    "台股研究工具",
    "台股 AI 分析",
    "半導體供應鏈 研究",
    "CPO 共同封裝光學 供應鏈 台股",
    "總體經濟 個股風險 檢視",
    "投資研究報告 整理 AI",
    "基金經理人 研究工具",
    "台股 籌碼 分析 網站",
    "美股 台股 研究平台",
    "研究報告 主張 驗證",
    "TY 市場研究室",
    "Taiwan stock research platform",
)
STATUSES = ("checked", "unavailable")  # unavailable: the platform needed a login or refused; never guess a result
MAX_RANK = 20
SNIPPET_LIMIT = 300


def validate_results(results: list[dict]) -> list[dict]:
    """Return normalized rows, or raise ValueError with the first problem."""
    if not results:
        raise ValueError("No results")
    seen, out = set(), []
    for item in results:
        keyword, platform = item.get("keyword"), item.get("platform")
        if keyword not in KEYWORDS:
            raise ValueError(f"Unknown keyword: {keyword}")
        if platform not in PLATFORMS:
            raise ValueError(f"Unknown platform: {platform}")
        if (keyword, platform) in seen:
            raise ValueError(f"duplicate result for {keyword} / {platform}")
        seen.add((keyword, platform))
        status = item.get("status", "checked")
        if status not in STATUSES:
            raise ValueError(f"Unknown status: {status}")
        appeared, rank = bool(item.get("appeared")), item.get("rank")
        if status == "unavailable" and (appeared or rank is not None):
            raise ValueError("An unavailable platform cannot report an appearance")
        if rank is not None and (not appeared or not isinstance(rank, int) or not 1 <= rank <= MAX_RANK):
            raise ValueError(f"rank must be 1-{MAX_RANK} and only when the site appeared")
        competitors = [str(c)[:60] for c in (item.get("competitors") or [])][:5]
        out.append({"keyword": keyword, "platform": platform, "status": status, "appeared": appeared, "rank": rank,
                    "cited": bool(item.get("cited")) and appeared, "snippet": str(item.get("snippet") or "")[:SNIPPET_LIMIT],
                    "competitors": competitors})
    return out


def _totals(results: list[dict]) -> dict:
    checked = [r for r in results if r["status"] == "checked"]
    ranks = [r["rank"] for r in checked if r["rank"]]
    return {"checked": len(checked), "appeared": sum(r["appeared"] for r in checked),
            "unavailable": len(results) - len(checked), "bestRank": min(ranks) if ranks else None}


def _change(now: dict, before: dict | None) -> str:
    if now["status"] != "checked":
        return "unavailable"
    if before is None or before["status"] != "checked":
        return "new" if now["appeared"] else "none"
    if now["appeared"] and not before["appeared"]:
        return "new"
    if before["appeared"] and not now["appeared"]:
        return "lost"
    if now["appeared"] and now["rank"] and before["rank"]:
        return "up" if now["rank"] < before["rank"] else "down" if now["rank"] > before["rank"] else "same"
    return "same" if now["appeared"] else "none"


def summarize(runs: list[dict]) -> dict:
    """`runs`: accepted runs, newest first. Cells compare the latest run with the one before it."""
    if not runs:
        return {"latest": None, "previous": None, "byPlatform": {}, "cells": [], "trend": []}
    latest, previous = runs[0], runs[1] if len(runs) > 1 else None
    before = {(r["keyword"], r["platform"]): r for r in previous["results"]} if previous else {}
    by_platform = defaultdict(lambda: {"checked": 0, "appeared": 0, "bestRank": None})
    for r in latest["results"]:
        if r["status"] != "checked":
            continue
        p = by_platform[r["platform"]]
        p["checked"] += 1
        p["appeared"] += r["appeared"]
        if r["rank"] and (p["bestRank"] is None or r["rank"] < p["bestRank"]):
            p["bestRank"] = r["rank"]
    cells = [{**r, "change": _change(r, before.get((r["keyword"], r["platform"])))} for r in latest["results"]]
    trend = [{"id": run["id"], "at": run["submittedAt"], **_totals(run["results"])} for run in reversed(runs[:12])]
    return {"latest": {"id": latest["id"], "at": latest["submittedAt"], **_totals(latest["results"])},
            "previous": {"id": previous["id"], "at": previous["submittedAt"], **_totals(previous["results"])} if previous else None,
            "byPlatform": dict(by_platform), "cells": cells, "trend": trend}
