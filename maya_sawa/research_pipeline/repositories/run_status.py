"""Run 狀態轉移規則與 repository 錯誤型別。

兩種 repository 實作（記憶體、PostgreSQL）共用同一組規則，
避免 API 測試與正式行為不一致。
"""

from __future__ import annotations

from ..state import (
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PUBLISH_VERIFICATION_FAILED,
    STATUS_REJECTED,
    STATUS_RUNNING,
)


class RunRepositoryError(Exception):
    """Repository 層的基底錯誤。"""


class RunNotFoundError(RunRepositoryError):
    pass


class RunAlreadyExistsError(RunRepositoryError):
    pass


class RunConcurrencyError(RunRepositoryError):
    """revision 不符：run 已被其他人更新。"""


class InvalidStatusTransition(RunRepositoryError):
    pass


TERMINAL_STATUSES = frozenset(
    {STATUS_COMPLETED, STATUS_REJECTED, STATUS_FAILED, STATUS_PUBLISH_VERIFICATION_FAILED}
)

_NON_TERMINAL_TARGETS = frozenset(
    {
        STATUS_RUNNING,
        STATUS_AWAITING_APPROVAL,
        STATUS_COMPLETED,
        STATUS_REJECTED,
        STATUS_FAILED,
        STATUS_PUBLISH_VERIFICATION_FAILED,
    }
)

# 終態不得再轉出（同狀態的重複寫入視為 no-op，允許 resume 時重跑節點）。
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_RUNNING: _NON_TERMINAL_TARGETS,
    STATUS_AWAITING_APPROVAL: _NON_TERMINAL_TARGETS,
    **{status: frozenset({status}) for status in TERMINAL_STATUSES},
}

UPDATABLE_FIELDS = (
    "status",
    "triggered_by",
    "dry_run",
    "current_node",
    "mapping_provenance",
    "evidence",
    "retrieval_evaluation",
    "retrieval_verdict",
    "correction_attempts",
    "refined_evidence",
    "change_set",
    "diff_summary",
    "validation_warnings",
    "approval_decision",
    "approved_by",
    "approval_note",
    "approval_decided_at",
    "backup_version",
    "published_version",
    "failed_node",
    "error",
)

JSON_FIELDS = (
    "mapping_provenance",
    "evidence",
    "retrieval_evaluation",
    "refined_evidence",
    "change_set",
    "diff_summary",
    "validation_warnings",
)


def assert_transition(current: str, new: str) -> None:
    if current == new:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if new not in allowed:
        raise InvalidStatusTransition(f"不允許的狀態轉移：{current} -> {new}")


def assert_updatable_fields(fields: dict[str, object]) -> None:
    unknown = sorted(set(fields) - set(UPDATABLE_FIELDS))
    if unknown:
        raise RunRepositoryError(f"未知的 run 欄位：{unknown}")
