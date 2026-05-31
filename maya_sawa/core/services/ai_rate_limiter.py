"""Shared rate limits for endpoints that call AI or embedding providers."""

from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Tuple

from fastapi import HTTPException, Request, status

from ..auth.keycloak import get_bearer_token, verify_bearer_token
from ..config.config import Config
from ..database.connection_pool import get_pool_manager

logger = logging.getLogger(__name__)

_memory_buckets: Dict[str, Tuple[int, int]] = {}


def enforce_ai_rate_limit(request: Request, *, allow_anonymous: bool) -> Optional[dict]:
    token = get_bearer_token(request)
    claims = verify_bearer_token(token) if token else None

    if claims:
        is_manager = bool(claims.get("_is_manage_users"))
        limit = Config.AI_RATE_LIMIT_MANAGER_PER_MINUTE if is_manager else Config.AI_RATE_LIMIT_STANDARD_PER_MINUTE
        identity = f"token:{_subject_from_claims(claims)}"
    else:
        if not allow_anonymous:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
        limit = Config.AI_RATE_LIMIT_ANONYMOUS_PER_MINUTE
        identity = f"ip:{_client_ip(request)}"

    count = _increment_bucket(f"ai_rate:{identity}")
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"AI API rate limit exceeded. Limit is {limit} request(s) per minute.",
        )

    return claims


def _increment_bucket(key: str) -> int:
    redis_client = get_pool_manager().get_redis_connection()
    if redis_client:
        try:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, Config.AI_RATE_LIMIT_WINDOW_SECONDS)
            return int(count)
        except Exception as exc:
            logger.warning("AI Redis rate limiter unavailable, falling back to memory: %s", exc)

    now_window = int(time.time() // Config.AI_RATE_LIMIT_WINDOW_SECONDS)
    bucket_window, count = _memory_buckets.get(key, (now_window, 0))
    if bucket_window != now_window:
        bucket_window, count = now_window, 0
    count += 1
    _memory_buckets[key] = (bucket_window, count)
    return count


def _subject_from_claims(claims: dict) -> str:
    return str(
        claims.get("sub")
        or claims.get("preferred_username")
        or claims.get("email")
        or "unknown"
    )


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"
