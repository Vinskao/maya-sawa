"""RunPod cost & balance observability via the RunPod GraphQL API.

RunPod has no CLI command for spend, but its GraphQL endpoint exposes the
account balance, the live aggregate spend rate, and the per-pod hourly cost.
This service is read-only: it issues a single GraphQL query with the account
API key and shapes the result into a small, stable payload for the dashboard.

Mirrors the configuration style of the other services in this package: it is
disabled (raises ``RunpodNotConfiguredError``) until ``RUNPOD_API_KEY`` is set.
"""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RUNPOD_GRAPHQL_URL = "https://api.runpod.io/graphql"

# Single query: account balance + live spend rate + every pod's hourly cost and
# uptime. ``costPerHr`` is what the pod bills while RUNNING; a stopped pod bills
# 0 for compute but its volume storage is billed separately by RunPod and is
# NOT reflected here.
_COST_QUERY = """
query CostOverview {
  myself {
    clientBalance
    currentSpendPerHr
    pods {
      id
      name
      desiredStatus
      costPerHr
      machine { gpuDisplayName }
      runtime { uptimeInSeconds }
    }
  }
}
"""


class RunpodNotConfiguredError(RuntimeError):
    """RUNPOD_API_KEY is not set; the cost endpoint is disabled."""


class RunpodUnavailableError(RuntimeError):
    """The RunPod GraphQL API could not be reached or returned an error."""


class RunpodCostService:
    """Reads account balance and pod cost rates from RunPod GraphQL."""

    def __init__(self) -> None:
        self._timeout = float(os.getenv("RUNPOD_HTTP_TIMEOUT", "15"))

    @property
    def api_key(self) -> str | None:
        # Read lazily so .env loaded after import is still picked up.
        return os.getenv("RUNPOD_API_KEY")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def get_cost_overview(self) -> dict[str, Any]:
        """Return balance, aggregate spend rate, and per-pod cost breakdown."""
        api_key = self.api_key
        if not api_key:
            raise RunpodNotConfiguredError(
                "RUNPOD_API_KEY is not set; RunPod cost reporting is disabled"
            )

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    RUNPOD_GRAPHQL_URL,
                    params={"api_key": api_key},
                    json={"query": _COST_QUERY},
                )
                resp.raise_for_status()
                payload = resp.json()
        except httpx.HTTPError as exc:
            raise RunpodUnavailableError(f"RunPod API request failed: {exc}") from exc

        if payload.get("errors"):
            raise RunpodUnavailableError(f"RunPod API error: {payload['errors']}")

        myself = (payload.get("data") or {}).get("myself") or {}
        return self._shape(myself)

    @staticmethod
    def _shape(myself: dict[str, Any]) -> dict[str, Any]:
        pods_raw = myself.get("pods") or []
        pods: list[dict[str, Any]] = []
        running_spend_per_hr = 0.0

        for pod in pods_raw:
            status = pod.get("desiredStatus")
            cost = float(pod.get("costPerHr") or 0.0)
            uptime = (pod.get("runtime") or {}).get("uptimeInSeconds")
            is_running = status == "RUNNING"
            if is_running:
                running_spend_per_hr += cost
            pods.append(
                {
                    "id": pod.get("id"),
                    "name": pod.get("name"),
                    "status": status,
                    "gpu": (pod.get("machine") or {}).get("gpuDisplayName"),
                    "costPerHr": cost,
                    "running": is_running,
                    "uptimeSeconds": uptime,
                }
            )

        return {
            "currency": "USD",
            "balance": float(myself.get("clientBalance") or 0.0),
            # Account-wide live spend rate as reported by RunPod.
            "currentSpendPerHr": float(myself.get("currentSpendPerHr") or 0.0),
            # Spend rate summed from currently-running pods (sanity cross-check).
            "runningSpendPerHr": round(running_spend_per_hr, 4),
            "podCount": len(pods),
            "runningPodCount": sum(1 for p in pods if p["running"]),
            "pods": pods,
        }


# Module-level singleton, matching the other services in this package.
runpod_cost_service = RunpodCostService()
