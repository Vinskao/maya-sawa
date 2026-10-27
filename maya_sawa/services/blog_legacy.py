"""A single ownership switch prevents old sync paths from overwriting editorial data."""
import os
from functools import wraps
from fastapi import HTTPException, Request


def reject_legacy_sync():
    if os.getenv('BLOG_ENABLED', 'false').lower() == 'true':
        raise HTTPException(410, 'Article sync is retired; use Markdown import and publication')


def reject_legacy_article_write(request: Request):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        reject_legacy_sync()


def legacy_sync_guard(operation):
    @wraps(operation)
    async def guarded(*args, **kwargs):
        reject_legacy_sync()
        return await operation(*args, **kwargs)
    return guarded
