"""
Voyeur API Endpoints
Migrated from Voyeur Django project.
Contains Visit and Queue functionality using Redis.
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Form, Query
from fastapi.responses import JSONResponse
import logging
from ..databases.visit_count_db import visit_count_db

from ..core.database.connection_pool import get_pool_manager
from ..core.config.config import Config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voyeur", tags=["Voyeur"])

def _redis_count(redis_client) -> int:
    if redis_client is None:
        return 0
    try:
        return max(0, int(redis_client.get("visit_count") or 0))
    except Exception as exc:
        logger.warning("Could not read legacy visit count from Redis: %s", exc)
        return 0


def _optional_redis_client():
    try:
        return get_pool_manager().get_redis_connection()
    except Exception as exc:
        logger.warning("Redis cache unavailable for persisted visit counter: %s", exc)
        return None


def _sync_redis_cache(redis_client, total: int) -> None:
    if redis_client is None:
        return
    try:
        redis_client.set("visit_count", total)
    except Exception as exc:
        logger.warning("Persistent visit count saved, but Redis cache update failed: %s", exc)

@router.get("/count/")
async def get_visit_count():
    """
    Read the durable count from PostgreSQL and refresh the Redis cache.
    """
    try:
        r = _optional_redis_client()
        legacy_total = _redis_count(r)
        visit_count_db.ensure_baseline(legacy_total)
        count = visit_count_db.history(1)["totalCount"]
        _sync_redis_cache(r, count)
        logger.info("Current persistent visit count: %s", count)
        return {"count": count, "persisted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting persistent visit count: %s", e)
        raise HTTPException(status_code=503, detail="Persistent visit count unavailable")

@router.post("/increment/")
async def increment_visit_count():
    """
    Persist one visit in the daily PostgreSQL bucket, then refresh Redis as a cache.
    """
    try:
        r = _optional_redis_client()
        now = datetime.now(timezone.utc)
        count = visit_count_db.increment(now, _redis_count(r))
        _sync_redis_cache(r, count)
        logger.info("Persisted visit count increment: %s", count)
        return {"count": count, "persisted": True, "timestamp": now.isoformat(timespec="seconds")}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error incrementing persistent visit count: %s", e)
        raise HTTPException(status_code=503, detail="Persistent visit count unavailable")


@router.get("/history/")
async def get_visit_history(days: int = Query(default=365, ge=1, le=1825)):
    """Return daily persisted visits and cumulative totals for the homepage trend chart."""
    try:
        r = _optional_redis_client()
        history = visit_count_db.history(days)
        _sync_redis_cache(r, history["totalCount"])
        return history
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error getting persistent visit history: %s", exc)
        raise HTTPException(status_code=500, detail="Visit history unavailable")

@router.post("/push/")
async def push_to_queue(value: int = Form(1)):
    """
    Push value to Redis queue.
    Matches Django PushView.
    Supports Form data (application/x-www-form-urlencoded) for backward compatibility.
    """
    try:
        r = get_pool_manager().get_redis_connection()
        if not r:
             raise HTTPException(status_code=503, detail="Redis connection unavailable")

        queue_name = Config.REDIS_QUEUE_VOYEUR
        if not queue_name:
             # Fallback if config is missing, though Config has default
             queue_name = "voyeur_queue"

        r.rpush(queue_name, value)
        length = r.llen(queue_name)
        logger.info(f"Pushed {value} to queue {queue_name}, current length: {length}")
        
        return {
            "status": "success",
            "message": f"Pushed {value} to queue",
            "queue_length": length
        }
    except Exception as e:
        logger.error(f"Error pushing to queue: {str(e)}")
        # Django view returned 500 JSON
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": str(e)
            }
        )
