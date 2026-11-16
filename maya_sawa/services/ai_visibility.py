"""AI-search visibility: where tymultiverse.cc shows up when someone asks ChatGPT, Grok, Gemini or Claude (docs/AI_VISIBILITY.md).

Pure rules (keyword list, validation, summary). The GPT task that probes the platforms cannot be trusted, so everything it
sends goes through validate_results and waits for review before the dashboard counts it.
"""
from collections import defaultdict

PLATFORMS = ("chatgpt", "grok", "gemini", "claude")
# Keywords people would plausibly type to find this site, taken from docs/HOME_SEARCH_POSITIONING.md. Changing the list
# starts a new comparison baseline, so edit deliberately; the dashboard compares a cell only with the same keyword.
SITE_KEYWORDS = (
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
# 2026-11-16: queries the /work articles are titled to answer (data/blog_titles.json), so the weekly check also shows whether
# individual articles surface in AI answers, not only the site as a whole.
ARTICLE_KEYWORDS = (
    "Redis 為什麼快 Key-Value 記憶體資料庫",
    "React Hydration 是什麼 SSR 為什麼快",
    "R2DBC 是什麼 Spring WebFlux 反應式資料庫",
    "git reset --hard 與 --soft 差別 git revert",
    "Spring Boot IoC AOP 原理",
    "Kubernetes kind 本機部署 Spring Boot",
)
KEYWORDS = SITE_KEYWORDS + ARTICLE_KEYWORDS
MAIN_KEYWORD = KEYWORDS[0]  # checked every week so there is one continuous trend line


def _rotate(pool: tuple, week: str, count: int) -> list[str]:
    year, number = week.split("-W")
    start = ((int(year) * 53 + int(number) - 1) * count) % len(pool)
    return [pool[(start + i) % len(pool)] for i in range(count)]


def weekly_keywords(week: str) -> list[str]:
    """This ISO week's three keywords ("2026-W47"): the main one, one more site keyword and one article keyword, each rotating."""
    others = tuple(k for k in SITE_KEYWORDS if k != MAIN_KEYWORD)
    return [MAIN_KEYWORD] + _rotate(others, week, 1) + _rotate(ARTICLE_KEYWORDS, week, 1)


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


def _by_week(runs: list[dict]) -> list[dict]:
    """Merge runs of the same week (GPT's ChatGPT cells, the owner's manual cells); a newer run wins a cell. Newest week first."""
    weeks: dict[str, dict] = {}
    for run in runs:  # newest first
        week = run.get("week") or run["submittedAt"][:10]
        merged = weeks.setdefault(week, {"id": run["id"], "week": week, "submittedAt": run["submittedAt"], "cells": {}})
        for r in run["results"]:
            merged["cells"].setdefault((r["keyword"], r["platform"]), r)
    return [{**w, "results": list(w["cells"].values())} for w in weeks.values()]


def _head(week: dict) -> dict:
    return {"id": week["id"], "week": week["week"], "at": week["submittedAt"], **_totals(week["results"])}


def summarize(runs: list[dict]) -> dict:
    """`runs`: accepted runs, newest first. Cells compare the latest week with the week before it."""
    weeks = _by_week(runs)
    if not weeks:
        return {"latest": None, "previous": None, "byPlatform": {}, "cells": [], "trend": []}
    latest, previous = weeks[0], weeks[1] if len(weeks) > 1 else None
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
    return {"latest": _head(latest), "previous": _head(previous) if previous else None,
            "byPlatform": dict(by_platform), "cells": cells, "trend": [_head(w) for w in reversed(weeks[:12])]}


# ---- Automatic checks (2026-11-15): Gemini via its API with Google Search grounding; Claude via the Monday routine ----
AUTO_PLATFORMS = ("gemini", "claude")  # ChatGPT / Grok need paid API credit; off until then
SITE = "tymultiverse.cc"
SITE_NAMES = (SITE, "TY 市場研究室", "TY Multiverse")


def gemini_result(keyword: str, response: dict) -> dict:
    """Turn one Gemini generateContent answer into a result row; anything unusable is `unavailable`, never a guess."""
    try:
        candidate = response["candidates"][0]
        text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
    except (KeyError, IndexError, TypeError):
        return {"keyword": keyword, "platform": "gemini", "status": "unavailable", "appeared": False, "rank": None,
                "cited": False, "snippet": str((response or {}).get("error", {}).get("message", "no answer"))[:SNIPPET_LIMIT],
                "competitors": []}
    chunks = (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []
    sources = [((c.get("web") or {}).get("title") or (c.get("web") or {}).get("uri") or "").lower() for c in chunks]
    rank = next((i + 1 for i, s in enumerate(sources) if SITE in s), None)
    lowered = text.lower()
    named = next((n for n in SITE_NAMES if n.lower() in lowered), None)
    appeared = bool(rank or named)
    snippet = ""
    if named:
        at = lowered.index(named.lower())
        snippet = text[max(0, at - 80): at + 160]
    competitors = list(dict.fromkeys(s for s in sources if s and SITE not in s))[:5]
    return {"keyword": keyword, "platform": "gemini", "status": "checked", "appeared": appeared,
            "rank": rank if rank and rank <= MAX_RANK else None, "cited": bool(rank), "snippet": snippet[:SNIPPET_LIMIT],
            "competitors": competitors}
