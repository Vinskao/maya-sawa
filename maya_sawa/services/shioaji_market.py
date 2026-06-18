import asyncio
import json
import logging
import os
import platform
import time
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import redis


logger = logging.getLogger(__name__)
TAIPEI_TZ = ZoneInfo("Asia/Taipei")
FUTURES_EXPIRY_ROLLOVER_TIME = (13, 45)


def resolve_shioaji_credentials() -> tuple[str | None, str | None]:
    """Pick the Shioaji API/secret key pair for the current machine.

    Local development uses a separate key per OS so two machines never share
    one session (Shioaji invalidates a key when another login reuses it):

    - macOS   -> SHIOAJI_LOCAL1_API_KEY / SHIOAJI_LOCAL1_SECRET_KEY
    - Windows -> SHIOAJI_LOCAL2_API_KEY / SHIOAJI_LOCAL2_SECRET_KEY

    If the OS-specific pair is not set (e.g. the Linux cloud deployment, where
    only the generic vars exist), fall back to SHIOAJI_API_KEY /
    SHIOAJI_SECRET_KEY. This means "local stage" is detected implicitly: the
    LOCAL* vars only live in local .env files.
    """
    system = platform.system()
    if system == "Darwin":
        prefix = "SHIOAJI_LOCAL1_"
    elif system == "Windows":
        prefix = "SHIOAJI_LOCAL2_"
    else:
        prefix = None

    if prefix:
        api_key = os.getenv(f"{prefix}API_KEY")
        secret_key = os.getenv(f"{prefix}SECRET_KEY")
        if api_key and secret_key:
            return api_key, secret_key

    return os.getenv("SHIOAJI_API_KEY"), os.getenv("SHIOAJI_SECRET_KEY")


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

    def margin(self, account: Any) -> Any:
        return self._api.margin(account=account)

    def list_positions(self, account: Any) -> Any:
        return self._api.list_positions(account=account)

    def list_stock_positions(self) -> Any:
        return self._api.list_positions(
            account=self.stock_account,
            unit=self._share_unit,
        )

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
        api_key, secret_key = resolve_shioaji_credentials()
        return bool(api_key and secret_key)

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
            logger.exception("Failed to refresh Shioaji market payload: %s", key)
            return False
        try:
            await asyncio.to_thread(self._write_cached_payload, key, payload)
        except redis.RedisError:
            logger.exception("Failed to write Shioaji market payload to Redis: %s", key)
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

        api_key, secret_key = resolve_shioaji_credentials()
        if not (api_key and secret_key):
            raise ShioajiNotConfiguredError(
                "SHIOAJI_API_KEY and SHIOAJI_SECRET_KEY are required"
            )
        api = sj.Shioaji(simulation=os.getenv("SHIOAJI_SIMULATION", "false").lower() == "true")
        api.login(
            api_key=api_key,
            secret_key=secret_key,
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

        stock_position_payloads: list[dict[str, Any]] = []
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
            stock_position_payloads.append(
                ShioajiMarketService._position_payload(
                    position,
                    "stock",
                    market_value,
                    allocation_value=market_value,
                    last_price=last_price,
                    name=stock_name,
                )
            )

        futures_margin = None
        futures_margin_error = None
        try:
            futures_margin = api.margin(api.futopt_account)
        except Exception as exc:
            futures_margin_error = ShioajiMarketService._public_account_error(exc)

        try:
            futures_positions = api.list_positions(api.futopt_account)
        except Exception as exc:
            futures_positions = []
            futures_error = ShioajiMarketService._public_account_error(exc)
        else:
            futures_error = None

        futures_position_payloads: list[dict[str, Any]] = []
        for position in futures_positions:
            code = str(getattr(position, "code", ""))
            contract = ShioajiMarketService._find_contract_by_code(api, code)
            contract_name = str(getattr(contract, "name", "") or "")
            last_price = float(getattr(position, "last_price", 0) or 0)
            contract_value, contract_size_shares, valuation_formula = (
                ShioajiMarketService._futures_contract_value_details(
                position,
                contract=contract,
                contract_name=contract_name,
            )
            )
            futures_position_payloads.append(
                ShioajiMarketService._position_payload(
                    position,
                    "futures",
                    market_value=contract_value,
                    allocation_value=contract_value,
                    last_price=last_price,
                    name=contract_name,
                    contract_size_shares=contract_size_shares,
                    valuation_formula=valuation_formula,
                )
            )

        positions = stock_position_payloads + futures_position_payloads
        stock_market_value = sum(item["allocationValue"] for item in stock_position_payloads)
        futures_contract_exposure = sum(item["allocationValue"] for item in futures_position_payloads)
        total_position_exposure = stock_market_value + futures_contract_exposure
        total_pnl = sum(item["pnl"] for item in positions)
        futures_equity = float(getattr(futures_margin, "equity", 0) or 0)
        futures_available_cash = float(getattr(futures_margin, "available_margin", 0) or 0)
        display_cash = (
            cash + futures_available_cash
            if cash is not None
            else None
        )
        total_assets = (
            cash + stock_market_value + futures_equity
            if cash is not None
            else None
        )
        leverage_ratio = (
            round(
                (futures_contract_exposure + stock_market_value + cash) / total_assets,
                4,
            )
            if cash is not None and total_assets and total_assets > 0
            else None
        )
        percentage_base = total_assets or total_position_exposure
        for item in positions:
            item["assetPercentage"] = (
                round(item["allocationValue"] / percentage_base * 100, 2)
                if percentage_base > 0
                else 0
            )

        return {
            "cashBalance": round(display_cash, 2) if display_cash is not None else None,
            "stockCashBalance": cash,
            "futuresAvailableCash": round(futures_available_cash, 2),
            "balanceAvailable": balance is not None,
            "balanceError": balance_error,
            "accountErrors": {
                key: value for key, value in {
                    "stock": stock_error,
                    "futures": futures_error,
                    "futuresMargin": futures_margin_error,
                }.items() if value
            },
            "balanceDate": str(getattr(balance, "date", "") or "") if balance else "",
            "totalAssetsEstimated": round(total_assets, 2) if total_assets is not None else None,
            "totalPositionExposure": round(total_position_exposure, 2),
            "stockMarketValue": round(stock_market_value, 2),
            "futuresContractExposure": round(futures_contract_exposure, 2),
            "futuresEquity": round(futures_equity, 2),
            "leverageRatio": leverage_ratio,
            "totalPnl": round(total_pnl, 2),
            "summaryFormulas": {
                "cashBalance": (
                    f"{int(cash):,} + {int(futures_available_cash):,}"
                    if cash is not None
                    else None
                ),
                "totalAssetsEstimated": (
                    f"{int(cash):,} + {int(stock_market_value):,} + {int(futures_equity):,}"
                    if cash is not None
                    else None
                ),
                "totalPnl": " + ".join(
                    f"{str(item.get('name') or item.get('code') or '?')} {item['pnl']:+,.0f}"
                    for item in positions
                ) or "0",
                "leverageRatio": (
                    f"({int(futures_contract_exposure):,} + {int(stock_market_value):,} + {int(cash):,}) / "
                    f"({int(futures_equity):,} + {int(stock_market_value):,} + {int(cash):,})"
                    if cash is not None and total_assets and total_assets > 0
                    else None
                ),
            },
            "positionCount": len(positions),
            "cashPercentage": (
                round(display_cash / total_assets * 100, 2)
                if display_cash is not None and total_assets and total_assets > 0
                else 0
            ),
            "positions": positions,
            "stockPositions": stock_position_payloads,
            "futuresPositions": futures_position_payloads,
            "futuresSummary": {
                "equity": futures_equity,
                "equityAmount": float(getattr(futures_margin, "equity_amount", 0) or 0),
                "availableMargin": futures_available_cash,
                "openPositionPnl": float(getattr(futures_margin, "future_open_position", 0) or 0),
                "maintenanceMargin": float(getattr(futures_margin, "maintenance_margin", 0) or 0),
                "initialMargin": float(getattr(futures_margin, "initial_margin", 0) or 0),
                "positionCount": len(futures_position_payloads),
            },
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "Sinopac Shioaji",
            "valuationNote": (
                "Stock cash plus stock market value plus futures equity"
                if cash is not None
                else "Stock and futures exposure only; cash balance unavailable"
            ),
        }

    @staticmethod
    def _position_payload(
        position: Any,
        product_type: str,
        market_value: float,
        allocation_value: float | None = None,
        last_price: float | None = None,
        name: str = "",
        contract_size_shares: int | None = None,
        valuation_formula: str | None = None,
    ) -> dict[str, Any]:
        direction = getattr(position, "direction", "")
        payload = {
            "code": str(getattr(position, "code", "")),
            "name": name,
            "productType": product_type,
            "direction": str(getattr(direction, "value", direction)),
            "quantity": int(getattr(position, "quantity", 0) or 0),
            "signedQuantity": ShioajiMarketService._signed_quantity(position),
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
            "allocationValue": round(
                allocation_value if allocation_value is not None else market_value,
                2,
            ),
        }
        if contract_size_shares is not None:
            payload["contractSizeShares"] = contract_size_shares
        if valuation_formula:
            payload["valuationFormula"] = valuation_formula
        return payload

    @staticmethod
    def _futures_contract_shares(
        code: str,
        contract: Any | None = None,
        contract_name: str = "",
    ) -> int | None:
        resolved_name = contract_name or str(getattr(contract, "name", "") or "")
        underlying_kind = str(getattr(contract, "underlying_kind", "") or "").upper()
        underlying_code = str(getattr(contract, "underlying_code", "") or "")
        if underlying_kind == "S":
            return 100 if "小型" in resolved_name else 2000
        if not underlying_kind and underlying_code.isdigit() and len(underlying_code) == 4:
            return 100 if "小型" in resolved_name else 2000
        return None

    @staticmethod
    def _futures_contract_value_details(
        position: Any,
        contract: Any | None = None,
        contract_name: str = "",
    ) -> tuple[float, int | None, str]:
        code = str(getattr(position, "code", "") or "")
        contract_shares = ShioajiMarketService._futures_contract_shares(
            code,
            contract=contract,
            contract_name=contract_name,
        )
        quantity = abs(int(getattr(position, "quantity", 0) or 0))
        last_price = float(getattr(position, "last_price", 0) or 0)
        if contract_shares and quantity > 0 and last_price > 0:
            contract_value = contract_shares * quantity * last_price
            return (
                float(contract_value),
                contract_shares,
                f"{quantity} * {last_price:g} * {contract_shares}",
            )
        fallback_value = float(abs(getattr(position, "last_price", 0) or 0) * quantity)
        return fallback_value, None, f"{quantity} * {last_price:g}"

    @staticmethod
    def _futures_contract_value(
        position: Any,
        contract: Any | None = None,
        contract_name: str = "",
    ) -> float:
        value, _contract_shares, _formula = ShioajiMarketService._futures_contract_value_details(
            position,
            contract=contract,
            contract_name=contract_name,
        )
        return value

    @staticmethod
    def _signed_quantity(position: Any) -> int:
        quantity = int(getattr(position, "quantity", 0) or 0)
        direction = str(getattr(getattr(position, "direction", ""), "value", getattr(position, "direction", "")))
        return -quantity if direction.lower() == "sell" else quantity

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
    def _nearest_txf_contract(api: Any, now: datetime | None = None) -> Any:
        contracts = [
            contract
            for contract in api.Contracts.Futures.TXF
            if getattr(contract, "delivery_date", None)
            and getattr(contract, "code", "").upper().startswith("TXF")
        ]
        if not contracts:
            raise RuntimeError("No active TXF contracts returned by Shioaji")

        active = [
            contract
            for contract in contracts
            if ShioajiMarketService._is_active_futures_contract(contract, now)
        ]
        candidates = active or contracts
        return min(
            candidates,
            key=ShioajiMarketService._contract_sort_key,
        )

    @staticmethod
    def _mini_tsmc_contract(api: Any, now: datetime | None = None) -> Any:
        qff_contracts = list(getattr(api.Contracts.Futures, "QFF", []) or [])
        candidates = [
            contract
            for contract in qff_contracts
            if str(getattr(contract, "underlying_code", "")) == "2330"
        ]
        if not candidates:
            raise RuntimeError("QFFR1 mini TSMC futures contract was not returned")
        return ShioajiMarketService._nearest_contract(candidates, now)

    @staticmethod
    def _nearest_contract(contracts: list[Any], now: datetime | None = None) -> Any:
        dated = [
            contract for contract in contracts
            if getattr(contract, "delivery_date", None)
        ]
        if not dated:
            return contracts[0]
        active = [
            contract for contract in dated
            if ShioajiMarketService._is_active_futures_contract(contract, now)
        ]
        return min(
            active or dated,
            key=ShioajiMarketService._contract_sort_key,
        )

    @staticmethod
    def _is_active_futures_contract(contract: Any, now: datetime | None = None) -> bool:
        current = now.astimezone(TAIPEI_TZ) if now else datetime.now(TAIPEI_TZ)
        delivery_date = ShioajiMarketService._parse_date(contract.delivery_date)
        if delivery_date > current.date():
            return True
        if delivery_date < current.date():
            return False
        return (current.hour, current.minute) < FUTURES_EXPIRY_ROLLOVER_TIME

    @staticmethod
    def _contract_sort_key(contract: Any) -> tuple[date, bool]:
        code = str(getattr(contract, "code", "")).upper()
        is_continuous = len(code) >= 2 and code[-2] == "R" and code[-1].isdigit()
        return ShioajiMarketService._parse_date(contract.delivery_date), is_continuous

    @staticmethod
    def _find_contract_by_code(api: Any, code: str) -> Any:
        futures = getattr(api.Contracts, "Futures", None)
        if futures is None:
            return None
        for contract in ShioajiMarketService._iter_futures_contracts(futures):
            if str(getattr(contract, "code", "")) == code:
                return contract
        return None

    @staticmethod
    def _iter_futures_contracts(futures: Any):
        seen_ids: set[int] = set()

        def yield_contracts_from_group(group: Any):
            group_id = id(group)
            if group_id in seen_ids:
                return
            seen_ids.add(group_id)

            values = group.values() if hasattr(group, "values") else group
            try:
                for item in values:
                    if isinstance(item, str):
                        continue
                    if getattr(item, "code", None) is not None:
                        yield item
                    elif hasattr(item, "values") or not isinstance(item, (str, bytes)):
                        yield from yield_contracts_from_group(item)
            except TypeError:
                return

        try:
            for group in futures:
                yield from yield_contracts_from_group(group)
        except TypeError:
            pass

        for group_name in dir(futures):
            if group_name.startswith("_"):
                continue
            try:
                group = getattr(futures, group_name)
                yield from yield_contracts_from_group(group)
            except (TypeError, AttributeError):
                continue

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
