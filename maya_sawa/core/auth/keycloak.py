"""Keycloak JWT validation helpers for FastAPI endpoints."""

from __future__ import annotations

import base64
import json
import time
import logging
from typing import Any, Dict, Iterable, Optional

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives import hashes
from fastapi import Header, HTTPException, Request, status

from ..config.config import Config

logger = logging.getLogger(__name__)

_JWKS_CACHE: Dict[str, Any] = {"expires_at": 0, "keys": []}


def _b64url_decode(value: str) -> bytes:
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _decode_json_part(value: str) -> Dict[str, Any]:
    return json.loads(_b64url_decode(value).decode("utf-8"))


def _jwk_set_uri() -> str:
    base = Config.KEYCLOAK_AUTH_SERVER_URL.rstrip("/")
    return f"{base}/realms/{Config.KEYCLOAK_REALM}/protocol/openid-connect/certs"


def _issuer() -> str:
    base = Config.KEYCLOAK_AUTH_SERVER_URL.rstrip("/")
    return f"{base}/realms/{Config.KEYCLOAK_REALM}"


def _get_jwks() -> Iterable[Dict[str, Any]]:
    now = time.time()
    if _JWKS_CACHE["keys"] and _JWKS_CACHE["expires_at"] > now:
        return _JWKS_CACHE["keys"]

    response = httpx.get(_jwk_set_uri(), timeout=5.0)
    response.raise_for_status()
    keys = response.json().get("keys", [])
    _JWKS_CACHE.update({"keys": keys, "expires_at": now + 3600})
    return keys


def _find_key(kid: Optional[str]) -> Dict[str, Any]:
    for key in _get_jwks():
        if key.get("kid") == kid:
            return key
    _JWKS_CACHE.update({"keys": [], "expires_at": 0})
    for key in _get_jwks():
        if key.get("kid") == kid:
            return key
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown token key")


def _public_key_from_jwk(jwk: Dict[str, Any]) -> rsa.RSAPublicKey:
    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    return rsa.RSAPublicNumbers(e, n).public_key()


def _verify_rs256(token: str) -> Dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = _decode_json_part(header_part)
        payload = _decode_json_part(payload_part)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    if header.get("alg") != "RS256":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unsupported token algorithm")

    jwk = _find_key(header.get("kid"))
    public_key = _public_key_from_jwk(jwk)
    signed = f"{header_part}.{payload_part}".encode("ascii")
    signature = _b64url_decode(signature_part)

    try:
        public_key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token signature") from exc

    now = int(time.time())
    if payload.get("exp") and int(payload["exp"]) < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    if payload.get("nbf") and int(payload["nbf"]) > now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token not active yet")
    if payload.get("iss") != _issuer():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token issuer")
    audience = payload.get("aud", [])
    audiences = {audience} if isinstance(audience, str) else set(audience or [])
    if Config.KEYCLOAK_CLIENT_ID not in audiences and payload.get("azp") != Config.KEYCLOAK_CLIENT_ID:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token audience")

    return payload


def _extract_roles(payload: Dict[str, Any]) -> set[str]:
    roles: set[str] = set()
    realm_access = payload.get("realm_access")
    if isinstance(realm_access, dict) and isinstance(realm_access.get("roles"), list):
        roles.update(str(role) for role in realm_access["roles"])

    resource_access = payload.get("resource_access")
    if isinstance(resource_access, dict):
        for client_access in resource_access.values():
            if isinstance(client_access, dict) and isinstance(client_access.get("roles"), list):
                roles.update(str(role) for role in client_access["roles"])

    return roles


def get_bearer_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return None


def verify_bearer_token(token: str) -> Dict[str, Any]:
    payload = _verify_rs256(token)
    roles = _extract_roles(payload)
    payload["_roles"] = sorted(roles)
    payload["_is_manage_users"] = Config.GIT_COMMIT_REQUIRED_ROLE in roles
    return payload


def _subject(payload: Dict[str, Any], request: Request) -> str:
    subject = payload.get("sub") or payload.get("preferred_username") or payload.get("email")
    if subject:
        return str(subject)

    # Fall back to the IP resolved by SecurityMiddleware (trusted-proxy aware)
    # rather than re-parsing the spoofable X-Forwarded-For header here.
    resolved = getattr(request.state, "client_ip", None)
    if resolved:
        return str(resolved)

    return request.client.host if request.client else "unknown"


async def require_git_commit_access(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    token = authorization.split(" ", 1)[1].strip()
    return verify_bearer_token(token)


async def require_manage_users(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")

    token = authorization.split(" ", 1)[1].strip()
    payload = _verify_rs256(token)
    roles = _extract_roles(payload)
    required_role = Config.GIT_COMMIT_REQUIRED_ROLE
    if required_role not in roles:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires {required_role} role")

    return payload


async def require_authenticated(request: Request) -> Dict[str, Any]:
    claims = getattr(request.state, "user", None)
    if claims:
        return claims

    token = get_bearer_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    return verify_bearer_token(token)


async def require_manage_users_request(request: Request) -> Dict[str, Any]:
    payload = await require_authenticated(request)
    required_role = Config.GIT_COMMIT_REQUIRED_ROLE
    if required_role not in set(payload.get("_roles", [])):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Requires {required_role} role")
    return payload
