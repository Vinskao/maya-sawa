"""RunPod cost observability endpoints.

Two surfaces, mirroring the market router:
- ``/runpod/cost``           : authenticated (Keycloak bearer) for direct use.
- ``/runpod/internal/cost``  : internal secret, for the frontend SSR proxy.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth.internal import require_internal_secret
from ..core.auth.keycloak import require_authenticated
from ..services.runpod_cost import (
    RunpodNotConfiguredError,
    RunpodUnavailableError,
    runpod_cost_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runpod", tags=["RunPod Cost"])


async def _cost_overview() -> dict:
    try:
        return await runpod_cost_service.get_cost_overview()
    except RunpodNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except RunpodUnavailableError as exc:
        logger.warning("RunPod cost fetch failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "upstream_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001 - surface as 500 with stable shape
        logger.exception("Unexpected error fetching RunPod cost")
        raise HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": "Failed to fetch RunPod cost"},
        ) from exc


@router.get("/cost")
async def get_runpod_cost(_claims: dict = Depends(require_authenticated)):
    return await _cost_overview()


@router.get("/internal/cost")
async def get_runpod_cost_internal(_=Depends(require_internal_secret)):
    return await _cost_overview()
