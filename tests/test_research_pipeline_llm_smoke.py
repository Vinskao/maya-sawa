"""真實模型 smoke test（integration，預設 skip）。

只驗證「模型能產出 schema 相容的 change set」，不測文字品質。
刻意限制成一份短證據、一次呼叫、低 output token。

    RESEARCH_PIPELINE_LLM_SMOKE=true poetry run pytest \
        tests/test_research_pipeline_llm_smoke.py
"""

from __future__ import annotations

import os

import pytest

from maya_sawa.research_pipeline.crag import DeterministicRetrievalEvaluator, refine_evidence
from maya_sawa.research_pipeline.generators import LlmChangeSetGenerator
from maya_sawa.research_pipeline.generators.llm_generator import AiProviderLlmClient
from maya_sawa.research_pipeline.schemas import parse_change_set, parse_evidence_list

from tests.test_research_pipeline_graph import CURRENT_MAPPING, EVIDENCE

pytestmark = pytest.mark.skipif(
    os.getenv("RESEARCH_PIPELINE_LLM_SMOKE", "").lower() != "true",
    reason="需要 RESEARCH_PIPELINE_LLM_SMOKE=true 且會消耗 token",
)


def test_real_model_returns_schema_compatible_change_set():
    from maya_sawa.services.ai_providers.base import AIProviderFactory

    provider = AIProviderFactory.get_provider(os.getenv("RESEARCH_PIPELINE_LLM_PROVIDER", "openai"))
    if provider is None or not provider.is_available():
        pytest.skip("AI provider 無法使用")

    # 只送一份證據，並限制 output token。
    evidence = parse_evidence_list([EVIDENCE[0]])
    refined = refine_evidence(
        evidence, DeterministicRetrievalEvaluator().evaluate(evidence, CURRENT_MAPPING)
    )

    generator = LlmChangeSetGenerator(
        AiProviderLlmClient(provider), max_attempts=1, max_output_tokens=400
    )
    payload = generator.generate(refined, CURRENT_MAPPING)

    # 只檢查結構相容性，不檢查內容品質。
    change_set = parse_change_set(payload)
    assert generator.attempts == 1
    for operation in change_set.operations:
        assert operation.rack_part_id == "dc-pdu"
        assert set(operation.evidence_ids) <= {item["evidenceId"] for item in refined}
