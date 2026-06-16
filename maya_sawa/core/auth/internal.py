import os
from fastapi import Header, HTTPException


async def require_internal_secret(x_internal_secret: str = Header(...)):
    """Verify internal service-to-service communication."""
    expected_secret = os.environ.get("MARKET_INTERNAL_SECRET")

    if not expected_secret:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": "Internal market access is not configured"},
        )

    if not x_internal_secret or x_internal_secret != expected_secret:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "Invalid internal secret"},
        )
