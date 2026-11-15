"""AI-search visibility endpoints (docs/AI_VISIBILITY.md): keyword list for the GPT task, an unkeyed inbox, keyed review, owner view."""
import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.auth.keycloak import require_manage_users_request
from ..databases.ai_visibility_db import InboxFull, ai_visibility_db
import os

import httpx

from ..services.ai_visibility import AUTO_PLATFORMS, KEYWORDS, PLATFORMS, gemini_result, summarize, validate_results, weekly_keywords
from .market import _verify_agent_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["ai-visibility"])
RUNS_PER_WEEK = 6  # one GPT run plus retries
AUTO_PER_WEEK = 10  # Gemini probe + Claude routine, with retries
GEMINI_MODEL = os.getenv("AI_VISIBILITY_GEMINI_MODEL", "gemini-2.5-flash")


class VisibilityResult(BaseModel):
    keyword: str = Field(max_length=80)
    platform: str = Field(max_length=20)
    status: str = Field(default="checked", max_length=20)
    appeared: bool = False
    rank: int | None = None
    cited: bool = False
    snippet: str = Field(default="", max_length=300)
    competitors: list[str] = Field(default_factory=list, max_length=5)


class VisibilitySubmission(BaseModel):
    results: list[VisibilityResult] = Field(max_length=len(KEYWORDS) * len(PLATFORMS))


class VisibilityReview(BaseModel):
    action: str = Field(pattern="^(accept|reject)$")
    note: str = Field(default="", max_length=300)


class VisibilityFixes(BaseModel):
    fixes: list[str] = Field(min_length=1, max_length=10)


def _unavailable(exc: Exception) -> HTTPException:
    logger.exception("AI visibility store failed")
    return HTTPException(status_code=503, detail="AI visibility unavailable")


WEEK_ROLLOVER = timedelta(hours=6)  # checks run Friday/Sunday nights after midnight; Monday before 06:00 is still last week


def _week(now: datetime) -> str:
    iso = (now.astimezone(ZoneInfo("Asia/Taipei")) - WEEK_ROLLOVER).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


@router.get("/ai-visibility/keywords")
async def keywords():
    week = _week(datetime.now(ZoneInfo("UTC")))
    return {"keywords": list(KEYWORDS), "platforms": list(PLATFORMS), "site": "tymultiverse.cc",
            "week": week, "thisWeek": weekly_keywords(week)}


@router.post("/ai-visibility/runs")
async def submit_run(body: VisibilitySubmission):
    now = datetime.now(ZoneInfo("UTC"))
    try:
        results = validate_results([r.model_dump() for r in body.results])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        row, stored = await asyncio.to_thread(ai_visibility_db.submit, _week(now), results, now, RUNS_PER_WEEK)
    except InboxFull as exc:
        raise HTTPException(status_code=429, detail="This week's visibility inbox is full") from exc
    except Exception as exc:
        raise _unavailable(exc) from exc
    return {"stored": stored, "id": row["id"], "status": row["status"]}


@router.get("/ai-visibility/runs")
async def list_runs(request: Request, status: str = "pending"):
    _verify_agent_key(request)
    try:
        return {"runs": await asyncio.to_thread(ai_visibility_db.list, None if status == "all" else status)}
    except Exception as exc:
        raise _unavailable(exc) from exc


@router.post("/ai-visibility/runs/{run_id}/review")
async def review_run(run_id: str, body: VisibilityReview, request: Request):
    _verify_agent_key(request)
    row = await asyncio.to_thread(ai_visibility_db.review, run_id, body.action, body.note, datetime.now(ZoneInfo("UTC")))
    if row:
        return {"id": run_id, "status": row["status"]}
    exists = await asyncio.to_thread(ai_visibility_db.get, run_id)
    raise HTTPException(status_code=409 if exists else 404, detail="Run already reviewed" if exists else "Unknown run")


@router.post("/ai-visibility/runs/{run_id}/fixes")
async def record_fixes(run_id: str, body: VisibilityFixes, request: Request):
    """What the repair routine changed on the site in answer to this run; shown next to its numbers."""
    _verify_agent_key(request)
    row = await asyncio.to_thread(ai_visibility_db.add_fixes, run_id, [f[:200] for f in body.fixes])
    if not row:
        raise HTTPException(status_code=404, detail="No accepted run with that id")
    return {"id": run_id, "fixes": row["fixes"]}


@router.get("/admin/ai-visibility")
async def owner_view(_claims: dict = Depends(require_manage_users_request)):
    try:
        accepted = await asyncio.to_thread(ai_visibility_db.list, "accepted", 12)
        pending = await asyncio.to_thread(ai_visibility_db.count, "pending")
    except Exception as exc:
        raise _unavailable(exc) from exc
    week = _week(datetime.now(ZoneInfo("UTC")))
    fixes = [{"runId": r["id"], "at": r["reviewedAt"], "items": r["fixes"]} for r in accepted if r["fixes"]][:3]
    return {**summarize(accepted), "pending": pending, "fixes": fixes, "week": week, "thisWeek": weekly_keywords(week)}


def ask_gemini(keyword: str, key: str) -> dict:
    """Ask Gemini the keyword verbatim, as a user would, with Google Search grounding on (free tier)."""
    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": keyword}]}], "tools": [{"google_search": {}}]}, timeout=90)
    return response.json()


async def _store_auto(results: list[dict]) -> dict:
    now = datetime.now(ZoneInfo("UTC"))
    try:
        row, stored = await asyncio.to_thread(ai_visibility_db.submit, _week(now), results, now, AUTO_PER_WEEK, "accepted")
    except InboxFull as exc:
        raise HTTPException(status_code=429, detail="Too many automatic runs this week") from exc
    except Exception as exc:
        raise _unavailable(exc) from exc
    return {"stored": stored, "id": row["id"], "status": row["status"]}


@router.post("/ai-visibility/probe/gemini")
async def probe_gemini(request: Request):
    """Called by the Monday routine: checks this week's keywords on Gemini and records them (trusted, server-side)."""
    _verify_agent_key(request)
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")
    results = []
    for keyword in weekly_keywords(_week(datetime.now(ZoneInfo("UTC")))):
        try:
            response = await asyncio.to_thread(ask_gemini, keyword, key)
        except Exception as exc:
            logger.warning("Gemini visibility probe failed for %s: %s", keyword, exc)
            response = {"error": {"message": "request failed"}}
        results.append(gemini_result(keyword, response))
    return {**await _store_auto(validate_results(results)), "results": results}


@router.post("/ai-visibility/auto")
async def auto_entry(body: VisibilitySubmission, request: Request):
    """The keyed Claude routine's own web-search checks; trusted like the probe, limited to the automatic platforms."""
    _verify_agent_key(request)
    try:
        results = validate_results([r.model_dump() for r in body.results])
        if any(r["platform"] not in AUTO_PLATFORMS for r in results):
            raise ValueError(f"Automatic entries are limited to {', '.join(AUTO_PLATFORMS)}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return await _store_auto(results)
