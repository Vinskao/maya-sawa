import hmac
import logging
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, status

from ..services.token_reporter import report_token_usage_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/otel", tags=["OTel Usage"])

CLAUDE_TOKEN_METRIC = "claude_code.token.usage"
CLAUDE_COST_METRIC = "claude_code.cost.usage"
GEMINI_TOKEN_METRIC = "gemini_cli.token.usage"


def _header_token(request: Request) -> Optional[str]:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ")
    # Only accept the token via headers. Query-string tokens leak into access
    # logs, browser history and referrers, so they are intentionally rejected.
    return request.headers.get("x-ai-usage-token")


def _require_otel_token(request: Request) -> None:
    expected = os.getenv("OTEL_USAGE_INGEST_TOKEN") or os.getenv("AI_USAGE_INGEST_TOKEN", "")
    if not expected:
        # Fail closed: refuse ingestion when no token is configured rather than
        # silently leaving the endpoint open to the public.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OTel ingest token not configured",
        )

    provided = _header_token(request) or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized OTel ingest")


def _attr_value(value: Dict[str, Any]) -> Any:
    for key in (
        "stringValue",
        "intValue",
        "doubleValue",
        "boolValue",
        "bytesValue",
    ):
        if key in value:
            return value[key]
    if "arrayValue" in value:
        return [_attr_value(v) for v in value["arrayValue"].get("values", [])]
    return None


def _attrs(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {item.get("key", ""): _attr_value(item.get("value", {})) for item in items}


def _metric_points(metric: Dict[str, Any]) -> Iterable[Tuple[Dict[str, Any], float]]:
    for container_name in ("sum", "gauge", "histogram"):
        container = metric.get(container_name)
        if not container:
            continue
        for point in container.get("dataPoints", []):
            raw_value = point.get("asDouble", point.get("asInt", point.get("value", 0)))
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                value = 0.0
            yield _attrs(point.get("attributes", [])), value


def _iter_metrics(payload: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    for resource_metric in payload.get("resourceMetrics", []):
        resource_attrs = _attrs(resource_metric.get("resource", {}).get("attributes", []))
        for scope_metric in resource_metric.get("scopeMetrics", []):
            for metric in scope_metric.get("metrics", []):
                metric["_resourceAttrs"] = resource_attrs
                yield metric


def _model(attrs: Dict[str, Any]) -> str:
    return str(
        attrs.get("model")
        or attrs.get("gen_ai.request.model")
        or attrs.get("gen_ai.response.model")
        or "unknown"
    )


def _session_id(attrs: Dict[str, Any], resource_attrs: Dict[str, Any]) -> Optional[str]:
    value = attrs.get("session.id") or resource_attrs.get("session.id")
    return str(value) if value else None


async def _report_token_metric(
    provider: str,
    metric_name: str,
    attrs: Dict[str, Any],
    resource_attrs: Dict[str, Any],
    value: float,
) -> None:
    token_type = str(attrs.get("type", "")).lower()
    tokens = max(0, int(round(value)))
    if tokens == 0:
        return

    usage = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    if token_type in ("input", "prompt"):
        usage["prompt_tokens"] = tokens
    elif token_type in ("output", "completion", "thought", "tool"):
        usage["completion_tokens"] = tokens
    elif token_type in ("cacheread", "cache_read", "cache"):
        usage["cache_read_input_tokens"] = tokens
    elif token_type in ("cachecreation", "cache_creation"):
        usage["cache_creation_input_tokens"] = tokens
    else:
        logger.debug("Ignoring unsupported token type %s for %s", token_type, metric_name)
        return

    await report_token_usage_async(
        ai_provider=provider,
        model_name=_model(attrs),
        input_tokens=usage["prompt_tokens"],
        output_tokens=usage["completion_tokens"],
        cache_creation_input_tokens=usage["cache_creation_input_tokens"],
        cache_read_input_tokens=usage["cache_read_input_tokens"],
        estimated_cost_usd=None,
        session_id=_session_id(attrs, resource_attrs),
        user_id=str(attrs.get("user.account_id") or attrs.get("user.email") or "") or None,
        endpoint=f"/otel/{metric_name}",
    )


async def _report_cost_metric(
    attrs: Dict[str, Any],
    resource_attrs: Dict[str, Any],
    value: float,
) -> None:
    if value <= 0:
        return
    await report_token_usage_async(
        ai_provider="claude",
        model_name=_model(attrs),
        input_tokens=0,
        output_tokens=0,
        estimated_cost_usd=value,
        session_id=_session_id(attrs, resource_attrs),
        user_id=str(attrs.get("user.account_id") or "") or None,
        endpoint=f"/otel/{CLAUDE_COST_METRIC}",
    )


@router.post("/v1/metrics")
async def ingest_otlp_metrics(request: Request) -> Dict[str, Any]:
    _require_otel_token(request)

    content_type = request.headers.get("content-type", "")
    if "json" not in content_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Use OTLP HTTP JSON: OTEL_EXPORTER_OTLP_PROTOCOL=http/json",
        )

    payload = await request.json()
    received = 0
    forwarded = 0

    for metric in _iter_metrics(payload):
        received += 1
        name = metric.get("name")
        resource_attrs = metric.get("_resourceAttrs", {})
        for attrs, value in _metric_points(metric):
            if name == CLAUDE_TOKEN_METRIC:
                await _report_token_metric("claude", name, attrs, resource_attrs, value)
                forwarded += 1
            elif name == CLAUDE_COST_METRIC:
                await _report_cost_metric(attrs, resource_attrs, value)
                forwarded += 1
            elif name == GEMINI_TOKEN_METRIC:
                await _report_token_metric("gemini", name, attrs, resource_attrs, value)
                forwarded += 1

    return {"ok": True, "metricsReceived": received, "pointsForwarded": forwarded}
