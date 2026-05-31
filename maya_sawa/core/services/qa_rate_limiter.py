import base64
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request

from ..database.connection_pool import get_pool_manager

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
ANONYMOUS_LIMIT = 1
PALAIS_LIMIT = 10

_memory_buckets: Dict[str, Tuple[int, int]] = {}


def enforce_qa_rate_limit(request: Request) -> None:
    identity, limit = _resolve_identity_and_limit(request)
    key = f"qa_rate:{identity}"
    count = _increment_bucket(key)

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail=(
                f"QA 使用頻率過高："
                f"{'已登入 Palais 使用者' if limit == PALAIS_LIMIT else '匿名/IP'}"
                f"每分鐘最多 {limit} 次，請稍後再試。"
            ),
        )


def _resolve_identity_and_limit(request: Request) -> Tuple[str, int]:
    token = _get_bearer_token(request)
    claims = _decode_jwt_payload(token) if token else None

    if claims and _has_palais_access(claims):
        subject = str(claims.get("sub") or claims.get("preferred_username") or _client_ip(request))
        return f"palais:{subject}", PALAIS_LIMIT

    return f"ip:{_client_ip(request)}", ANONYMOUS_LIMIT


def _increment_bucket(key: str) -> int:
    redis_client = get_pool_manager().get_redis_connection()
    if redis_client:
        try:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, WINDOW_SECONDS)
            return int(count)
        except Exception as exc:
            logger.warning("QA Redis rate limiter unavailable, falling back to memory: %s", exc)

    now_window = int(time.time() // WINDOW_SECONDS)
    bucket_window, count = _memory_buckets.get(key, (now_window, 0))
    if bucket_window != now_window:
        bucket_window, count = now_window, 0
    count += 1
    _memory_buckets[key] = (bucket_window, count)
    return count


def _get_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


def _decode_jwt_payload(token: str) -> Optional[Dict[str, Any]]:
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


def _has_palais_access(claims: Dict[str, Any]) -> bool:
    return _claim_has_role(claims.get("realm_access")) or any(
        _claim_has_role(client_access)
        for client_access in (claims.get("resource_access") or {}).values()
    )


def _claim_has_role(access: Any) -> bool:
    roles = access.get("roles") if isinstance(access, dict) else None
    return isinstance(roles, list) and "manage-users" in roles


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    return request.client.host if request.client else "unknown"
