"""
Voyeur API Endpoints
Migrated from Voyeur Django project.
Contains Visit and Queue functionality using Redis.
"""

from fastapi import APIRouter, HTTPException, Form, Request
from fastapi.responses import JSONResponse
import logging
from typing import Optional

from ..core.database.connection_pool import get_pool_manager
from ..core.config.config import Config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voyeur", tags=["Voyeur"])

@router.get("/count/")
async def get_visit_count():
    """
    Get current visit count from Redis.
    Matches Django VisitCountView.
    """
    try:
        r = get_pool_manager().get_redis_connection()
        if not r:
             raise HTTPException(status_code=503, detail="Redis connection unavailable")
             
        count = r.get('visit_count')
        logger.info(f"Current visit count: {count}")
        if count is None:
            count = 0
        return {'count': int(count)}
    except Exception as e:
        logger.error(f"Error getting visit count: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/increment/")
async def increment_visit_count():
    """
    Increment visit count in Redis.
    Matches Django IncrementView.
    """
    try:
        r = get_pool_manager().get_redis_connection()
        if not r:
             raise HTTPException(status_code=503, detail="Redis connection unavailable")

        count = r.incr('visit_count')
        logger.info(f"Incremented visit count to: {count}")
        return {'count': int(count)}
    except Exception as e:
        logger.error(f"Error incrementing visit count: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

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
