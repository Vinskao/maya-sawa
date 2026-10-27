"""Recover pending publication events from PostgreSQL after any process restart."""
import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager, suppress
from .blog_postgres import get_postgres_store
from .blog import BlogService, Conflict, index_article

logger = logging.getLogger(__name__)


def drain(service, indexer=index_article):
    count = 0
    for state in service.list(admin=True):
        if state['indexStatus'] not in ('pending', 'failed') or state.get('retryAfter', 0) > time.time():
            continue
        try:
            service.process(state['id'], indexer)
            count += 1
        except Conflict:
            continue
    return count


async def loop():
    while True:
        try:
            await asyncio.to_thread(drain, BlogService(get_postgres_store()))
        except Exception:
            # Do not expose provider URLs, credentials or raw database exceptions.
            logger.warning('Blog indexing is unavailable; pending events remain retryable')
        await asyncio.sleep(30)


@asynccontextmanager
async def blog_worker():
    task = None
    if os.getenv('BLOG_ENABLED', 'false').lower() == 'true':
        task = asyncio.create_task(loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
