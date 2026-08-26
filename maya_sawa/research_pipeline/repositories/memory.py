"""記憶體版 run repository。

行為必須與 PostgreSQL 版一致（同一組狀態轉移與 revision 規則），
讓 API 單元測試不需要資料庫也能反映正式行為。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..state import STATUS_AWAITING_APPROVAL, STATUS_RUNNING
from .run_status import (
    InvalidStatusTransition,
    RunAlreadyExistsError,
    RunConcurrencyError,
    RunNotFoundError,
    RunRepositoryError,
    assert_transition,
    assert_updatable_fields,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class InMemoryRunRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}

    # --- 讀取 ---------------------------------------------------------
    def get(self, run_id: str) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        return dict(run) if run else None

    def require(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        if run is None:
            raise RunNotFoundError(f"run 不存在：{run_id}")
        return run

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        runs = sorted(self.runs.values(), key=lambda run: run["created_at"], reverse=True)
        return [dict(run) for run in runs[:limit]]

    # --- 寫入 ---------------------------------------------------------
    def create(
        self,
        run_id: str,
        *,
        triggered_by: str,
        dry_run: bool = True,
        status: str = STATUS_RUNNING,
    ) -> dict[str, Any]:
        if run_id in self.runs:
            raise RunAlreadyExistsError(f"run_id 已存在：{run_id}")
        now = _now()
        self.runs[run_id] = {
            "run_id": run_id,
            "status": status,
            "triggered_by": triggered_by,
            "dry_run": dry_run,
            "current_node": None,
            "mapping_provenance": None,
            "evidence": None,
            "retrieval_evaluation": None,
            "retrieval_verdict": None,
            "correction_attempts": 0,
            "refined_evidence": None,
            "change_set": None,
            "diff_summary": None,
            "validation_warnings": None,
            "approval_decision": None,
            "approved_by": None,
            "approval_note": None,
            "approval_decided_at": None,
            "backup_version": None,
            "published_version": None,
            "failed_node": None,
            "error": None,
            "revision": 0,
            "created_at": now,
            "updated_at": now,
        }
        return self.get(run_id)  # type: ignore[return-value]

    def update(
        self, run_id: str, *, expected_revision: int | None = None, **fields: Any
    ) -> dict[str, Any]:
        assert_updatable_fields(fields)
        run = self.runs.get(run_id)
        if run is None:
            raise RunNotFoundError(f"run 不存在：{run_id}")

        if expected_revision is not None and run["revision"] != expected_revision:
            raise RunConcurrencyError(
                f"run {run_id} 已被更新（expected {expected_revision}, actual {run['revision']}）"
            )

        new_status = fields.get("status")
        if new_status is not None:
            assert_transition(run["status"], new_status)

        run.update({key: value for key, value in fields.items() if value is not None})
        run["revision"] += 1
        run["updated_at"] = _now()
        return self.get(run_id)  # type: ignore[return-value]

    def record(self, run_id: str, **fields: Any) -> dict[str, Any]:
        """Graph node 用的 upsert；沒有 run 就以目前欄位建立。"""
        if run_id not in self.runs:
            self.create(
                run_id,
                triggered_by=fields.get("triggered_by") or "unknown",
                dry_run=bool(fields.get("dry_run", True)),
            )
        return self.update(run_id, **fields)

    def record_approval(
        self,
        run_id: str,
        *,
        decision: str,
        actor: str,
        note: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """記錄人工審核決定；同一個 run 只接受一次決定。"""
        run = self.require(run_id)
        if run["status"] != STATUS_AWAITING_APPROVAL:
            raise InvalidStatusTransition(
                f"run {run_id} 目前狀態為 {run['status']}，只有 awaiting_approval 可以審核"
            )
        if run["approval_decision"] is not None:
            raise RunRepositoryError(
                f"run {run_id} 已有審核決定：{run['approval_decision']}"
            )
        return self.update(
            run_id,
            expected_revision=expected_revision,
            approval_decision=decision,
            approved_by=actor,
            approval_note=note,
            approval_decided_at=_now(),
        )
