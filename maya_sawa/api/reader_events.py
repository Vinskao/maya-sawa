"""Anonymous reader events from the frontend server, and the owner's view of the north star metric.

The browser posts to the frontend's own /api/market/track; only that server holds the internal secret, so this service
has a single caller to trust. See docs/NORTH_STAR_METRIC.md.
"""
import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.auth.internal import require_internal_secret
from ..core.auth.keycloak import require_manage_users_request
from ..databases.reader_events_db import EVENTS, TARGET_LIMIT, VISITOR_PATTERN, reader_events_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["reader-events"])


class ReaderEventReport(BaseModel):
    visitor: str = Field(pattern=VISITOR_PATTERN)
    event: Literal[EVENTS]  # type: ignore[valid-type]
    target: str = Field(default="", max_length=TARGET_LIMIT)


@router.post("/internal/reader-events", dependencies=[Depends(require_internal_secret)])
async def report_reader_event(body: ReaderEventReport):
    try:
        recorded = await asyncio.to_thread(reader_events_db.record, body.visitor, body.event, body.target)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Reader event could not be recorded")
        raise HTTPException(status_code=503, detail="Reader events unavailable") from exc
    return {"recorded": recorded}


@router.get("/admin/north-star")
async def north_star(weeks: int = Query(default=8, ge=1, le=26), _claims: dict = Depends(require_manage_users_request)):
    try:
        return {"metric": "weekly_returning_research_readers", "weeks": await asyncio.to_thread(reader_events_db.north_star, weeks)}
    except Exception as exc:
        logger.exception("North star read failed")
        raise HTTPException(status_code=503, detail="Reader events unavailable") from exc
