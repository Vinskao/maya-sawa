"""
External API Proxy Service
Provides proxy endpoints for external APIs to bypass CORS restrictions.
"""

import os
import json
import logging
import httpx
import redis
from fastapi import APIRouter, HTTPException
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

# HTTP client with extended timeout configuration.
http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(30.0, connect=10.0),
    follow_redirects=True
)

# LeetCode official GraphQL endpoint
LEETCODE_GRAPHQL_URL = "https://leetcode.com/graphql"

# Redis cache configuration
#   *:fresh key  -> short TTL, gates whether we re-fetch from LeetCode
#   main key     -> long TTL, the fallback store returned when GraphQL fails
LEETCODE_CACHE_TTL = 7 * 24 * 3600          # 7 days fallback store
LEETCODE_FRESH_TTL = 6 * 3600               # 6 hours freshness window

# GraphQL query: solved counts per difficulty + ranking
LEETCODE_QUERY = """
query($username: String!) {
  matchedUser(username: $username) {
    submitStatsGlobal { acSubmissionNum { difficulty count } }
    profile { ranking }
  }
}
""".strip()


def _build_redis_client() -> Optional[redis.Redis]:
    """Build a Redis client mirroring the connection style used elsewhere
    (see core/services/chat_history.py). Returns None if unreachable so the
    proxy degrades gracefully instead of crashing."""
    try:
        client = redis.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_CUSTOM_PORT", 6379)),
            password=(os.getenv("REDIS_PASSWORD") or "").strip() or None,
            db=0,
            decode_responses=True,
        )
        client.ping()
        logger.info("LeetCode proxy connected to Redis")
        return client
    except Exception as e:
        logger.warning(f"LeetCode proxy Redis unavailable, caching disabled: {e}")
        return None


redis_client: Optional[redis.Redis] = _build_redis_client()


def _cache_key(username: str) -> str:
    return f"leetcode:stats:{username}"


def _fresh_key(username: str) -> str:
    return f"leetcode:stats:{username}:fresh"


def _read_cache(username: str) -> Optional[Dict[str, Any]]:
    if redis_client is None:
        return None
    try:
        raw = redis_client.get(_cache_key(username))
        return json.loads(raw) if raw else None
    except Exception as e:
        logger.warning(f"Failed to read LeetCode cache for {username}: {e}")
        return None


def _is_fresh(username: str) -> bool:
    if redis_client is None:
        return False
    try:
        return redis_client.exists(_fresh_key(username)) == 1
    except Exception:
        return False


def _write_cache(username: str, data: Dict[str, Any]) -> None:
    if redis_client is None:
        return
    try:
        payload = json.dumps(data, ensure_ascii=False)
        redis_client.set(_cache_key(username), payload, ex=LEETCODE_CACHE_TTL)
        redis_client.set(_fresh_key(username), "1", ex=LEETCODE_FRESH_TTL)
    except Exception as e:
        logger.warning(f"Failed to write LeetCode cache for {username}: {e}")


def _parse_graphql(matched_user: Dict[str, Any]) -> Dict[str, Any]:
    """Map LeetCode GraphQL response to the response shape the frontend reads
    (totalSolved / easySolved / mediumSolved / hardSolved)."""
    counts = {"All": 0, "Easy": 0, "Medium": 0, "Hard": 0}
    for item in (matched_user.get("submitStatsGlobal") or {}).get("acSubmissionNum", []):
        difficulty = item.get("difficulty")
        if difficulty in counts:
            counts[difficulty] = item.get("count", 0)

    ranking = ((matched_user.get("profile") or {}).get("ranking"))

    return {
        "totalSolved": counts["All"],
        "easySolved": counts["Easy"],
        "mediumSolved": counts["Medium"],
        "hardSolved": counts["Hard"],
        "ranking": ranking,
    }


@router.get("/leetcode-stats/{username}")
async def get_leetcode_stats(username: str):
    """
    Proxy endpoint for LeetCode statistics.

    Queries LeetCode's official GraphQL endpoint directly and caches the result
    in Redis. When GraphQL fails or rate-limits, the last cached value is
    returned (with `stale: true`) so the frontend rarely sees a blank section.

    Example:
        GET /maya-sawa/proxy/leetcode-stats/Vinskao
    """
    # Serve fresh cache without hitting LeetCode at all.
    if _is_fresh(username):
        cached = _read_cache(username)
        if cached is not None:
            logger.info(f"Serving fresh cached LeetCode stats for {username}")
            return cached

    headers = {
        "Content-Type": "application/json",
        "Referer": f"https://leetcode.com/{username}/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    body = {"query": LEETCODE_QUERY, "variables": {"username": username}}

    max_retries = 2
    response = None
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            logger.debug(f"Attempt {attempt + 1}/{max_retries + 1} fetching LeetCode GraphQL for {username}")
            response = await http_client.post(LEETCODE_GRAPHQL_URL, json=body, headers=headers)
            break
        except (httpx.TimeoutException, httpx.RequestError) as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(f"LeetCode GraphQL request failed on attempt {attempt + 1}, retrying: {e}")
                continue

    # Network-level failure across all retries -> try stale cache, else 503.
    if response is None:
        logger.error(f"LeetCode GraphQL unreachable for {username}: {last_error}")
        return _stale_or_503(username)

    if response.status_code == 200:
        try:
            payload = response.json()
        except Exception:
            payload = None

        matched_user = (payload or {}).get("data", {}).get("matchedUser") if payload else None

        if payload and matched_user is None and not (payload.get("errors")):
            # GraphQL explicitly resolved matchedUser to null -> user not found.
            logger.warning(f"LeetCode user '{username}' not found")
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "User not found",
                    "message": f"LeetCode user '{username}' does not exist",
                    "username": username,
                },
            )

        if matched_user is not None:
            result = _parse_graphql(matched_user)
            _write_cache(username, result)
            logger.info(f"Fetched fresh LeetCode stats for {username}")
            return result

        # 200 but errors / unexpected shape (e.g. rate limited inside body).
        logger.error(f"LeetCode GraphQL returned errors for {username}: {(payload or {}).get('errors')}")
        return _stale_or_503(username)

    # Non-200 (commonly 403/429 rate limiting) -> stale cache, else 503.
    logger.error(f"LeetCode GraphQL returned status {response.status_code} for {username}")
    return _stale_or_503(username)


def _stale_or_503(username: str) -> Dict[str, Any]:
    """Return the last cached value flagged as stale, or raise 503 if the
    cache is empty (cold start)."""
    cached = _read_cache(username)
    if cached is not None:
        logger.info(f"Serving stale cached LeetCode stats for {username}")
        return {**cached, "stale": True}

    raise HTTPException(
        status_code=503,
        detail={
            "error": "Service unavailable",
            "message": "LeetCode stats are temporarily unavailable and no cached data exists yet. Please try again in a few moments.",
        },
    )


@router.on_event("shutdown")
async def shutdown_event():
    """Clean up HTTP client on shutdown"""
    await http_client.aclose()
