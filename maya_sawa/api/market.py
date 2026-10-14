import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field

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
from ..databases.market_dashboard_db import market_dashboard_db
from ..databases.market_history_db import market_history_db
from ..services.market_history_collector import market_history_collector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["market"])


class DashboardCustomSelection(BaseModel):
    symbols: list[dict[str, str]] = Field(max_length=5)


@router.get("/dashboard")
async def get_market_dashboard():
    """Public, privacy-safe selection and live quotes; never returns account values."""
    auto = market_dashboard_db.latest_auto()
    custom = market_dashboard_db.custom_symbols()
    seen: set[str] = set()
    auto_rows = []
    for item in auto["positions"]:
        key = item["code"].upper()
        if key not in seen:
            seen.add(key)
            auto_rows.append(item)
    custom_rows = []
    for item in custom:
        key = (item["productType"], item["code"].upper())
        if key not in seen:
            seen.add(key)
            custom_rows.append(item)
    quotes: dict[tuple[str, str], dict] = {}
    try:
        rows = await shioaji_market_service.get_dashboard_quotes(auto_rows + custom_rows)
        quotes = {(item["productType"], item["symbol"].upper()): item for item in rows}
    except Exception as exc:
        logger.info("Market selection quotes unavailable: %s", exc)
    try:
        txf = await shioaji_market_service.get_taiex_futures_quote()
    except Exception:
        txf = None
    def expose(item: dict) -> dict:
        return {**item, "quote": quotes.get((item["productType"], item["code"].upper()))}
    return {
        "fixed": {"code": "TXF", "name": "TAIEX Futures · front month", "productType": "futures", "quote": txf},
        "automatic": {"snapshotAt": auto["snapshotAt"], "positions": [expose(item) for item in auto_rows]},
        "custom": [expose(item) for item in custom_rows],
        "customLimit": 5,
    }


@router.get("/dashboard/search")
async def search_market_contracts(q: str, productType: str | None = None,
                                 _claims: dict = Depends(require_manage_users_request)):
    if productType not in (None, "stock", "futures"):
        raise HTTPException(status_code=422, detail="productType must be stock or futures")
    try:
        results = await shioaji_market_service.search_contracts(q[:40], productType)
        # Searchable Shioaji contracts form the candidate universe until
        # external source-list ingestion is configured and verified.
        market_dashboard_db.record_candidates("shioaji-search", results)
        return {"results": results}
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail={"code": "not_configured", "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Market contract search failed")
        raise HTTPException(status_code=502, detail="Market contract search unavailable") from exc


@router.get("/dashboard/custom")
async def get_market_dashboard_custom(_claims: dict = Depends(require_manage_users_request)):
    return {"symbols": market_dashboard_db.custom_symbols(), "limit": 5}


@router.get("/dashboard/candidates")
async def get_market_dashboard_candidates(q: str = "", limit: int = 100,
                                         _claims: dict = Depends(require_manage_users_request)):
    return {"results": market_dashboard_db.list_candidates(q[:40], min(max(limit, 1), 200))}


@router.get("/dashboard/history/{code}")
async def get_market_dashboard_history(code: str, start: date | None = None, end: date | None = None,
                                      view: str = "daily"):
    """Public daily price and chip history; no account or portfolio fields are exposed."""
    normalized = code.strip().upper()
    if not normalized or len(normalized) > 24 or not normalized.replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid instrument code")
    end_date = end or datetime.now(ZoneInfo("Asia/Taipei")).date()
    start_date = start or (end_date - timedelta(days=92))
    if start_date > end_date or (end_date - start_date).days > 366:
        raise HTTPException(status_code=422, detail="History range must be within 366 days")
    sources = ["tdcc:distribution-history", "twse:foreign-holding", "tpex:foreign-holding"] if view == "ownership" else None
    if view not in {"daily", "ownership"}:
        raise HTTPException(status_code=422, detail="view must be daily or ownership")
    result = market_history_db.history(normalized, start_date, end_date, sources=sources)
    return {"code": normalized, "view": view, "start": start_date.isoformat(), "end": end_date.isoformat(), **result}


@router.put("/dashboard/custom")
async def put_market_dashboard_custom(body: DashboardCustomSelection,
                                      _claims: dict = Depends(require_manage_users_request)):
    seen: set[str] = set()
    normalized = []
    automatic = {item["code"].upper() for item in market_dashboard_db.latest_auto()["positions"]}
    for item in body.symbols:
        code, name, kind = (str(item.get(key, "")).strip() for key in ("code", "name", "productType"))
        key = code.upper()
        if kind not in ("stock", "futures") or not code or not name:
            raise HTTPException(status_code=422, detail="Each selection requires a valid code, name and productType")
        if key not in seen:
            if key in automatic or (kind == "futures" and code.upper() == "TXF"):
                raise HTTPException(status_code=422, detail=f"{code} is already in the fixed or automatic selection")
            search_error = None
            try:
                matches = await shioaji_market_service.search_contracts(code, kind)
            except Exception as exc:
                logger.exception("Unable to validate dashboard custom instrument")
                matches = []
                search_error = exc
            match = next((result for result in matches if result["code"].upper() == code.upper()), None)
            if (not match and kind == "futures" and code.upper().endswith(("R1", "R2"))
                    and matches):
                # Resolve legacy/custom rolling aliases to the current listed
                # month returned by the contract directory.
                match = matches[0]
            if not match:
                # Historical candidates remain selectable after a contract
                # leaves the current directory; live quotes may be absent.
                match = market_dashboard_db.find_candidate(kind, code)
            if not match:
                if search_error:
                    raise HTTPException(status_code=503, detail="Instrument validation is temporarily unavailable") from search_error
                raise HTTPException(status_code=422, detail=f"Unknown {kind} contract: {code}")
            seen.add(key)
            normalized.append({"code": code.upper(), "name": match["name"], "productType": kind,
                               **({"deliveryMonth": match["deliveryMonth"]} if match.get("deliveryMonth") else {})})
    if len(normalized) > 5:
        raise HTTPException(status_code=422, detail="At most five custom instruments are allowed")
    try:
        market_dashboard_db.save_custom_symbols(normalized)
        await market_history_collector.enqueue_codes(
            [item["code"] for item in normalized if item["productType"] == "stock"]
        )
        await market_history_collector.enqueue_futures(
            [item for item in normalized if item["productType"] == "futures"]
        )
    except Exception as exc:
        logger.exception("Failed to save market dashboard settings")
        raise HTTPException(status_code=503, detail="Market dashboard settings unavailable") from exc
    return {"symbols": market_dashboard_db.custom_symbols(), "limit": 5}


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

    try:
        fixed_quote = await shioaji_market_service.get_taiex_futures_quote()
    except Exception:
        fixed_quote = None
        logger.info("Fixed TXF quote unavailable while refreshing public automatic selection")
    try:
        await asyncio.to_thread(market_dashboard_db.record_portfolio, portfolio,
                                 fixed_quote.get("symbol") if fixed_quote else None)
    except Exception:
        logger.exception("Failed to update public automatic market selection")

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
        # A dashboard read can be the first successful access after the market
        # close. Persist the valid Taiwan source snapshot before returning it,
        # so the following history request can include today's daily point.
        await asyncio.to_thread(portfolio_history_db.record_taiwan, portfolio)
    except Exception:
        logger.exception("Failed to record Taiwan portfolio daily point (non-fatal)")

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
