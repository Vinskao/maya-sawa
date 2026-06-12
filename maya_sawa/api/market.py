import logging

from fastapi import APIRouter, HTTPException

from ..services.shioaji_market import (
    ShioajiCacheUnavailableError,
    ShioajiNotConfiguredError,
    shioaji_market_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["market"])


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
async def get_portfolio():
    if not shioaji_market_service.portfolio_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "portfolio_disabled",
                "message": "Portfolio dashboard is disabled",
            },
        )
    try:
        return await shioaji_market_service.get_portfolio()
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


@router.get("/usage")
async def get_market_usage():
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
