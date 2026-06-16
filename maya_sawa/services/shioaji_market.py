import asyncio
import json
import os
import time
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import redis


TAIPEI_TZ = ZoneInfo("Asia/Taipei")


class ShioajiNotConfiguredError(RuntimeError):
    pass


class ShioajiCacheUnavailableError(RuntimeError):
    pass


class ReadOnlyShioajiClient:
    """Expose only the Shioaji capabilities used by the market dashboard."""

    def __init__(self, api: Any, share_unit: Any = None) -> None:
        self._api = api
        self._share_unit = share_unit
        self.Contracts = api.Contracts
        self.stock_account = api.stock_account
        self.futopt_account = api.futopt_account

    def snapshots(self, contracts: list[Any]) -> Any:
        return self._api.snapshots(contracts)

    def usage(self) -> Any:
        return self._api.usage()

    def account_balance(self, account: Any) -> Any:
        return self._api.account_balance(account=account)

    def list_positions(self, account: Any) -> Any:
        return self._api.list_positions(account=account)

    def list_stock_positions(self) -> Any:
        return self._api.list_positions(
            account=self.stock_account,
            unit=self._share_unit,
        )

    def list_futures_positions(self) -> Any:
        return self._api.list_positions(account=self.futopt_account)

    def margin(self) -> Any:
        return self._api.margin(account=self.futopt_account)

    def logout(self) -> Any:
        return self._api.logout()


class ShioajiMarketService:
    def __init__(self) -> None:
        self._api: Any = None
        self._login_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._cache_seconds = int(os.getenv("SHIOAJI_QUOTE_CACHE_SECONDS", "600"))
        self._portfolio_cache_seconds = int(
            os.getenv("SHIOAJI_PORTFOLIO_CACHE_SECONDS", "3600")
        )
        self._last_portfolio_refresh = 0.0
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
    def configured(self) -> bool:
        return bool(os.getenv("SHIOAJI_API_KEY") and os.getenv("SHIOAJI_SECRET_KEY"))

    @property
    def portfolio_enabled(self) -> bool:
        # Account data is opt-in because the public dashboard has no user login.
        return os.getenv("SHIOAJI_PORTFOLIO_ENABLED", "false").lower() == "true"

    async def get_taiex_futures_quote(self) -> dict[str, Any]:
        return await self._get_cached_payload("TXF")

    async def get_mini_tsmc_futures_quote(self) -> dict[str, Any]:
        return await self._get_cached_payload("QFFR1")

    async def get_portfolio(self) -> dict[str, Any]:
        return await self._get_cached_payload("PORTFOLIO")

    async def get_usage(self) -> dict[str, Any]:
        return await self._get_cached_payload("USAGE")

    async def _get_cached_payload(self, key: str) -> dict[str, Any]:
        try:
            cached = await asyncio.to_thread(self._read_cached_payload, key)
        except redis.RedisError as exc:
            raise ShioajiCacheUnavailableError(
                "Redis market cache is unavailable"
            ) from exc
        if cached is not None:
            return cached
        raise ShioajiCacheUnavailableError(
            f"No cached market data available for {key}"
        )

    async def start_background_refresh(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            return

        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def refresh_cache_now(self) -> None:
        await self._refresh_payload("TXF", self._fetch_txf_quote)
        await self._refresh_payload("QFFR1", self._fetch_qff_quote)
        await self._refresh_payload("USAGE", self._fetch_usage_payload)
        portfolio_due = (
            time.monotonic() - self._last_portfolio_refresh
            >= self._portfolio_cache_seconds
        )
        if self.portfolio_enabled and portfolio_due:
            refreshed = await self._refresh_payload("PORTFOLIO", self._fetch_portfolio)
            if refreshed:
                self._last_portfolio_refresh = time.monotonic()

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
        await self._reset_api()

    async def _refresh_payload(self, key: str, fetcher: Any) -> bool:
        try:
            payload = await self._run_with_relogin(fetcher)
        except Exception:
            return False
        try:
            await asyncio.to_thread(self._write_cached_payload, key, payload)
        except redis.RedisError:
            return False
        return True

    async def _run_with_relogin(self, operation: Any) -> Any:
        async with self._request_lock:
            api = await self._get_api()
            try:
                return await asyncio.to_thread(operation, api)
            except Exception:
                # Shioaji sessions can be invalidated by another login using the
                # same key. Recreate the session once before surfacing the error.
                await self._reset_api()
                api = await self._get_api()
                return await asyncio.to_thread(operation, api)

    async def _reset_api(self) -> None:
        async with self._login_lock:
            api = self._api
            self._api = None
            if api is not None:
                try:
                    await asyncio.to_thread(api.logout)
                except Exception:
                    pass

    async def _get_api(self) -> Any:
        if self._api is not None:
            return self._api
        if not self.configured:
            raise ShioajiNotConfiguredError(
                "SHIOAJI_API_KEY and SHIOAJI_SECRET_KEY are required"
            )

        async with self._login_lock:
            if self._api is not None:
                return self._api
            self._api = await asyncio.to_thread(self._login)
            return self._api

    @staticmethod
    def _login() -> Any:
        try:
            import shioaji as sj
        except ImportError as exc:
            raise RuntimeError("Shioaji is not installed") from exc

        api = sj.Shioaji(simulation=os.getenv("SHIOAJI_SIMULATION", "false").lower() == "true")
        api.login(
            api_key=os.environ["SHIOAJI_API_KEY"],
            secret_key=os.environ["SHIOAJI_SECRET_KEY"],
            fetch_contract=True,
        )
        return ReadOnlyShioajiClient(api, share_unit=sj.Unit.Share)

    @staticmethod
    def _fetch_txf_quote(api: Any) -> dict[str, Any]:
        contract = ShioajiMarketService._nearest_txf_contract(api)
        return ShioajiMarketService._snapshot_payload(api, contract)

    @staticmethod
    def _fetch_qff_quote(api: Any) -> dict[str, Any]:
        contract = ShioajiMarketService._mini_tsmc_contract(api)
        return ShioajiMarketService._snapshot_payload(api, contract)

    @staticmethod
    def _snapshot_payload(api: Any, contract: Any) -> dict[str, Any]:
        snapshot = api.snapshots([contract])[0]

        close = float(snapshot.close or 0)
        change = float(getattr(snapshot, "change_price", 0) or 0)
        change_percent = float(getattr(snapshot, "change_rate", 0) or 0)

        return {
            "symbol": contract.code,
            "name": getattr(contract, "name", "臺股期貨"),
            "deliveryMonth": getattr(contract, "delivery_month", None),
            "close": close,
            "open": float(snapshot.open or 0),
            "high": float(snapshot.high or 0),
            "low": float(snapshot.low or 0),
            "change": change,
            "changePercent": change_percent,
            "volume": int(snapshot.total_volume or snapshot.volume or 0),
            "timestamp": ShioajiMarketService._format_timestamp(snapshot.ts),
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Sinopac Shioaji",
        }

    @staticmethod
    def _fetch_usage_payload(api: Any) -> dict[str, Any]:
        usage = api.usage()
        mb = 1024 * 1024
        return {
            "connections": int(getattr(usage, "connections", 0) or 0),
            "bytes": int(getattr(usage, "bytes", 0) or 0),
            "limitBytes": int(getattr(usage, "limit_bytes", 0) or 0),
            "remainingBytes": int(getattr(usage, "remaining_bytes", 0) or 0),
            "usedMb": round((getattr(usage, "bytes", 0) or 0) / mb, 2),
            "limitMb": round((getattr(usage, "limit_bytes", 0) or 0) / mb, 2),
            "remainingMb": round((getattr(usage, "remaining_bytes", 0) or 0) / mb, 2),
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Sinopac Shioaji",
        }

    @staticmethod
    def _fetch_portfolio(api: Any) -> dict[str, Any]:
        balance = None
        balance_error = None
        try:
            balance = api.account_balance(account=api.stock_account)
        except Exception as exc:
            balance_error = ShioajiMarketService._public_account_error(exc)
        cash = (
            float(getattr(balance, "acc_balance", 0) or 0)
            if balance is not None
            else None
        )
        try:
            stock_positions = api.list_stock_positions()
        except Exception as exc:
            stock_positions = []
            stock_error = ShioajiMarketService._public_account_error(exc)
        else:
            stock_error = None

        positions: list[dict[str, Any]] = []
        for position in stock_positions:
            quantity = int(getattr(position, "quantity", 0) or 0)
            average_price = float(getattr(position, "price", 0) or 0)
            pnl = float(getattr(position, "pnl", 0) or 0)
            cost_value = average_price * quantity
            market_value = max(cost_value + pnl, 0)
            last_price = market_value / quantity if quantity else 0
            code = str(getattr(position, "code", ""))
            try:
                stock_name = str(getattr(api.Contracts.Stocks[code], "name", "") or "")
            except Exception:
                stock_name = ""
            positions.append(
                ShioajiMarketService._position_payload(
                    position,
                    "stock",
                    market_value,
                    last_price=last_price,
                    name=stock_name,
                )
            )

        total_position_exposure = sum(item["marketValue"] for item in positions)
        total_pnl = sum(item["pnl"] for item in positions)
        total_assets = (
            cash + total_position_exposure
            if cash is not None
            else None
        )
        percentage_base = total_assets or total_position_exposure
        for item in positions:
            item["assetPercentage"] = (
                round(item["marketValue"] / percentage_base * 100, 2)
                if percentage_base > 0
                else 0
            )

        # === Futures (futopt) positions and equity/margin ===
        futures_positions, futures_error = ShioajiMarketService._fetch_futures_positions(api)
        futures_summary = ShioajiMarketService._fetch_futures_summary(api, len(futures_positions))

        account_errors = {
            key: value
            for key, value in {"stock": stock_error, "futures": futures_error}.items()
            if value
        }

        return {
            "cashBalance": cash,
            "balanceAvailable": balance is not None,
            "balanceError": balance_error,
            "accountErrors": account_errors,
            "balanceDate": str(getattr(balance, "date", "") or "") if balance else "",
            "totalAssetsEstimated": round(total_assets, 2) if total_assets is not None else None,
            "totalPositionExposure": round(total_position_exposure, 2),
            "totalPnl": round(total_pnl, 2),
            "positionCount": len(positions),
            "cashPercentage": (
                round(cash / total_assets * 100, 2)
                if cash is not None and total_assets and total_assets > 0
                else 0
            ),
            # `positions` keeps stock holdings for backward compatibility; the
            # dashboard reads `stockPositions` / `futuresPositions` explicitly.
            "positions": positions,
            "stockPositions": positions,
            "futuresPositions": futures_positions,
            "futuresSummary": futures_summary,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Sinopac Shioaji",
            "valuationNote": (
                "Stock cash plus stock market value"
                if cash is not None
                else "Stock market value only; cash balance unavailable"
            ),
        }

    @staticmethod
    def _fetch_futures_positions(api: Any) -> tuple[list[dict[str, Any]], str | None]:
        try:
            raw_positions = api.list_futures_positions()
        except Exception as exc:
            return [], ShioajiMarketService._public_account_error(exc)

        futures_positions: list[dict[str, Any]] = []
        for position in raw_positions:
            code = str(getattr(position, "code", ""))
            # `last_price` is not guaranteed on a futures Position object; fall back
            # to a contract snapshot so the dashboard can show the current price.
            last_price = float(getattr(position, "last_price", 0) or 0)
            contract = None
            try:
                contract = api.Contracts.Futures[code]
            except Exception:
                contract = None
            if not last_price and contract is not None:
                try:
                    last_price = float(api.snapshots([contract])[0].close or 0)
                except Exception:
                    last_price = 0.0
            futures_name = str(getattr(contract, "name", "") or "") if contract is not None else ""
            futures_positions.append(
                ShioajiMarketService._position_payload(
                    position,
                    "futures",
                    market_value=0.0,  # futures are margin instruments, no stock-style market value
                    last_price=last_price,
                    name=futures_name,
                )
            )
        return futures_positions, None

    @staticmethod
    def _fetch_futures_summary(api: Any, position_count: int) -> dict[str, Any] | None:
        try:
            margin = api.margin()
        except Exception:
            return None
        return {
            "equity": float(getattr(margin, "equity", 0) or 0),
            "equityAmount": float(getattr(margin, "equity_amount", 0) or 0),
            "availableMargin": float(getattr(margin, "available_margin", 0) or 0),
            "openPositionPnl": float(getattr(margin, "future_open_position", 0) or 0),
            "initialMargin": float(getattr(margin, "initial_margin", 0) or 0),
            "maintenanceMargin": float(getattr(margin, "maintenance_margin", 0) or 0),
            "riskIndicator": float(getattr(margin, "risk_indicator", 0) or 0),
            "positionCount": position_count,
        }

    @staticmethod
    def _position_payload(
        position: Any,
        product_type: str,
        market_value: float,
        last_price: float | None = None,
        name: str = "",
    ) -> dict[str, Any]:
        direction = getattr(position, "direction", "")
        direction_str = str(getattr(direction, "value", direction))
        quantity = int(getattr(position, "quantity", 0) or 0)
        # Shioaji reports `quantity` as an absolute lot count — a short position is
        # still positive — so the signed net must be derived from the direction.
        signed_quantity = -quantity if direction_str.lower() == "sell" else quantity
        return {
            "code": str(getattr(position, "code", "")),
            "name": name,
            "productType": product_type,
            "direction": direction_str,
            "quantity": quantity,
            "signedQuantity": signed_quantity,
            "ydQuantity": int(getattr(position, "yd_quantity", 0) or 0),
            "averagePrice": float(getattr(position, "price", 0) or 0),
            "lastPrice": round(
                last_price
                if last_price is not None
                else float(getattr(position, "last_price", 0) or 0),
                4,
            ),
            "pnl": float(getattr(position, "pnl", 0) or 0),
            "marketValue": round(market_value, 2),
        }

    @staticmethod
    def _public_account_error(exc: Exception) -> str:
        message = str(exc)
        if "Account Not Acceptable" in message:
            return "Account Not Acceptable"
        return "Account data unavailable"

    def _redis_key(self, key: str) -> str:
        return f"{self._cache_prefix}:{key.lower()}"

    def _read_cached_payload(self, key: str) -> dict[str, Any] | None:
        raw = self._redis.get(self._redis_key(key))
        if not raw:
            return None
        envelope = json.loads(raw)
        return envelope["payload"]

    def _write_cached_payload(self, key: str, payload: dict[str, Any]) -> None:
        envelope = {
            "cachedAt": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        self._redis.set(
            self._redis_key(key),
            json.dumps(envelope, ensure_ascii=True),
        )

    @staticmethod
    def _nearest_txf_contract(api: Any) -> Any:
        contracts = [
            contract
            for contract in api.Contracts.Futures.TXF
            if getattr(contract, "delivery_date", None)
            and getattr(contract, "code", "").upper().startswith("TXF")
        ]
        if not contracts:
            raise RuntimeError("No active TXF contracts returned by Shioaji")

        today = datetime.now().date()
        active = [
            contract
            for contract in contracts
            if ShioajiMarketService._parse_date(contract.delivery_date) >= today
        ]
        candidates = active or contracts
        return min(
            candidates,
            key=lambda contract: ShioajiMarketService._parse_date(contract.delivery_date),
        )

    @staticmethod
    def _mini_tsmc_contract(api: Any) -> Any:
        qff_contracts = list(getattr(api.Contracts.Futures, "QFF", []) or [])
        exact = [
            contract
            for contract in qff_contracts
            if str(getattr(contract, "code", "")).upper() == "QFFR1"
        ]
        if exact:
            return exact[0]

        candidates = [
            contract
            for contract in qff_contracts
            if str(getattr(contract, "underlying_code", "")) == "2330"
        ]
        if not candidates:
            raise RuntimeError("QFFR1 mini TSMC futures contract was not returned")
        return ShioajiMarketService._nearest_contract(candidates)

    @staticmethod
    def _nearest_contract(contracts: list[Any]) -> Any:
        dated = [
            contract for contract in contracts
            if getattr(contract, "delivery_date", None)
        ]
        if not dated:
            return contracts[0]
        today = datetime.now().date()
        active = [
            contract for contract in dated
            if ShioajiMarketService._parse_date(contract.delivery_date) >= today
        ]
        return min(
            active or dated,
            key=lambda contract: ShioajiMarketService._parse_date(
                contract.delivery_date
            ),
        )

    @staticmethod
    def _find_contract_by_code(api: Any, code: str) -> Any:
        futures = api.Contracts.Futures
        for group_name in dir(futures):
            if group_name.startswith("_"):
                continue
            try:
                group = getattr(futures, group_name)
                for contract in group:
                    if str(getattr(contract, "code", "")) == code:
                        return contract
            except (TypeError, AttributeError):
                continue
        return None

    @staticmethod
    def _parse_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return datetime.strptime(str(value).replace("/", "-"), "%Y-%m-%d").date()

    @staticmethod
    def _format_timestamp(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=TAIPEI_TZ).isoformat()
            return value.astimezone(TAIPEI_TZ).isoformat()
        if isinstance(value, (int, float)):
            divisor = 1_000_000_000 if value > 10_000_000_000 else 1
            # Shioaji snapshots expose ts as an epoch-like integer whose wall-clock
            # value already matches Taiwan market time, so we preserve the local
            # clock reading and attach the Taipei offset instead of shifting it.
            local_clock = datetime.fromtimestamp(value / divisor, tz=timezone.utc).replace(tzinfo=TAIPEI_TZ)
            return local_clock.isoformat()
        return str(value)


shioaji_market_service = ShioajiMarketService()
