import asyncio
import json
import os
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

    def __init__(self, api: Any) -> None:
        self._api = api
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

    def logout(self) -> Any:
        return self._api.logout()


class ShioajiMarketService:
    def __init__(self) -> None:
        self._api: Any = None
        self._login_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[None] | None = None
        self._cache_seconds = int(os.getenv("SHIOAJI_QUOTE_CACHE_SECONDS", "600"))
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
        if self.portfolio_enabled:
            await self._refresh_payload("PORTFOLIO", self._fetch_portfolio)

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

    async def _refresh_payload(self, key: str, fetcher: Any) -> None:
        try:
            payload = await self._run_with_relogin(fetcher)
        except Exception:
            return
        try:
            await asyncio.to_thread(self._write_cached_payload, key, payload)
        except redis.RedisError:
            return

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
        return ReadOnlyShioajiClient(api)

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
        account_errors: dict[str, str] = {}
        try:
            stock_positions = api.list_positions(account=api.stock_account)
        except Exception as exc:
            stock_positions = []
            account_errors["stock"] = ShioajiMarketService._public_account_error(exc)
        try:
            futures_positions = api.list_positions(account=api.futopt_account)
        except Exception as exc:
            futures_positions = []
            account_errors["futures"] = ShioajiMarketService._public_account_error(exc)

        positions: list[dict[str, Any]] = []
        for position in stock_positions:
            quantity = int(getattr(position, "quantity", 0) or 0)
            last_price = float(getattr(position, "last_price", 0) or 0)
            market_value = abs(last_price * quantity * 1000)
            positions.append(
                ShioajiMarketService._position_payload(
                    position, "stock", market_value
                )
            )

        for position in futures_positions:
            quantity = int(getattr(position, "quantity", 0) or 0)
            last_price = float(getattr(position, "last_price", 0) or 0)
            contract = ShioajiMarketService._find_contract_by_code(
                api, str(getattr(position, "code", ""))
            )
            multiplier = float(getattr(contract, "unit", 1) or 1)
            market_value = abs(last_price * quantity * multiplier)
            payload = ShioajiMarketService._position_payload(
                position, "futures", market_value
            )
            payload["multiplier"] = multiplier
            positions.append(payload)

        total_position_exposure = sum(item["marketValue"] for item in positions)
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

        return {
            "cashBalance": cash,
            "balanceAvailable": balance is not None,
            "balanceError": balance_error,
            "accountErrors": account_errors,
            "balanceDate": str(getattr(balance, "date", "") or "") if balance else "",
            "totalAssetsEstimated": round(total_assets, 2) if total_assets is not None else None,
            "totalPositionExposure": round(total_position_exposure, 2),
            "positions": positions,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Sinopac Shioaji",
            "valuationNote": (
                "Cash plus position exposure"
                if cash is not None
                else "Position exposure only; account balance unavailable"
            ),
        }

    @staticmethod
    def _position_payload(
        position: Any, product_type: str, market_value: float
    ) -> dict[str, Any]:
        direction = getattr(position, "direction", "")
        return {
            "code": str(getattr(position, "code", "")),
            "productType": product_type,
            "direction": str(getattr(direction, "value", direction)),
            "quantity": int(getattr(position, "quantity", 0) or 0),
            "averagePrice": float(getattr(position, "price", 0) or 0),
            "lastPrice": float(getattr(position, "last_price", 0) or 0),
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
