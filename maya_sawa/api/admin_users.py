"""Owner-only view of the site's users and their activity, and the internal endpoint the Java backend reports /learn activity to.

Keycloak stays the identity provider: this reads the small user table and the append-only activity log (docs/USER_PERMISSIONS.md).
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth.internal import require_internal_secret
from ..core.auth.keycloak import require_manage_users_request
from ..databases.user_activity_db import user_activity_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["user-activity"])


class ActivityReport(BaseModel):
    """One event the Java backend saw for a signed-in user (it has already verified the user's token)."""
    sub: str = Field(min_length=1, max_length=120)
    username: str = Field(default="", max_length=120)
    action: str = Field(pattern="^[CRUD]$")
    resourceType: str = Field(min_length=1, max_length=60)
    resourceId: str = Field(default="", max_length=200)
    detail: dict | None = None


@router.post("/internal/activity", dependencies=[Depends(require_internal_secret)])
async def report_activity(body: ActivityReport):
    try:
        await asyncio.to_thread(user_activity_db.touch_user, body.sub, body.username)
        await asyncio.to_thread(user_activity_db.record, body.sub, body.username, body.action, body.resourceType, body.resourceId, body.detail)
    except Exception as exc:
        logger.exception("Reported user activity could not be recorded")
        raise HTTPException(status_code=503, detail="User activity unavailable") from exc
    return {"recorded": True}


@router.get("/admin/users")
async def list_users(_claims: dict = Depends(require_manage_users_request)):
    try:
        return {"users": await asyncio.to_thread(user_activity_db.users)}
    except Exception as exc:
        logger.exception("User list read failed")
        raise HTTPException(status_code=503, detail="User activity unavailable") from exc


@router.get("/admin/users/{sub}/activity")
async def user_activity(sub: str, limit: int = 100, before_id: int | None = None, _claims: dict = Depends(require_manage_users_request)):
    try:
        return {"activity": await asyncio.to_thread(user_activity_db.activity, sub, limit, before_id)}
    except Exception as exc:
        logger.exception("User activity read failed")
        raise HTTPException(status_code=503, detail="User activity unavailable") from exc


@router.get("/admin/activity")
async def recent_activity(limit: int = 100, before_id: int | None = None, _claims: dict = Depends(require_manage_users_request)):
    try:
        return {"activity": await asyncio.to_thread(user_activity_db.activity, None, limit, before_id)}
    except Exception as exc:
        logger.exception("Recent activity read failed")
        raise HTTPException(status_code=503, detail="User activity unavailable") from exc
