"""
Voyeur API Endpoints
Migrated from Voyeur Django project.
Contains Visit and Queue functionality using Redis.
"""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Form, Query
from fastapi.responses import JSONResponse
import logging
from threading import Lock

try:
    import pymongo
    from pymongo import ASCENDING
except ImportError:
    pymongo = None
    ASCENDING = 1

from ..core.database.connection_pool import get_pool_manager
from ..core.config.config import Config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voyeur", tags=["Voyeur"])

_BASELINE_ID = "legacy-baseline"
_VISIT_TIMEZONE = timezone(timedelta(hours=8))
_mongo_client = None
_mongo_client_lock = Lock()


def _visit_collection():
    """Return the durable visit-count collection, using a pooled Mongo client."""
    global _mongo_client
    if pymongo is None or not Config.MONGODB_URI:
        raise HTTPException(status_code=503, detail="Persistent visit storage unavailable")
    if _mongo_client is None:
        with _mongo_client_lock:
            if _mongo_client is None:
                _mongo_client = pymongo.MongoClient(
                    Config.MONGODB_URI,
                    serverSelectionTimeoutMS=4000,
                    connectTimeoutMS=4000,
                    maxPoolSize=4,
                )
    return _mongo_client[Config.MONGODB_DB][Config.MONGODB_VISITS_COLLECTION]


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


def _ensure_legacy_baseline(collection, redis_client):
    """Seed the pre-persistence Redis total once, preserving the existing counter."""
    if collection.find_one({"_id": _BASELINE_ID}, {"_id": 1}):
        return
    recorded_at = datetime.now(_VISIT_TIMEZONE).isoformat(timespec="seconds")
    persisted_daily_total = sum(
        int(item.get("visits", 0))
        for item in collection.find({"_id": {"$ne": _BASELINE_ID}}, {"visits": 1})
    )
    legacy_total = _redis_count(redis_client)
    collection.update_one(
        {"_id": _BASELINE_ID},
        {"$setOnInsert": {
            "kind": "baseline",
            "timestamp": recorded_at,
            "total": max(0, legacy_total - persisted_daily_total),
        }},
        upsert=True,
    )


def _total_visit_count(collection) -> int:
    baseline = collection.find_one({"_id": _BASELINE_ID}, {"total": 1}) or {}
    daily_total = sum(
        int(item.get("visits", 0))
        for item in collection.find({"_id": {"$ne": _BASELINE_ID}}, {"visits": 1})
    )
    return int(baseline.get("total", 0)) + daily_total


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
    Read the durable count from MongoDB and refresh the Redis cache.
    """
    try:
        r = _optional_redis_client()
        collection = _visit_collection()
        _ensure_legacy_baseline(collection, r)
        count = _total_visit_count(collection)
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
    Persist one visit in the daily MongoDB bucket, then refresh Redis as a cache.
    """
    try:
        r = _optional_redis_client()
        collection = _visit_collection()
        _ensure_legacy_baseline(collection, r)
        now = datetime.now(_VISIT_TIMEZONE)
        period = now.date().isoformat()
        collection.update_one(
            {"_id": period},
            {"$inc": {"visits": 1}, "$set": {"kind": "daily", "period": period, "timestamp": now.isoformat(timespec="seconds")}},
            upsert=True,
        )
        count = _total_visit_count(collection)
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
        collection = _visit_collection()
        _ensure_legacy_baseline(collection, r)
        baseline = collection.find_one({"_id": _BASELINE_ID}) or {}
        rows = list(
            collection.find({"_id": {"$ne": _BASELINE_ID}}, {"period": 1, "visits": 1, "timestamp": 1})
            .sort("period", ASCENDING)
        )
        cumulative = int(baseline.get("total", 0))
        all_points = []
        if baseline.get("timestamp"):
            all_points.append({"timestamp": baseline["timestamp"], "date": baseline["timestamp"][:10], "visits": 0, "cumulative": cumulative})
        for row in rows:
            visits = int(row.get("visits", 0))
            cumulative += visits
            all_points.append({
                "timestamp": row.get("timestamp", f"{row.get('period', '')}T23:59:59+08:00"),
                "date": row.get("period", ""),
                "visits": visits,
                "cumulative": cumulative,
            })
        cutoff = (datetime.now(_VISIT_TIMEZONE).date() - timedelta(days=days - 1)).isoformat()
        prior_points = [point for point in all_points if point["date"] < cutoff]
        visible_points = [point for point in all_points if point["date"] >= cutoff]
        if prior_points:
            visible_points.insert(0, prior_points[-1])
        _sync_redis_cache(r, cumulative)
        return {"totalCount": cumulative, "days": days, "points": visible_points, "persisted": True}
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
