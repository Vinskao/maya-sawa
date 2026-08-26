"""人工審核節點。

prepare_review 之後：
- dry-run 直接完成，不得產生任何 publish 副作用。
- 非 dry-run 一律 interrupt 等待人工 approve，沒有其他進入 publish 的路徑。
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.types import interrupt

from ..services import PipelineServices
from ..state import (
    APPROVAL_APPROVED,
    APPROVAL_REJECTED,
    STATUS_AWAITING_APPROVAL,
    ResearchPipelineState,
)

Node = Callable[[ResearchPipelineState], ResearchPipelineState]


def review_payload(state: ResearchPipelineState) -> dict[str, Any]:
    """交給審核者的資訊；同時是 interrupt 的 payload。"""
    return {
        "runId": state["run_id"],
        "mappingProvenance": state.get("mapping_provenance", {}),
        "evidence": state.get("evidence", []),
        "retrievalEvaluation": state.get("retrieval_evaluation", []),
        "retrievalVerdict": state.get("retrieval_verdict", ""),
        "correctionAttempts": state.get("correction_attempts", 0),
        "refinedEvidence": state.get("refined_evidence", []),
        "changeSet": state.get("change_set", {}),
        "diffSummary": state.get("diff_summary", {}),
        "validationWarnings": state.get("validation_warnings", []),
        "dryRun": state.get("dry_run", True),
    }


def make_prepare_review(services: PipelineServices) -> Node:
    def prepare_review(state: ResearchPipelineState) -> ResearchPipelineState:
        payload = review_payload(state)
        services.run_repository.record(
            state["run_id"],
            current_node="prepare_review",
            mapping_provenance=payload["mappingProvenance"],
            evidence=payload["evidence"],
            retrieval_evaluation=payload["retrievalEvaluation"],
            retrieval_verdict=payload["retrievalVerdict"],
            correction_attempts=payload["correctionAttempts"],
            refined_evidence=payload["refinedEvidence"],
            change_set=payload["changeSet"],
            diff_summary=payload["diffSummary"],
            validation_warnings=payload["validationWarnings"],
        )
        return {}

    return prepare_review


def make_await_approval(services: PipelineServices) -> Node:
    def await_approval(state: ResearchPipelineState) -> ResearchPipelineState:
        services.run_repository.record(
            state["run_id"],
            status=STATUS_AWAITING_APPROVAL,
            current_node="await_approval",
        )
        # interrupt 之後 graph 會停在這裡；resume 時本節點會重新執行，
        # 因此這裡不能有 publish 之類的副作用。
        decision = interrupt(review_payload(state))
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        approved_by = decision.get("approvedBy") if isinstance(decision, dict) else None

        return {
            "approval_status": APPROVAL_APPROVED if approved else APPROVAL_REJECTED,
            "approved_by": approved_by,
        }

    return await_approval
