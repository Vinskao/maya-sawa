"""Isolated, bounded GPT drafts and keyed reviewer actions."""
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..services.daily_maya_sources import validate_sources


class Submission(BaseModel):
    day: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    content: str = Field(min_length=1, max_length=20000)
    sources: list[str] = Field(min_length=1, max_length=50)


class Review(BaseModel):
    decision: str = Field(pattern=r'^(approved|rejected)$')
    note: str = Field(min_length=1, max_length=1000)


def make_router(db, analyses, authorized, clock=lambda: datetime.now(timezone.utc), on_approved=None):
    router = APIRouter(prefix='/market/daily-maya', tags=['daily maya'])

    def require_agent(request):
        if not authorized(request):
            raise HTTPException(401, 'Invalid agent key')

    @router.post('/proposals')
    async def submit(body: Submission):
        now = clock()
        if body.day != now.astimezone(ZoneInfo('Asia/Taipei')).date().isoformat():
            raise HTTPException(422, 'Day must be today in Asia/Taipei')
        try:
            await asyncio.to_thread(validate_sources, body.sources, analyses)
            row, created = await asyncio.to_thread(db.submit, body.day, body.content, body.sources, now)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OverflowError as exc:
            raise HTTPException(429, str(exc)) from exc
        return {'id': row['id'], 'created': created, 'status': row['status']}

    @router.get('/proposals')
    async def pending(request: Request):
        require_agent(request)
        return {'proposals': await asyncio.to_thread(db.pending)}

    @router.post('/proposals/{proposal_id}/review')
    async def review(proposal_id: str, body: Review, request: Request):
        require_agent(request)
        row = await asyncio.to_thread(db.get, proposal_id)
        if not row:
            raise HTTPException(404, 'Proposal not found')
        if row['status'] != 'pending':
            raise HTTPException(409, 'Proposal already reviewed')
        if body.decision == 'approved':
            try:
                await asyncio.to_thread(validate_sources, row['sources'], analyses)
            except ValueError as exc:
                raise HTTPException(409, 'Source revision no longer available') from exc
        try:
            changed = await asyncio.to_thread(db.review, proposal_id, body.decision, body.note, clock())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not changed:
            raise HTTPException(409, 'Proposal already reviewed')
        if body.decision == 'approved' and on_approved:
            published_row = await asyncio.to_thread(db.get, proposal_id)
            try:
                await asyncio.to_thread(on_approved, published_row)
            except Exception:
                # Publication remains committed; queue reconciliation can repair a missed audio job.
                import logging
                logging.getLogger(__name__).exception('Daily Maya audio job enqueue failed')
        return {'id': proposal_id, 'status': body.decision}

    @router.get('')
    async def published():
        return {'items': await asyncio.to_thread(db.published)}

    return router
