"""CRAG 節點：檢索評估、補救檢索、知識精煉、evidence gate 與 grounding 驗證。

這幾個節點合起來就是 generator 前的硬性 gate：
沒有通過 evidence_gate 就不會有 change set，
沒有通過 validate_grounding 就不會進入 merge。
"""

from __future__ import annotations

from typing import Any, Callable

from ..crag import (
    MAX_CORRECTION_ATTEMPTS,
    aggregate_verdict,
    grounding_errors,
    refine_evidence,
)
from ..errors import SchemaError
from ..schemas import parse_change_set, parse_evidence_list
from ..services import PipelineServices
from ..state import ResearchPipelineState, failure

Node = Callable[[ResearchPipelineState], ResearchPipelineState]


def make_evaluate_retrieval(services: PipelineServices) -> Node:
    def evaluate_retrieval(state: ResearchPipelineState) -> ResearchPipelineState:
        services.run_repository.record(state["run_id"], current_node="evaluate_retrieval")
        try:
            evidence = parse_evidence_list(state.get("evidence", []))
        except SchemaError as exc:
            return failure("evaluate_retrieval", exc.errors)

        evaluations = services.evaluator().evaluate(evidence, state.get("current_mapping", {}))
        payload = [evaluation.to_dict() for evaluation in evaluations]
        verdict = aggregate_verdict(evaluations)

        services.run_repository.record(
            state["run_id"],
            retrieval_evaluation=payload,
            retrieval_verdict=verdict,
        )
        return {"retrieval_evaluation": payload, "retrieval_verdict": verdict}

    return evaluate_retrieval


def make_corrective_retrieve(services: PipelineServices) -> Node:
    def corrective_retrieve(state: ResearchPipelineState) -> ResearchPipelineState:
        attempt = int(state.get("correction_attempts", 0)) + 1
        services.run_repository.record(
            state["run_id"], current_node="corrective_retrieve", correction_attempts=attempt
        )

        evidence = list(state.get("evidence", []))
        attempted = {item.get("evidenceId") for item in evidence}

        retriever = services.corrective_retriever
        extra: list[dict[str, Any]] = []
        if retriever is not None:
            try:
                extra = retriever.retrieve(
                    state["run_id"], attempt, state.get("current_mapping", {}), attempted
                )
            except Exception as exc:  # noqa: BLE001 - 補救失敗只影響這一輪
                return {
                    "correction_attempts": attempt,
                    "validation_warnings": [
                        *state.get("validation_warnings", []),
                        f"補救檢索第 {attempt} 輪失敗：{exc}",
                    ],
                }

        # 只加入沒抓過的 evidence，避免補救輪次之間重複累積。
        merged = evidence + [item for item in extra if item.get("evidenceId") not in attempted]
        return {"evidence": merged, "correction_attempts": attempt}

    return corrective_retrieve


def make_refine_evidence(services: PipelineServices) -> Node:
    def refine_evidence_node(state: ResearchPipelineState) -> ResearchPipelineState:
        services.run_repository.record(state["run_id"], current_node="refine_evidence")
        try:
            evidence = parse_evidence_list(state.get("evidence", []))
        except SchemaError as exc:
            return failure("refine_evidence", exc.errors)

        evaluations = services.evaluator().evaluate(evidence, state.get("current_mapping", {}))
        refined = refine_evidence(evidence, evaluations)

        services.run_repository.record(state["run_id"], refined_evidence=refined)
        return {"refined_evidence": refined}

    return refine_evidence_node


def make_evidence_gate(services: PipelineServices) -> Node:
    def evidence_gate(state: ResearchPipelineState) -> ResearchPipelineState:
        services.run_repository.record(state["run_id"], current_node="evidence_gate")
        refined = state.get("refined_evidence", [])
        if refined:
            return {}

        attempts = int(state.get("correction_attempts", 0))
        return failure(
            "evidence_gate",
            [
                f"檢索品質不足（verdict={state.get('retrieval_verdict')}，"
                f"補救 {attempts}/{MAX_CORRECTION_ATTEMPTS} 輪後仍無 correct evidence），"
                "禁止生成 change set"
            ],
        )

    return evidence_gate


def make_validate_grounding(services: PipelineServices) -> Node:
    def validate_grounding(state: ResearchPipelineState) -> ResearchPipelineState:
        services.run_repository.record(state["run_id"], current_node="validate_grounding")
        try:
            change_set = parse_change_set(state.get("change_set", {}))
        except SchemaError as exc:
            return failure("validate_grounding", exc.errors)

        errors = grounding_errors(
            change_set,
            state.get("refined_evidence", []),
            state.get("retrieval_evaluation", []),
        )
        if errors:
            return failure("validate_grounding", errors)
        return {}

    return validate_grounding
