"""Interactive Brokers Client Portal API (CPAPI v1) integration.

Unlike Shioaji (API-key based), CPAPI requires a stateful Client Portal Gateway
that is authenticated through a browser login. This service only *reads* from a
gateway that is already running and authenticated; it never handles credentials.

Caching mirrors ``shioaji_market.py``: a background loop fetches a fresh snapshot
from the gateway and writes it to Redis, and request handlers only ever read the
cached payload. Because every authenticated gateway call also resets the session
idle timer, refreshing on a short interval doubles as a keepalive, so the human
only needs to re-authenticate (2FA) when the session hard-expires (~24h).

Locally the gateway runs at https://localhost:5050 (port 5000 collides with the
macOS AirPlay receiver). In the cluster the gateway URL is provided via env.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import redis

logger = logging.getLogger(__name__)

# Live USD->TWD rate, no API key required. Falls back to FX_FALLBACK on failure.
_FX_FALLBACK_USD_TWD = 31.5


class IbkrNotConfiguredError(RuntimeError):
    """IBKR integration is disabled via configuration."""


class IbkrCacheUnavailableError(RuntimeError):
    """Redis cache is unreachable or holds no IBKR snapshot yet."""


class IbkrUnavailableError(RuntimeError):
    """Gateway is unreachable or the session is not authenticated."""


class IbkrMarketService:
    def __init__(self) -> None:
        self._refresh_task: asyncio.Task[None] | None = None
        self._cached_account_id: str | None = None
        # Keep the refresh interval below the gateway idle timeout (~6 min) so the
        # background fetch also keeps the authenticated session alive.
        self._cache_seconds = int(os.getenv("IBKR_REFRESH_SECONDS", "240"))
        self._cache_prefix = os.getenv(
            "SHIOAJI_REDIS_CACHE_PREFIX",
            "maya-sawa:market",
        )
        self._redis = redis.Redis(
            host=os.getenv("REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("REDIS_CUSTOM_PORT", 6379)),
            password=(os.getenv("REDIS_PASSWORD") or "").strip() or None,
            db=int(os.getenv("SHIOAJI_REDIS_DB", "0")),
            decode_responses=True,
        )

    @property
    def enabled(self) -> bool:
        return os.getenv("IBKR_ENABLED", "false").lower() == "true"

    @property
    def gateway_url(self) -> str:
        return os.getenv("IBKR_GATEWAY_URL", "https://localhost:5050").rstrip("/")

    @property
    def _base(self) -> str:
        return f"{self.gateway_url}/v1/api"

    # ----- public, cache-backed -------------------------------------------------

    async def get_snapshot(self) -> dict[str, Any]:
        """Return the cached IBKR snapshot (USD + TWD-converted figures)."""
        if not self.enabled:
            raise IbkrNotConfiguredError("IBKR integration is disabled")
        try:
            cached = await asyncio.to_thread(self._read_cached_payload, "IBKR")
        except redis.RedisError as exc:
            raise IbkrCacheUnavailableError("Redis cache is unavailable") from exc
        if cached is None:
            raise IbkrCacheUnavailableError("No cached IBKR snapshot available")
        return cached

    async def start_background_refresh(self) -> None:
        if not self.enabled:
            return
        if self._refresh_task is not None and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def refresh_cache_now(self) -> bool:
        try:
            snapshot = await self._fetch_snapshot_live()
        except (IbkrNotConfiguredError, IbkrUnavailableError) as exc:
            logger.warning("IBKR refresh skipped: %s", exc)
            return False
        except Exception:
            logger.exception("Unexpected error fetching IBKR snapshot")
            return False
        try:
            await asyncio.to_thread(self._write_cached_payload, "IBKR", snapshot)
        except redis.RedisError:
            logger.exception("Failed to write IBKR snapshot to Redis")
            return False
        return True

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self.refresh_cache_now()
                await asyncio.sleep(self._cache_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(self._cache_seconds)
                continue

    async def close(self) -> None:
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None

    # ----- gateway fetch --------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        # Gateway uses a self-signed cert; verify=False is expected here.
        return httpx.AsyncClient(verify=False, timeout=10.0)

    async def _resolve_account_id(self, client: httpx.AsyncClient) -> str:
        configured = os.getenv("IBKR_ACCOUNT_ID")
        if configured:
            return configured
        if self._cached_account_id:
            return self._cached_account_id
        resp = await client.get(f"{self._base}/portfolio/accounts")
        resp.raise_for_status()
        accounts = resp.json()
        if not accounts:
            raise IbkrUnavailableError("No IBKR accounts returned by the gateway")
        self._cached_account_id = str(accounts[0]["accountId"])
        return self._cached_account_id

    async def _fx_usd_twd(self, client: httpx.AsyncClient) -> tuple[float, str]:
        override = os.getenv("USD_TWD_RATE")
        if override:
            try:
                return float(override), "manual"
            except ValueError:
                logger.warning("Invalid USD_TWD_RATE=%r, ignoring", override)
        fx_url = os.getenv("IBKR_FX_URL", "https://open.er-api.com/v6/latest/USD")
        try:
            resp = await client.get(fx_url)
            resp.raise_for_status()
            rate = float(resp.json()["rates"]["TWD"])
            return rate, "live"
        except Exception as exc:  # noqa: BLE001 - fall back to a sane default
            logger.warning("USD/TWD FX fetch failed (%s); using fallback", exc)
            return _FX_FALLBACK_USD_TWD, "fallback"

    async def _fetch_snapshot_live(self) -> dict[str, Any]:
        if not self.enabled:
            raise IbkrNotConfiguredError("IBKR integration is disabled")

        async with self._client() as client:
            try:
                account_id = await self._resolve_account_id(client)
                ledger_resp = await client.get(
                    f"{self._base}/portfolio/{account_id}/ledger"
                )
                ledger_resp.raise_for_status()
                ledger = ledger_resp.json()
                summary_resp = await client.get(
                    f"{self._base}/portfolio/{account_id}/summary"
                )
                summary_resp.raise_for_status()
                summary = summary_resp.json()
            except httpx.HTTPError as exc:
                raise IbkrUnavailableError(
                    "IBKR gateway is unreachable or not authenticated"
                ) from exc

            base = ledger.get("BASE", {})

            def _amount(key: str) -> float:
                node = summary.get(key) or {}
                return float(node.get("amount") or 0.0)

            cash_usd = float(base.get("cashbalance") or _amount("totalcashvalue"))
            netliq_usd = float(
                base.get("netliquidationvalue") or _amount("netliquidation")
            )
            gross_position_usd = _amount("grosspositionvalue")
            unrealized_usd = float(base.get("unrealizedpnl") or 0.0)
            realized_usd = float(base.get("realizedpnl") or 0.0)

            rate, rate_source = await self._fx_usd_twd(client)

        return {
            "accountId": account_id,
            "baseCurrency": "USD",
            "usdTwdRate": round(rate, 4),
            "rateSource": rate_source,
            "usd": {
                "cashBalance": round(cash_usd, 2),
                "netLiquidation": round(netliq_usd, 2),
                "grossPositionValue": round(gross_position_usd, 2),
                "unrealizedPnl": round(unrealized_usd, 2),
                "realizedPnl": round(realized_usd, 2),
            },
            "twd": {
                "cashBalance": round(cash_usd * rate, 2),
                "netLiquidation": round(netliq_usd * rate, 2),
                "grossPositionValue": round(gross_position_usd * rate, 2),
                "unrealizedPnl": round(unrealized_usd * rate, 2),
            },
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Interactive Brokers CPAPI",
        }

    # ----- redis cache (mirrors shioaji_market) ---------------------------------

    def _redis_key(self, key: str) -> str:
        return f"{self._cache_prefix}:{key.lower()}"

    def _read_cached_payload(self, key: str) -> dict[str, Any] | None:
        raw = self._redis.get(self._redis_key(key))
        if not raw:
            return None
        return json.loads(raw)["payload"]

    def _write_cached_payload(self, key: str, payload: dict[str, Any]) -> None:
        envelope = {
            "cachedAt": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self._redis.set(self._redis_key(key), json.dumps(envelope, ensure_ascii=True))


def merge_ibkr_into_portfolio(
    portfolio: dict[str, Any], ibkr: dict[str, Any]
) -> dict[str, Any]:
    """Fold IBKR TWD-converted figures into a Shioaji portfolio payload.

    Adds IBKR cash, net-liquidation and unrealized P/L into the unified NT$
    totals, and records the IBKR contribution under `ibkr` for the frontend.
    Mutates and returns `portfolio`.
    """
    twd = ibkr["twd"]

    if portfolio.get("cashBalance") is not None:
        portfolio["cashBalance"] = round(portfolio["cashBalance"] + twd["cashBalance"], 2)
    if portfolio.get("totalAssetsEstimated") is not None:
        portfolio["totalAssetsEstimated"] = round(
            portfolio["totalAssetsEstimated"] + twd["netLiquidation"], 2
        )
    portfolio["totalPnl"] = round(
        portfolio.get("totalPnl", 0) + twd["unrealizedPnl"], 2
    )

    formulas = portfolio.setdefault("summaryFormulas", {})
    ibkr_cash = int(twd["cashBalance"])
    ibkr_netliq = int(twd["netLiquidation"])
    if formulas.get("cashBalance"):
        formulas["cashBalance"] = f"{formulas['cashBalance']} + IBKR {ibkr_cash:,}"
    if formulas.get("totalAssetsEstimated"):
        formulas["totalAssetsEstimated"] = (
            f"{formulas['totalAssetsEstimated']} + IBKR {ibkr_netliq:,}"
        )

    portfolio["ibkr"] = ibkr
    note = portfolio.get("valuationNote", "")
    portfolio["valuationNote"] = (
        f"{note}; includes IBKR @ {ibkr['usdTwdRate']} USD/TWD"
        if note
        else f"Includes IBKR @ {ibkr['usdTwdRate']} USD/TWD"
    )
    return portfolio


ibkr_market_service = IbkrMarketService()
