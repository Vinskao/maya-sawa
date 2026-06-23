import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from ..core.auth.keycloak import require_authenticated, require_manage_users_request
from ..core.auth.internal import require_internal_secret

from ..services.shioaji_market import (
    ShioajiCacheUnavailableError,
    ShioajiNotConfiguredError,
    shioaji_market_service,
)
from ..services.ibkr_market import (
    IbkrCacheUnavailableError,
    IbkrNotConfiguredError,
    IbkrUnavailableError,
    attach_taiwan_only_regions,
    ibkr_market_service,
    merge_ibkr_into_portfolio,
)
from ..databases.portfolio_history_db import portfolio_history_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["market"])


async def _portfolio_with_ibkr() -> dict:
    """Shioaji portfolio with IBKR folded in when enabled and reachable.

    Read policy: Redis cache first (via the Shioaji service); if the cache is
    empty, fall back to the latest Postgres history snapshot. IBKR failures never
    break the base portfolio. A throttled history snapshot is recorded on the way
    out so the DB accrues a time series.
    """
    try:
        portfolio = await shioaji_market_service.get_portfolio()
    except ShioajiCacheUnavailableError:
        snapshot = await asyncio.to_thread(portfolio_history_db.latest_snapshot)
        if snapshot is not None:
            logger.info("Serving portfolio from Postgres history (Redis cache empty)")
            return snapshot
        raise

    if not ibkr_market_service.enabled:
        merged = attach_taiwan_only_regions(portfolio)
    else:
        try:
            ibkr_snapshot = await ibkr_market_service.get_snapshot()
            merged = merge_ibkr_into_portfolio(portfolio, ibkr_snapshot)
        except (IbkrNotConfiguredError, IbkrUnavailableError, IbkrCacheUnavailableError) as exc:
            logger.warning("Skipping IBKR merge: %s", exc)
            merged = attach_taiwan_only_regions(portfolio)
        except Exception:
            logger.exception("Unexpected error merging IBKR portfolio")
            merged = attach_taiwan_only_regions(portfolio)

    try:
        await asyncio.to_thread(portfolio_history_db.record_if_due, merged)
    except Exception:
        logger.exception("Failed to record portfolio history (non-fatal)")
    return merged


@router.get("/auth-status")
async def get_market_auth_status(
    claims: dict = Depends(require_manage_users_request),
):
    return {
        "authenticated": True,
        "subject": claims.get("preferred_username") or claims.get("sub"),
        "roles": claims.get("_roles", []),
        "clientId": claims.get("azp"),
        "audience": claims.get("aud"),
    }


@router.get("/taiex-futures")
async def get_taiex_futures_quote():
    try:
        return await shioaji_market_service.get_taiex_futures_quote()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch TXF quote")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "quote_unavailable",
                "message": "Taiex futures quote is temporarily unavailable",
            },
        ) from exc


@router.get("/mini-tsmc-futures")
async def get_mini_tsmc_futures_quote():
    try:
        return await shioaji_market_service.get_mini_tsmc_futures_quote()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch QFFR1 quote")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "quote_unavailable",
                "message": "Mini TSMC futures quote is temporarily unavailable",
            },
        ) from exc


@router.get("/portfolio")
async def get_portfolio(_claims: dict = Depends(require_manage_users_request)):
    if not shioaji_market_service.portfolio_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "portfolio_disabled",
                "message": "Portfolio dashboard is disabled",
            },
        )
    try:
        return await _portfolio_with_ibkr()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch portfolio")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "portfolio_unavailable",
                "message": "Portfolio data is temporarily unavailable",
            },
        ) from exc


@router.get("/ibkr")
async def get_ibkr_snapshot(_claims: dict = Depends(require_manage_users_request)):
    return await _ibkr_snapshot_or_503()


@router.get("/internal/ibkr")
async def get_ibkr_snapshot_internal(_=Depends(require_internal_secret)):
    return await _ibkr_snapshot_or_503()


async def _ibkr_snapshot_or_503() -> dict:
    try:
        return await ibkr_market_service.get_snapshot()
    except IbkrNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except IbkrUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "gateway_unavailable", "message": str(exc)},
        ) from exc
    except IbkrCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch IBKR snapshot")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ibkr_unavailable",
                "message": "IBKR data is temporarily unavailable",
            },
        ) from exc


@router.get("/portfolio/history")
async def get_portfolio_history(
    limit: int = 90, _claims: dict = Depends(require_manage_users_request)
):
    return await _portfolio_history(limit)


@router.get("/internal/portfolio/history")
async def get_portfolio_history_internal(limit: int = 90, _=Depends(require_internal_secret)):
    return await _portfolio_history(limit)


async def _portfolio_history(limit: int) -> dict:
    try:
        rows = await asyncio.to_thread(portfolio_history_db.history, limit)
    except Exception as exc:
        logger.exception("Failed to read portfolio history")
        raise HTTPException(
            status_code=503,
            detail={"code": "history_unavailable", "message": "Portfolio history unavailable"},
        ) from exc
    return {"count": len(rows), "history": rows}


@router.get("/usage")
async def get_market_usage(_claims: dict = Depends(require_manage_users_request)):
    try:
        return await shioaji_market_service.get_usage()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch Shioaji usage")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "usage_unavailable",
                "message": "Shioaji usage is temporarily unavailable",
            },
        ) from exc


@router.get("/internal/usage")
async def get_market_usage_internal(_=Depends(require_internal_secret)):
    try:
        return await shioaji_market_service.get_usage()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch Shioaji usage (internal)")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "usage_unavailable",
                "message": "Shioaji usage is temporarily unavailable",
            },
        ) from exc


@router.get("/internal/portfolio")
async def get_portfolio_internal(_=Depends(require_internal_secret)):
    if not shioaji_market_service.portfolio_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "portfolio_disabled",
                "message": "Portfolio dashboard is disabled",
            },
        )
    try:
        return await _portfolio_with_ibkr()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch portfolio (internal)")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "portfolio_unavailable",
                "message": "Portfolio data is temporarily unavailable",
            },
        ) from exc
