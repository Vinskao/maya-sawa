"""Public podcast RSS for approved daily readings that already have finished audio."""
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..services.podcast_feed import build_podcast_rss

_CONFIG_PATH = Path(__file__).resolve().parents[2] / 'config' / 'podcast.json'


def load_podcast_config():
    with _CONFIG_PATH.open(encoding='utf-8') as config_file:
        return json.load(config_file)


def make_router(audio_db, daily_db, config=None):
    config = config or load_podcast_config()
    router = APIRouter(tags=['podcast'])

    def episodes():
        approved = {row['id']: row for row in daily_db.published()}
        items = []
        for audio in audio_db.list_ready():
            row = approved.get(audio['code']) if audio['productType'] == 'daily' else None
            if row is None:
                continue
            items.append({'id': row['id'], 'revision': audio['revision'], 'day': row['day'], 'title': row.get('title'),
                          'content': row['content'], 'reading': row.get('reading'), 'sources': row['sources'],
                          'createdAt': audio['createdAt'], 'size': audio.get('size') or 0})
        return items

    @router.get('/market/podcast.xml')
    async def feed():
        try:
            items = await asyncio.to_thread(episodes)
        except Exception as exc:
            raise HTTPException(503, 'Podcast feed unavailable') from exc
        return Response(content=build_podcast_rss(items, config), media_type='application/rss+xml; charset=utf-8',
                        headers={'Cache-Control': 'public, max-age=300'})

    return router
