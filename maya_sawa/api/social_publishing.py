"""Public card images for Instagram, and owner-only status / manual run for server-side social publishing."""
import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..core.auth.keycloak import require_manage_users_request
from ..databases.market_ai_analysis_db import market_ai_analysis_db
from ..services.social.card import render_card

router = APIRouter(prefix='/market/publishing', tags=['publishing'])


@router.get('/cards/{kind}/{code}/{revision}.png', include_in_schema=False)
async def card(kind: str, code: str, revision: int):
    """Only the current revision of a public stock or US macro analysis; Instagram fetches this URL once per post."""
    if kind not in {'stock', 'macro'} or (kind == 'macro' and code != 'US'):
        raise HTTPException(404, 'No such card')
    current = (await asyncio.to_thread(market_ai_analysis_db.read, kind, code)).get('analysis')
    if not current or current['revision'] != revision:
        raise HTTPException(404, 'No such card')
    image = await asyncio.to_thread(render_card, current)
    return Response(image, media_type='image/png', headers={'Cache-Control': 'public, max-age=86400'})


def _outbox():
    from ..databases.market_dashboard_db import market_dashboard_db
    from ..services.social.outbox import SocialOutbox
    return SocialOutbox(market_dashboard_db.engine)


@router.get('/social/status', include_in_schema=False)
async def status(user=Depends(require_manage_users_request)):
    from ..services.social import runner
    outbox = await asyncio.to_thread(_outbox)
    page = bool(os.getenv('META_PAGE_ACCESS_TOKEN'))
    configured = {'facebook': page, 'instagram': page, 'threads': bool(os.getenv('THREADS_ACCESS_TOKEN')
                                                                       or outbox.get('threads_token'))}
    from ..services.social.sources import public_sources
    sources = (await asyncio.to_thread(public_sources, None, None))['sources']
    channels = [channel for channel, ready in configured.items() if ready]
    return {'enabled': runner.enabled(), 'configured': configured, 'lastRun': outbox.get(runner.CURSOR),
            'coverage': await asyncio.to_thread(runner.coverage, outbox, sources, channels),
            'posts': await asyncio.to_thread(outbox.posts)}


@router.post('/social/run', include_in_schema=False)
async def run(user=Depends(require_manage_users_request)):
    from ..services.social import runner
    if not runner.enabled():
        raise HTTPException(409, 'Social publishing is disabled (SOCIAL_PUBLISH_ENABLED=false)')
    return await asyncio.to_thread(runner.run_now)
