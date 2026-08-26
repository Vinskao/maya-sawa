"""LLM change-set generator（含邊界檢查與重試）。

LLM client 以 dependency injection 注入，測試用 fake client，
所以整套邏輯不需要任何 token 就能驗證。

模型輸出被視為完全不可信：
- 只接受單一 JSON 物件（容忍 markdown code fence）。
- 通過 parse_change_set 的 schema 驗證（delete / add_rack_part 在這層被拒）。
- 再檢查 evidenceId 與 rackPartId 是否都在本次提供的範圍內，
  防止模型引用不存在的證據或改到沒有證據支持的 rack part。
malformed 輸出最多重試一次；仍失敗就讓節點失敗，不會退回「猜一個」。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from ..errors import SchemaError
from ..schemas import parse_change_set
from ..schemas.mapping import rack_part_index
from .prompts import SYSTEM_MESSAGE, build_change_set_prompt

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 2
DEFAULT_MAX_OUTPUT_TOKENS = 800

_CODE_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


class GenerationError(SchemaError):
    """模型輸出無法轉成可信任的 change set。"""


@runtime_checkable
class LlmClient(Protocol):
    """單一用途的同步 LLM 介面，刻意與 qa 用的 provider 分開。"""

    def complete(
        self, prompt: str, *, system_message: str, max_output_tokens: int
    ) -> str: ...


def extract_json_object(raw: str) -> dict[str, Any]:
    """從模型輸出取出唯一的 JSON 物件；容忍 code fence 與前後空白。"""
    if not isinstance(raw, str) or not raw.strip():
        raise GenerationError(["模型輸出為空"])

    text = raw.strip()
    fenced = _CODE_FENCE.match(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GenerationError([f"模型輸出不是合法 JSON：{exc}"]) from exc

    if not isinstance(payload, dict):
        raise GenerationError(["模型輸出必須是 JSON 物件"])
    return payload


def boundary_errors(
    change_set: Any, refined_evidence: list[dict[str, Any]], current_mapping: dict[str, Any]
) -> list[str]:
    """schema 之外的邊界檢查：只能用本次提供的 evidence 與既有 rack part。"""
    allowed_evidence = {
        item.get("evidenceId") for item in refined_evidence if item.get("evidenceId")
    }
    allowed_rack_parts = set(rack_part_index(current_mapping))

    errors: list[str] = []
    for operation in change_set.operations:
        label = f"{operation.op} {operation.target()}"
        if operation.rack_part_id not in allowed_rack_parts:
            errors.append(f"{label}: rackPartId 不在目前 mapping 中")
        for evidence_id in operation.evidence_ids:
            if evidence_id not in allowed_evidence:
                errors.append(f"{label}: 引用了本次未提供的 evidenceId {evidence_id}")
    return errors


class LlmChangeSetGenerator:
    """把精煉後的證據交給模型，取回受限的 change set。"""

    def __init__(
        self,
        client: LlmClient,
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ):
        self._client = client
        self._max_attempts = max(1, max_attempts)
        self._max_output_tokens = max_output_tokens
        self.attempts = 0
        self.last_errors: list[str] = []

    def generate(
        self, evidence: list[dict[str, Any]], current_mapping: dict[str, Any]
    ) -> dict[str, Any]:
        if not evidence:
            # 沒有可用證據時不呼叫模型，直接回空 change set。
            return {"generatedAt": datetime.now(timezone.utc).isoformat(), "operations": []}

        prompt = build_change_set_prompt(evidence, current_mapping)
        self.last_errors = []

        for attempt in range(1, self._max_attempts + 1):
            self.attempts = attempt
            raw = self._client.complete(
                prompt,
                system_message=SYSTEM_MESSAGE,
                max_output_tokens=self._max_output_tokens,
            )
            try:
                payload = extract_json_object(raw)
                change_set = parse_change_set(payload)
            except SchemaError as exc:
                self.last_errors = list(exc.errors)
                logger.warning("change set 生成第 %s 次失敗：%s", attempt, exc.errors)
                continue

            errors = boundary_errors(change_set, evidence, current_mapping)
            if errors:
                self.last_errors = errors
                logger.warning("change set 邊界檢查第 %s 次失敗：%s", attempt, errors)
                continue

            return payload

        raise GenerationError(
            [f"模型在 {self._max_attempts} 次嘗試內未能產生有效 change set", *self.last_errors]
        )


class FakeLlmClient:
    """測試用：依序回傳預先準備好的回應，完全不消耗 token。"""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, system_message: str, max_output_tokens: int) -> str:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("FakeLlmClient 的回應已用盡")
        return self._responses.pop(0)


class AiProviderLlmClient:
    """把既有的 async AI provider 包成本管線用的同步 client。

    只在真實模型 smoke test 或正式啟用生成時使用；
    平常的測試一律用 FakeLlmClient。
    """

    def __init__(self, provider: Any, *, temperature: float = 0.0):
        self._provider = provider
        self._temperature = temperature

    def complete(self, prompt: str, *, system_message: str, max_output_tokens: int) -> str:
        import asyncio

        response = asyncio.run(
            self._provider.generate_response(
                prompt,
                system_message=system_message,
                temperature=self._temperature,
                max_tokens=max_output_tokens,
            )
        )
        return getattr(response, "content", str(response))
