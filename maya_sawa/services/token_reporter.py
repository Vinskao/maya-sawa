"""
Token Usage Reporter

非同步向 ty-multiverse-backend 回報 AI API token 用量。
失敗只記錄 warning，不影響主業務流程。
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

TYMB_URL = os.getenv("PUBLIC_TYMB_URL", "")
AI_USAGE_ENDPOINT = f"{TYMB_URL}/ai-usage"
AI_USAGE_INGEST_TOKEN = os.getenv("AI_USAGE_INGEST_TOKEN", "")

COST_RATES: Dict[str, Dict[str, float]] = {
    "gpt-4o-mini":    {"input": 0.00015, "output": 0.00060},
    "gpt-4o":         {"input": 0.00250, "output": 0.01000},
    "gpt-4.1-nano":   {"input": 0.00010, "output": 0.00040},
}


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[float]:
    rates = COST_RATES.get(model)
    if not rates:
        return None
    return (rates["input"] * input_tokens + rates["output"] * output_tokens) / 1000


def _as_cost(value: Optional[Any]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _usage_headers() -> Dict[str, str]:
    if not AI_USAGE_INGEST_TOKEN:
        return {}
    return {"X-AI-Usage-Token": AI_USAGE_INGEST_TOKEN}


async def report_token_usage_async(
    ai_provider: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    status: str = "success",
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    estimated_cost_usd: Optional[float] = None,
) -> None:
    if not TYMB_URL:
        logger.debug("PUBLIC_TYMB_URL 未設置，跳過 token usage 回報")
        return

    try:
        payload = {
            "aiProvider": ai_provider,
            "modelName": model_name,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "cacheCreationInputTokens": cache_creation_input_tokens,
            "cacheReadInputTokens": cache_read_input_tokens,
            "estimatedCostUsd": estimated_cost_usd
                if estimated_cost_usd is not None
                else _calculate_cost(model_name, input_tokens, output_tokens),
            "sessionId": session_id,
            "userId": user_id,
            "requestId": request_id,
            "endpoint": endpoint,
            "status": status,
        }
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(AI_USAGE_ENDPOINT, json=payload, headers=_usage_headers())
            if resp.status_code not in (200, 201):
                logger.warning(f"Token usage 回報失敗: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"Token usage 回報例外 (已忽略): {e}")


def fire_and_forget(
    ai_provider: str,
    model_name: str,
    usage: Dict[str, Any],
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    status: str = "success",
) -> None:
    """
    同步包裝：在 async context 中建立 task，在 sync context 中執行 coroutine。
    """
    coro = report_token_usage_async(
        ai_provider=ai_provider,
        model_name=model_name,
        input_tokens=usage.get("prompt_tokens", usage.get("input_tokens", 0)),
        output_tokens=usage.get("completion_tokens", usage.get("output_tokens", 0)),
        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
        estimated_cost_usd=_as_cost(usage.get("estimated_cost_usd")),
        session_id=session_id,
        user_id=user_id,
        request_id=request_id,
        endpoint=endpoint,
        status=status,
    )
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(coro)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        logger.warning(f"fire_and_forget 失敗 (已忽略): {e}")
