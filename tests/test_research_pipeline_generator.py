"""Change-set generator 邊界測試。

使用 FakeLlmClient 與固定回應，完全不消耗 token。
"""

from __future__ import annotations

import copy
import json

import pytest

from maya_sawa.research_pipeline.checkpointing import memory_checkpointer
from maya_sawa.research_pipeline.crag import DeterministicRetrievalEvaluator, refine_evidence
from maya_sawa.research_pipeline.generators import (
    FakeLlmClient,
    GenerationError,
    LlmChangeSetGenerator,
    build_change_set_prompt,
    extract_json_object,
    summarize_current_state,
)
from maya_sawa.research_pipeline.graph import build_graph
from maya_sawa.research_pipeline.runner import start_run
from maya_sawa.research_pipeline.schemas import parse_evidence_list
from maya_sawa.research_pipeline.state import STATUS_COMPLETED, STATUS_FAILED

from tests.test_research_pipeline_graph import CHANGE_SET, CURRENT_MAPPING, EVIDENCE, make_services


@pytest.fixture
def refined():
    evidence = parse_evidence_list(copy.deepcopy(EVIDENCE))
    evaluator = DeterministicRetrievalEvaluator()
    return refine_evidence(evidence, evaluator.evaluate(evidence, CURRENT_MAPPING))


@pytest.fixture
def valid_response():
    return json.dumps(CHANGE_SET, ensure_ascii=False)


def make_generator(responses, **kwargs):
    client = FakeLlmClient(responses)
    return LlmChangeSetGenerator(client, **kwargs), client


# --- prompt ---------------------------------------------------------------


def test_prompt_contains_evidence_ids_and_rack_part_state(refined):
    prompt = build_change_set_prompt(refined, CURRENT_MAPPING)

    for item in refined:
        assert item["evidenceId"] in prompt
    assert "dc-pdu" in prompt
    assert "add_product_entry" in prompt
    assert "Deletions and adding new rack parts are forbidden" in prompt


def test_prompt_does_not_leak_unrelated_rack_parts(refined):
    """模型只該看到相關 rack part 的現況，不是整份 mapping。"""
    prompt = build_change_set_prompt(refined, CURRENT_MAPPING)

    assert "gpu-server" not in prompt
    assert "busbar-48v" not in prompt
    # 也不該出現 mapping 的頂層 note
    assert CURRENT_MAPPING["note"] not in prompt


def test_summarize_current_state_lists_existing_entries():
    summary = summarize_current_state(CURRENT_MAPPING, ["dc-pdu"])

    assert summary[0]["rackPartId"] == "dc-pdu"
    assert {"company": "Vicor", "product": "Factorized Power (FPA) modules"} in summary[0][
        "existingEntries"
    ]


# --- 輸出解析 -------------------------------------------------------------


def test_extract_json_object_handles_code_fence():
    assert extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_object('  {"a": 1}  ') == {"a": 1}


@pytest.mark.parametrize("raw", ["", "   ", "not json", "[1, 2]", '"a string"'])
def test_extract_json_object_rejects_non_object(raw):
    with pytest.raises(GenerationError):
        extract_json_object(raw)


# --- generator 行為 -------------------------------------------------------


def test_valid_response_is_returned(refined, valid_response):
    generator, client = make_generator([valid_response])
    result = generator.generate(refined, CURRENT_MAPPING)

    assert result == CHANGE_SET
    assert generator.attempts == 1
    assert len(client.prompts) == 1


def test_empty_evidence_skips_the_model(refined):
    generator, client = make_generator([])
    result = generator.generate([], CURRENT_MAPPING)

    assert result["operations"] == []
    assert client.prompts == [], "沒有證據時不應該呼叫模型"


def test_empty_operations_is_accepted(refined):
    response = json.dumps({"generatedAt": "2026-06-25T00:00:00Z", "operations": []})
    generator, _client = make_generator([response])

    assert generator.generate(refined, CURRENT_MAPPING)["operations"] == []


def test_malformed_json_is_retried_then_succeeds(refined, valid_response):
    generator, client = make_generator(["Sure! Here you go: {oops", valid_response])
    result = generator.generate(refined, CURRENT_MAPPING)

    assert result == CHANGE_SET
    assert generator.attempts == 2
    assert len(client.prompts) == 2


def test_persistent_malformed_output_raises(refined):
    generator, _client = make_generator(["{oops", "still not json"])
    with pytest.raises(GenerationError) as exc:
        generator.generate(refined, CURRENT_MAPPING)

    assert "2 次嘗試" in str(exc.value)
    assert generator.last_errors


def test_delete_operation_is_rejected(refined, valid_response):
    bad = json.dumps(
        {
            "generatedAt": "2026-06-25T00:00:00Z",
            "operations": [{"op": "delete_product_entry", "rackPartId": "dc-pdu"}],
        }
    )
    generator, _client = make_generator([bad, valid_response])
    # 第一次被 schema 擋下，第二次才成功。
    assert generator.generate(refined, CURRENT_MAPPING) == CHANGE_SET
    assert generator.attempts == 2


def test_unknown_evidence_id_is_rejected(refined):
    payload = copy.deepcopy(CHANGE_SET)
    payload["operations"][0]["evidence"] = ["fabricated-id"]
    generator, _client = make_generator([json.dumps(payload)] * 2)

    with pytest.raises(GenerationError):
        generator.generate(refined, CURRENT_MAPPING)
    assert any("未提供的 evidenceId" in error for error in generator.last_errors)


def test_unknown_rack_part_is_rejected(refined):
    payload = copy.deepcopy(CHANGE_SET)
    payload["operations"][0]["rackPartId"] = "invented-part"
    generator, _client = make_generator([json.dumps(payload)] * 2)

    with pytest.raises(GenerationError):
        generator.generate(refined, CURRENT_MAPPING)
    assert any("rackPartId 不在目前 mapping" in error for error in generator.last_errors)


def test_max_output_tokens_is_passed_through(refined, valid_response):
    class RecordingClient(FakeLlmClient):
        def __init__(self, responses):
            super().__init__(responses)
            self.token_limits: list[int] = []

        def complete(self, prompt, *, system_message, max_output_tokens):
            self.token_limits.append(max_output_tokens)
            return super().complete(prompt, system_message=system_message, max_output_tokens=max_output_tokens)

    client = RecordingClient([valid_response])
    LlmChangeSetGenerator(client, max_output_tokens=256).generate(refined, CURRENT_MAPPING)

    assert client.token_limits == [256]


# --- 接進 graph -----------------------------------------------------------


def test_graph_run_with_llm_generator(valid_response):
    """整條管線改用 LLM generator（fake client）仍能完成 dry-run。"""
    services = make_services()
    generator = LlmChangeSetGenerator(FakeLlmClient([valid_response]))
    services = services.__class__(**{**services.__dict__, "change_set_generator": generator})

    state = start_run(
        build_graph(services, checkpointer=memory_checkpointer()),
        "run-llm",
        triggered_by="tester",
        dry_run=True,
    )

    assert state["status"] == STATUS_COMPLETED
    assert state["diff_summary"]["totalChanges"] == 2


def test_graph_fails_when_model_keeps_returning_garbage():
    services = make_services()
    generator = LlmChangeSetGenerator(FakeLlmClient(["nope", "still nope"]))
    services = services.__class__(**{**services.__dict__, "change_set_generator": generator})

    state = start_run(
        build_graph(services, checkpointer=memory_checkpointer()),
        "run-llm-bad",
        triggered_by="tester",
        dry_run=True,
    )

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "generate_change_set"
    assert services.publisher.published == {}
