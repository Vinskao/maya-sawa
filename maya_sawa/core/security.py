"""Application-level security middleware for Maya Sawa."""

from __future__ import annotations

import ipaddress
import logging
import time
import uuid
from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth.keycloak import get_bearer_token, verify_bearer_token
from .config.config import Config
from .database.connection_pool import get_pool_manager

logger = logging.getLogger(__name__)


def _networks(value: str) -> list[ipaddress._BaseNetwork]:
    networks = []
    for item in value.split(","):
        item = item.strip()
        if item:
            networks.append(ipaddress.ip_network(item, strict=False))
    return networks


def _in_networks(address: str, networks: Iterable[ipaddress._BaseNetwork]) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self.trusted_proxies = _networks(Config.SECURITY_TRUSTED_PROXY_CIDRS)
        self.allowlist = _networks(Config.SECURITY_IP_ALLOWLIST_CIDRS)
        self.allowlist_paths = tuple(
            path.strip() for path in Config.SECURITY_IP_ALLOWLIST_PATHS.split(",") if path.strip()
        )

    async def dispatch(self, request: Request, call_next):
        started = time.monotonic()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        client_ip = self._client_ip(request)
        request.state.client_ip = client_ip

        if request.method != "OPTIONS":
            error = self._validate_request(request, client_ip)
            if error:
                error.headers["X-Request-ID"] = request_id
                return error

        try:
            response = await call_next(request)
        finally:
            elapsed_ms = (time.monotonic() - started) * 1000
            logger.info(
                "request_id=%s method=%s path=%s client_ip=%s duration_ms=%.1f",
                request_id,
                request.method,
                request.url.path,
                client_ip,
                elapsed_ms,
            )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def _validate_request(self, request: Request, client_ip: str) -> JSONResponse | None:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > Config.SECURITY_MAX_BODY_BYTES:
                    return self._error(413, "request_too_large", "Request body is too large")
            except ValueError:
                return self._error(400, "invalid_content_length", "Invalid Content-Length header")

        if self.allowlist and any(request.url.path.startswith(path) for path in self.allowlist_paths):
            if not _in_networks(client_ip, self.allowlist):
                return self._error(403, "ip_not_allowed", "Source IP is not allowed")

        claims = None
        token = get_bearer_token(request)
        if token and Config.SECURITY_ENABLED:
            try:
                claims = verify_bearer_token(token)
                request.state.user = claims
            except Exception as exc:
                status_code = getattr(exc, "status_code", 401)
                detail = getattr(exc, "detail", "Invalid bearer token")
                return self._error(status_code, "invalid_token", str(detail))

        identity = (
            f"user:{claims.get('sub')}"
            if claims and claims.get("sub")
            else f"ip:{client_ip}"
        )
        limit = (
            Config.SECURITY_AUTH_RATE_LIMIT_PER_MINUTE
            if claims
            else Config.SECURITY_PUBLIC_RATE_LIMIT_PER_MINUTE
        )
        if self._rate_limited(identity, request.url.path, limit):
            response = self._error(429, "rate_limit_exceeded", "Too many requests")
            response.headers["Retry-After"] = "60"
            return response
        return None

    def _client_ip(self, request: Request) -> str:
        peer = request.client.host if request.client else "unknown"
        if not _in_networks(peer, self.trusted_proxies):
            return peer
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
        return request.headers.get("x-real-ip", peer).strip()

    @staticmethod
    def _rate_limited(identity: str, path: str, limit: int) -> bool:
        redis_client = get_pool_manager().get_redis_connection()
        if not redis_client:
            return False
        bucket = int(time.time() // 60)
        key = f"maya-sawa:security:rate:{bucket}:{identity}:{path}"
        try:
            count = redis_client.incr(key)
            if count == 1:
                redis_client.expire(key, 120)
            return int(count) > limit
        except Exception as exc:
            logger.warning("Global Redis rate limiter unavailable: %s", exc)
            return False

    @staticmethod
    def _error(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={"success": False, "error": {"code": code, "message": message}},
        )
