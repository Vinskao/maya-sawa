"""LangGraph workflow 定義。

固定流程，條件 edge 只依據明確的 state 欄位判斷；
LLM 不參與「是否 publish」的決策。
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from . import nodes
from .crag import CORRECT, MAX_CORRECTION_ATTEMPTS
from .services import PipelineServices
from .state import (
    APPROVAL_APPROVED,
    STATUS_FAILED,
    STATUS_PUBLISH_VERIFICATION_FAILED,
    ResearchPipelineState,
)

FAILURE_STATUSES = (STATUS_FAILED, STATUS_PUBLISH_VERIFICATION_FAILED)


def _failed(state: ResearchPipelineState) -> bool:
    return state.get("status") in FAILURE_STATUSES


def _route_after(next_node: str):
    """任何節點失敗都導向 notify_failure，永遠不會落到 publish。"""

    def route(state: ResearchPipelineState) -> str:
        return "notify_failure" if _failed(state) else next_node

    return route


def _route_after_evaluation(state: ResearchPipelineState) -> str:
    """CRAG 分流：correct 才進精煉，其餘走補救檢索，超過上限就交給 evidence_gate 擋下。"""
    if _failed(state):
        return "notify_failure"
    if state.get("retrieval_verdict") == CORRECT:
        return "refine_evidence"
    if int(state.get("correction_attempts", 0)) >= MAX_CORRECTION_ATTEMPTS:
        # 兩輪補救後仍不是 correct：交給 evidence_gate 統一 fail closed。
        return "refine_evidence"
    return "corrective_retrieve"


def _route_after_review(state: ResearchPipelineState) -> str:
    if _failed(state):
        return "notify_failure"
    # dry-run 在 prepare_review 之後直接完成，不進入審核與 publish。
    return "complete" if state.get("dry_run", True) else "await_approval"


def _route_after_approval(state: ResearchPipelineState) -> str:
    if _failed(state):
        return "notify_failure"
    return "backup" if state.get("approval_status") == APPROVAL_APPROVED else "complete"


def build_graph(services: PipelineServices, checkpointer: Any = None):
    """建立並 compile workflow。checkpointer 由呼叫端決定（memory / postgres）。"""
    builder = StateGraph(ResearchPipelineState)

    builder.add_node("load_current_mapping", nodes.make_load_current_mapping(services))
    builder.add_node("collect_evidence", nodes.make_collect_evidence(services))
    builder.add_node("evaluate_retrieval", nodes.make_evaluate_retrieval(services))
    builder.add_node("corrective_retrieve", nodes.make_corrective_retrieve(services))
    builder.add_node("refine_evidence", nodes.make_refine_evidence(services))
    builder.add_node("evidence_gate", nodes.make_evidence_gate(services))
    builder.add_node("generate_change_set", nodes.make_generate_change_set(services))
    builder.add_node("validate_grounding", nodes.make_validate_grounding(services))
    builder.add_node("validate_change_set", nodes.make_validate_change_set(services))
    builder.add_node("merge_change_set", nodes.make_merge_change_set(services))
    builder.add_node("validate_candidate", nodes.make_validate_candidate(services))
    builder.add_node("prepare_review", nodes.make_prepare_review(services))
    builder.add_node("await_approval", nodes.make_await_approval(services))
    builder.add_node("backup", nodes.make_backup(services))
    builder.add_node("publish", nodes.make_publish(services))
    builder.add_node("verify_publication", nodes.make_verify_publication(services))
    builder.add_node("complete", nodes.make_complete(services))
    builder.add_node("notify_failure", nodes.make_notify_failure(services))

    builder.add_edge(START, "load_current_mapping")

    linear = [
        ("load_current_mapping", "collect_evidence"),
        ("collect_evidence", "evaluate_retrieval"),
        ("corrective_retrieve", "evaluate_retrieval"),
        ("refine_evidence", "evidence_gate"),
        ("evidence_gate", "generate_change_set"),
        ("generate_change_set", "validate_grounding"),
        ("validate_grounding", "validate_change_set"),
        ("validate_change_set", "merge_change_set"),
        ("merge_change_set", "validate_candidate"),
        ("validate_candidate", "prepare_review"),
        ("backup", "publish"),
        ("publish", "verify_publication"),
        ("verify_publication", "complete"),
    ]
    for source, target in linear:
        builder.add_conditional_edges(
            source, _route_after(target), {target: target, "notify_failure": "notify_failure"}
        )

    builder.add_conditional_edges(
        "evaluate_retrieval",
        _route_after_evaluation,
        {
            "refine_evidence": "refine_evidence",
            "corrective_retrieve": "corrective_retrieve",
            "notify_failure": "notify_failure",
        },
    )
    builder.add_conditional_edges(
        "prepare_review",
        _route_after_review,
        {
            "complete": "complete",
            "await_approval": "await_approval",
            "notify_failure": "notify_failure",
        },
    )
    builder.add_conditional_edges(
        "await_approval",
        _route_after_approval,
        {"backup": "backup", "complete": "complete", "notify_failure": "notify_failure"},
    )

    builder.add_edge("complete", END)
    builder.add_edge("notify_failure", END)

    return builder.compile(checkpointer=checkpointer)


def run_config(run_id: str) -> dict[str, Any]:
    """run_id 即 LangGraph thread_id：同一個 run 永遠對應同一條 checkpoint 線。"""
    return {"configurable": {"thread_id": run_id}}
