"""CRAG 測試：deterministic evaluator、知識精煉、grounding，以及 graph 的補救迴圈。

全部使用 fixture 與 fake evaluator，不呼叫任何模型或網路。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from maya_sawa.research_pipeline.checkpointing import memory_checkpointer
from maya_sawa.research_pipeline.crag import (
    AMBIGUOUS,
    CORRECT,
    INCORRECT,
    MAX_CORRECTION_ATTEMPTS,
    DeterministicRetrievalEvaluator,
    EvidenceEvaluation,
    aggregate_verdict,
    grounding_errors,
    refine_evidence,
)
from maya_sawa.research_pipeline.graph import build_graph
from maya_sawa.research_pipeline.runner import start_run
from maya_sawa.research_pipeline.schemas import parse_change_set, parse_evidence_list
from maya_sawa.research_pipeline.state import STATUS_COMPLETED, STATUS_FAILED

from tests.test_research_pipeline_graph import (
    CHANGE_SET,
    CURRENT_MAPPING,
    EVIDENCE,
    make_services,
)

FIXTURES = Path("maya_sawa/research_pipeline/fixtures")


@pytest.fixture
def evidence():
    return parse_evidence_list(copy.deepcopy(EVIDENCE))


@pytest.fixture
def evaluator():
    return DeterministicRetrievalEvaluator()


# --- deterministic evaluator ---------------------------------------------


def test_fixture_evidence_is_correct(evaluator, evidence):
    evaluations = evaluator.evaluate(evidence, CURRENT_MAPPING)

    assert [e.verdict for e in evaluations] == [CORRECT, CORRECT]
    assert all(e.score == pytest.approx(1.0) for e in evaluations)
    assert aggregate_verdict(evaluations) == CORRECT


def _evaluate_one(evaluator, patch: dict):
    item = parse_evidence_list([{**EVIDENCE[0], **patch}])[0]
    return evaluator.evaluate([item], CURRENT_MAPPING)[0]


def test_unknown_rack_part_is_not_correct(evaluator):
    evaluation = _evaluate_one(evaluator, {"rackPartId": "no-such-part"})

    assert evaluation.verdict != CORRECT
    assert not evaluation.checks["rack_part_match"]
    assert any("rackPartId" in reason for reason in evaluation.reasons)


def test_entity_mismatch_is_not_correct(evaluator):
    evaluation = _evaluate_one(evaluator, {"company": "Totally Unrelated Vendor"})

    assert evaluation.verdict != CORRECT
    assert not evaluation.checks["company_match"]


def test_missing_supporting_statement_is_not_correct(evaluator):
    evaluation = _evaluate_one(evaluator, {"evidenceText": "Delta."})

    assert evaluation.verdict != CORRECT
    assert not evaluation.checks["supporting_statement"]


def test_url_outside_source_allowlist_fails_completeness(evaluator):
    evaluation = _evaluate_one(evaluator, {"sourceUrl": "https://blog.example.com/post"})

    assert not evaluation.checks["complete_fields"]
    assert evaluation.verdict != CORRECT


def test_product_mismatch_alone_is_ambiguous(evaluator):
    """關鍵檢查都過、只有 product 對不上 → ambiguous，可補救但不能單獨支持變更。"""
    evaluation = _evaluate_one(evaluator, {"product": "Totally Different Product Name"})

    assert evaluation.verdict == AMBIGUOUS


def test_aggregate_prefers_correct_then_ambiguous():
    def make(verdict):
        return EvidenceEvaluation("id", verdict, 1.0, {}, ())

    assert aggregate_verdict([make(INCORRECT), make(CORRECT)]) == CORRECT
    assert aggregate_verdict([make(INCORRECT), make(AMBIGUOUS)]) == AMBIGUOUS
    assert aggregate_verdict([make(INCORRECT)]) == INCORRECT
    assert aggregate_verdict([]) == INCORRECT


# --- 知識精煉 -------------------------------------------------------------


def test_refine_keeps_only_correct_evidence(evaluator, evidence):
    evaluations = evaluator.evaluate(evidence, CURRENT_MAPPING)
    downgraded = [
        EvidenceEvaluation(evaluations[0].evidence_id, AMBIGUOUS, 0.6, {}, ()),
        evaluations[1],
    ]

    refined = refine_evidence(evidence, downgraded)
    assert [item["evidenceId"] for item in refined] == [evidence[1].evidence_id]


def test_refine_filters_unrelated_sentences_and_dedupes(evaluator):
    raw = [
        {
            **EVIDENCE[0],
            "evidenceText": (
                "Delta Electronics 800V to 48V DC-DC power module is in production. "
                "Cookies help us improve your browsing experience. "
                "Delta Electronics 800V to 48V DC-DC power module is in production."
            ),
        }
    ]
    evidence = parse_evidence_list(raw)
    refined = refine_evidence(evidence, evaluator.evaluate(evidence, CURRENT_MAPPING))

    text = refined[0]["evidenceText"]
    assert "Cookies" not in text
    assert text.count("in production") == 1  # 重複句子只留一次


def test_refine_carries_verdict_and_score(evaluator, evidence):
    refined = refine_evidence(evidence, evaluator.evaluate(evidence, CURRENT_MAPPING))
    assert refined[0]["verdict"] == CORRECT
    assert refined[0]["score"] == pytest.approx(1.0)


# --- grounding ------------------------------------------------------------


def _grounding(change_set_payload, refined, evaluations):
    return grounding_errors(parse_change_set(change_set_payload), refined, evaluations)


def test_grounding_accepts_correct_evidence(evaluator, evidence):
    evaluations = evaluator.evaluate(evidence, CURRENT_MAPPING)
    refined = refine_evidence(evidence, evaluations)
    assert _grounding(CHANGE_SET, refined, [e.to_dict() for e in evaluations]) == []


def test_grounding_rejects_unknown_evidence_id(evaluator, evidence):
    evaluations = evaluator.evaluate(evidence, CURRENT_MAPPING)
    refined = refine_evidence(evidence, evaluations)
    payload = copy.deepcopy(CHANGE_SET)
    payload["operations"][0]["evidence"] = ["does-not-exist"]

    errors = _grounding(payload, refined, [e.to_dict() for e in evaluations])
    assert any("不在精煉後的證據" in error for error in errors)


def test_grounding_rejects_ambiguous_evidence(evaluator, evidence):
    """ambiguous evidence 可以留給人工看，但不能單獨支持 operation。"""
    evaluations = [e.to_dict() for e in evaluator.evaluate(evidence, CURRENT_MAPPING)]
    refined = refine_evidence(evidence, evaluator.evaluate(evidence, CURRENT_MAPPING))
    evaluations[0]["verdict"] = AMBIGUOUS

    errors = _grounding(CHANGE_SET, refined, evaluations)
    assert any("不是 correct" in error for error in errors)


def test_grounding_rejects_rack_part_mismatch(evaluator, evidence):
    evaluations = evaluator.evaluate(evidence, CURRENT_MAPPING)
    refined = refine_evidence(evidence, evaluations)
    payload = copy.deepcopy(CHANGE_SET)
    payload["operations"][0]["rackPartId"] = "gpu-server"

    errors = _grounding(payload, refined, [e.to_dict() for e in evaluations])
    assert any("與 operation 不符" in error for error in errors)


# --- graph 迴圈 -----------------------------------------------------------


class ScriptedEvaluator:
    """fake evaluator：依呼叫順序回傳預先排好的 verdict。"""

    def __init__(self, verdicts_per_call):
        self.verdicts_per_call = list(verdicts_per_call)
        self.calls = 0

    def evaluate(self, evidence, current_mapping):
        index = min(self.calls, len(self.verdicts_per_call) - 1)
        verdicts = self.verdicts_per_call[index]
        self.calls += 1
        return [
            EvidenceEvaluation(
                item.evidence_id,
                verdicts[position] if position < len(verdicts) else INCORRECT,
                1.0 if (position < len(verdicts) and verdicts[position] == CORRECT) else 0.6,
                {},
                (),
            )
            for position, item in enumerate(evidence)
        ]


class StubCorrectiveRetriever:
    """補救檢索：只回傳事先準備好的 target 結果，不接受任何外部 URL。"""

    def __init__(self, extra_evidence):
        self.extra = extra_evidence
        self.calls: list[int] = []

    def retrieve(self, run_id, attempt, current_mapping, attempted_evidence_ids):
        self.calls.append(attempt)
        return [item for item in self.extra if item["evidenceId"] not in attempted_evidence_ids]


EXTRA_EVIDENCE = [
    {
        **EVIDENCE[0],
        "evidenceId": "delta-official:https://www.deltaww.com/en-US/products/orv3-shelf",
        "sourceUrl": "https://www.deltaww.com/en-US/products/orv3-shelf",
    }
]


def run_graph(services, run_id="run-crag", dry_run=True):
    graph = build_graph(services, checkpointer=memory_checkpointer())
    return start_run(graph, run_id, triggered_by="tester", dry_run=dry_run)


def test_correct_retrieval_skips_correction():
    services = make_services()
    services = services.__class__(
        **{**services.__dict__, "corrective_retriever": StubCorrectiveRetriever(EXTRA_EVIDENCE)}
    )
    state = run_graph(services)

    assert state["status"] == STATUS_COMPLETED
    assert state["retrieval_verdict"] == CORRECT
    assert state["correction_attempts"] == 0
    assert services.corrective_retriever.calls == []
    assert len(state["refined_evidence"]) == 2


def test_ambiguous_retrieval_triggers_correction_then_succeeds():
    retriever = StubCorrectiveRetriever(EXTRA_EVIDENCE)
    services = make_services()
    services = services.__class__(
        **{
            **services.__dict__,
            "retrieval_evaluator": ScriptedEvaluator(
                [
                    [AMBIGUOUS, AMBIGUOUS],  # 第一次評估：不足
                    [CORRECT, CORRECT, CORRECT],  # 補救後：可用
                ]
            ),
            "corrective_retriever": retriever,
        }
    )
    state = run_graph(services)

    assert state["status"] == STATUS_COMPLETED
    assert state["correction_attempts"] == 1
    assert retriever.calls == [1]
    # 補救抓到的 evidence 有加進來
    assert len(state["evidence"]) == 3


def test_persistently_bad_retrieval_fails_closed_before_generation():
    retriever = StubCorrectiveRetriever(EXTRA_EVIDENCE)
    services = make_services()
    services = services.__class__(
        **{
            **services.__dict__,
            "retrieval_evaluator": ScriptedEvaluator([[INCORRECT, INCORRECT]]),
            "corrective_retriever": retriever,
        }
    )
    state = run_graph(services)

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "evidence_gate"
    assert state["correction_attempts"] == MAX_CORRECTION_ATTEMPTS
    # 最重要的一點：completely 沒有進入生成階段。
    assert services.change_set_generator.calls == 0
    assert services.publisher.published == {}


def test_grounding_failure_blocks_merge():
    """generator 引用了未通過 CRAG 的 evidence，必須在 merge 之前擋下。"""
    payload = copy.deepcopy(CHANGE_SET)
    payload["operations"][0]["evidence"] = ["fabricated-evidence-id"]
    services = make_services(change_set=payload)
    state = run_graph(services)

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "validate_grounding"
    assert services.publisher.published == {}


def test_run_repository_records_crag_explainability():
    services = make_services()
    run_graph(services, run_id="run-explain")
    run = services.run_repository.get("run-explain")

    assert run["retrieval_verdict"] == CORRECT
    assert len(run["retrieval_evaluation"]) == 2
    assert run["retrieval_evaluation"][0]["checks"]["primary_source"] is True
    assert len(run["refined_evidence"]) == 2
    assert run["correction_attempts"] == 0
