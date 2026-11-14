"""AI-search visibility endpoints (docs/AI_VISIBILITY.md): keyword list for the GPT task, an unkeyed inbox, keyed review, owner view."""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.auth.keycloak import require_manage_users_request
from ..databases.ai_visibility_db import InboxFull, ai_visibility_db
from ..services.ai_visibility import KEYWORDS, PLATFORMS, summarize, validate_results
from .market import _verify_agent_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["ai-visibility"])
RUNS_PER_WEEK = 6  # twice a week plus retries


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


@router.get("/ai-visibility/keywords")
async def keywords():
    return {"keywords": list(KEYWORDS), "platforms": list(PLATFORMS), "site": "tymultiverse.cc"}


@router.post("/ai-visibility/runs")
async def submit_run(body: VisibilitySubmission):
    now = datetime.now(ZoneInfo("UTC"))
    try:
        results = validate_results([r.model_dump() for r in body.results])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    iso = now.astimezone(ZoneInfo("Asia/Taipei")).isocalendar()
    try:
        row, stored = await asyncio.to_thread(ai_visibility_db.submit, f"{iso.year}-W{iso.week:02d}", results, now, RUNS_PER_WEEK)
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
    fixes = [{"runId": r["id"], "at": r["reviewedAt"], "items": r["fixes"]} for r in accepted if r["fixes"]][:3]
    return {**summarize(accepted), "pending": pending, "fixes": fixes}
