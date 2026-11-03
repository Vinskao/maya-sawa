"""Public access to completed market analysis narration."""
import asyncio
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response


def make_router(db):
    router = APIRouter(prefix='/market/audio', tags=['market audio'])

    @router.get('')
    async def catalog():
        try:
            return {'items': await asyncio.to_thread(db.list_ready)}
        except Exception as exc:
            raise HTTPException(503, 'Audio database unavailable') from exc

    @router.get('/{product_type}/{code}/{revision}')
    async def audio(product_type: str, code: str, revision: int):
        code_pattern = r'[a-zA-Z0-9-]{1,64}' if product_type == 'daily' else r'[A-Z0-9-]{1,24}'
        if product_type not in {'macro', 'stock', 'daily'} or not re.fullmatch(code_pattern, code) or revision < 1:
            raise HTTPException(404, 'Audio not found')
        try:
            result = await asyncio.to_thread(db.audio, product_type, code, revision)
        except Exception as exc:
            raise HTTPException(503, 'Audio database unavailable') from exc
        if result is None:
            raise HTTPException(404, 'Audio not found')
        data, mime = result
        return Response(content=data, media_type=mime, headers={'Cache-Control': 'public, max-age=3600'})

    return router
