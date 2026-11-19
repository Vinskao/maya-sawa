"""Owner approval and agent-only application endpoints."""
import asyncio
import hashlib
import hmac
import logging
import os
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.auth.keycloak import require_manage_users_request
from ..databases.market_dashboard_db import market_dashboard_db
from ..services.job_alerts.linkedin import JobQueue
from ..services.job_alerts.linkedin_gmail import collect

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market/linkedin-jobs", tags=["linkedin-jobs"])


@lru_cache(maxsize=1)
def queue():
    if market_dashboard_db.engine is None:
        raise HTTPException(503, "Job queue unavailable")
    return JobQueue(market_dashboard_db.engine)


def verify_apply_key(request: Request):
    expected = os.getenv("LINKEDIN_APPLY_KEY_SHA256", "").strip()
    supplied = request.headers.get("x-linkedin-apply-key", "")
    if not supplied or not expected or not hmac.compare_digest(hashlib.sha256(supplied.encode()).hexdigest(), expected):
        raise HTTPException(401, "Invalid application key")


class Review(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)
    approve: bool


class Outcome(BaseModel):
    action: Literal["submit", "submitted", "review", "uncertain"]
    identity: str | None = Field(default=None, min_length=3, max_length=500, pattern=r"^[a-z0-9][a-z0-9./:_-]+$")
    note: str = Field(default="", max_length=500)


@router.get("", dependencies=[Depends(require_manage_users_request)])
def list_jobs():
    return {"jobs": queue().list()}


@router.post("/review", dependencies=[Depends(require_manage_users_request)])
def review(body: Review):
    before, after = ("pending", "approved") if body.approve else ("approved", "pending")
    store = queue()
    return {"updated": [job_id for job_id in dict.fromkeys(body.ids) if store.transition(job_id, before, after)]}


@router.post("/claim", dependencies=[Depends(verify_apply_key)])
def claim():
    return {"job": queue().claim()}


@router.post("/{job_id}/outcome", dependencies=[Depends(verify_apply_key)])
def outcome(job_id: str, body: Outcome):
    transitions = {
        "submit": ("claimed", "submitting"),
        "submitted": ("submitting", "submitted"),
        "review": ("claimed", "needs_review"),
        "uncertain": ("submitting", "uncertain"),
    }
    before, after = transitions[body.action]
    values = {"note": body.note}
    if body.action == "submit":
        if not body.identity:
            raise HTTPException(422, "Canonical employer job identity required")
        values["identity"] = body.identity
    elif not body.note.strip():
        raise HTTPException(422, "Outcome evidence required")
    if not queue().transition(job_id, before, after, **values):
        raise HTTPException(409, "State changed or employer job identity already reserved")
    return {"status": after}


async def linkedin_gmail_loop():
    credentials = {name: os.getenv(f"LINKEDIN_GMAIL_{name.upper()}", "").strip()
                   for name in ("client_id", "client_secret", "refresh_token")}
    if not all(credentials.values()):
        return
    while True:
        try:
            await asyncio.to_thread(lambda: collect(queue(), credentials))
        except Exception as exc:
            logger.warning("LinkedIn Gmail poll failed (%s)", type(exc).__name__)
        await asyncio.sleep(15 * 60)
