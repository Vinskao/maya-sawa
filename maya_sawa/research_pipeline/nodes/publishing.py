"""Publish / verify / 終結節點。

publish 只能由 approved 且非 dry-run 的路徑到達；每次寫入以 run_id 作為
idempotency key，publish 失敗不盲目 retry。
"""

from __future__ import annotations

from typing import Callable

from ..services import PipelineServices
from ..state import (
    APPROVAL_APPROVED,
    STATUS_COMPLETED,
    STATUS_PUBLISH_VERIFICATION_FAILED,
    STATUS_REJECTED,
    ResearchPipelineState,
    failure,
)

Node = Callable[[ResearchPipelineState], ResearchPipelineState]


def make_backup(services: PipelineServices) -> Node:
    def backup(state: ResearchPipelineState) -> ResearchPipelineState:
        services.run_repository.record(state["run_id"], current_node="backup")
        try:
            version = services.publisher.backup_current(
                state["run_id"], state.get("current_mapping", {})
            )
        except Exception as exc:  # noqa: BLE001 - 任何備份失敗都必須阻止 publish
            return failure("backup", [f"備份失敗：{exc}"])
        services.run_repository.record(state["run_id"], backup_version=version)
        return {"backup_version": version}

    return backup


def make_publish(services: PipelineServices) -> Node:
    def publish(state: ResearchPipelineState) -> ResearchPipelineState:
        if state.get("dry_run", True) or state.get("approval_status") != APPROVAL_APPROVED:
            # 防呆：即使 edge 被改錯，未經核准也不可能真的寫入。
            return failure("publish", ["未經人工核准或處於 dry-run，拒絕 publish"])

        services.run_repository.record(state["run_id"], current_node="publish")
        try:
            version = services.publisher.publish(
                state["run_id"], state.get("candidate_mapping", {})
            )
        except Exception as exc:  # noqa: BLE001
            return failure("publish", [f"publish 失敗：{exc}"])
        services.run_repository.record(state["run_id"], published_version=version)
        return {"published_version": version}

    return publish


def make_verify_publication(services: PipelineServices) -> Node:
    def verify_publication(state: ResearchPipelineState) -> ResearchPipelineState:
        services.run_repository.record(state["run_id"], current_node="verify_publication")
        ok = services.publisher.verify(
            state["run_id"],
            state.get("published_version") or "",
            state.get("candidate_mapping", {}),
        )
        if ok:
            return {}
        # 已寫入但驗證失敗：不自動 rollback，交人工判斷，避免二次錯誤擴大。
        return {
            "status": STATUS_PUBLISH_VERIFICATION_FAILED,
            "failed_node": "verify_publication",
            "error": "publish 後內容驗證失敗，需人工確認是否 rollback",
        }

    return verify_publication


def make_complete(services: PipelineServices) -> Node:
    def complete(state: ResearchPipelineState) -> ResearchPipelineState:
        status = (
            STATUS_REJECTED
            if state.get("approval_status") == "rejected"
            else STATUS_COMPLETED
        )
        services.run_repository.record(
            state["run_id"],
            status=status,
            current_node="complete",
            approved_by=state.get("approved_by"),
            published_version=state.get("published_version"),
        )
        return {"status": status}

    return complete


def make_notify_failure(services: PipelineServices) -> Node:
    def notify_failure(state: ResearchPipelineState) -> ResearchPipelineState:
        stage = state.get("failed_node") or "unknown"
        error = state.get("error") or ""
        services.run_repository.record(
            state["run_id"],
            status=state.get("status"),
            current_node="notify_failure",
            failed_node=stage,
            error=error,
        )
        services.notifier.notify_failure(state["run_id"], stage, error)
        return {}

    return notify_failure
