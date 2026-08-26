"""LangGraph workflow state。

State 只保存「流程協調需要的資料」。可查詢的業務狀態（操作者、版本、錯誤）
另外寫入 run repository 的業務表，不要讓 API 直接讀 checkpoint 當業務資料。
"""

from __future__ import annotations

from typing import Any, TypedDict

# run status（同時寫入業務表）
STATUS_RUNNING = "running"
STATUS_AWAITING_APPROVAL = "awaiting_approval"
STATUS_COMPLETED = "completed"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"
STATUS_PUBLISH_VERIFICATION_FAILED = "publish_verification_failed"

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"


class ResearchPipelineState(TypedDict, total=False):
    run_id: str
    status: str
    triggered_by: str
    dry_run: bool

    current_mapping: dict[str, Any]
    mapping_provenance: dict[str, Any]
    evidence: list[dict[str, Any]]

    # CRAG：檢索品質評估、補救輪數與精煉後的證據
    retrieval_evaluation: list[dict[str, Any]]
    retrieval_verdict: str
    correction_attempts: int
    refined_evidence: list[dict[str, Any]]

    change_set: dict[str, Any]
    candidate_mapping: dict[str, Any]

    validation_errors: list[str]
    validation_warnings: list[str]
    diff_summary: dict[str, Any]

    approval_status: str
    approved_by: str | None

    backup_version: str | None
    published_version: str | None

    failed_node: str | None
    error: str | None


def initial_state(run_id: str, *, triggered_by: str, dry_run: bool = True) -> ResearchPipelineState:
    return {
        "run_id": run_id,
        "status": STATUS_RUNNING,
        "triggered_by": triggered_by,
        "dry_run": dry_run,
        "evidence": [],
        "retrieval_evaluation": [],
        "retrieval_verdict": "",
        "correction_attempts": 0,
        "refined_evidence": [],
        "validation_errors": [],
        "validation_warnings": [],
        "approval_status": APPROVAL_PENDING,
        "approved_by": None,
        "backup_version": None,
        "published_version": None,
        "failed_node": None,
        "error": None,
    }


def failure(node: str, errors: list[str]) -> ResearchPipelineState:
    """所有節點共用的失敗回傳格式。"""
    return {
        "status": STATUS_FAILED,
        "failed_node": node,
        "error": "; ".join(errors) or f"{node} failed",
        "validation_errors": list(errors),
    }
