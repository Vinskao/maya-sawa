"""Validation layer。

分兩層：schema 驗證（schemas/ 內）與這裡的 business 驗證。
validation 一律不 retry：失敗就是失敗，且絕不可進入 publish。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diff import build_diff_summary
from .errors import SchemaError
from .schemas.change_set import ChangeSet
from .schemas.evidence import EvidenceItem
from .schemas.mapping import parse_mapping
from .trusted_sources import is_trusted, trusted_source_ids

# 超過門檻就必須人工確認，避免一次錯誤汙染整份 production mapping。
MAX_OPERATIONS_PER_RUN = 20
MAX_TOTAL_CHANGES = 30


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {"valid": self.is_valid, "errors": list(self.errors), "warnings": list(self.warnings)}


def validate_evidence(evidence: list[EvidenceItem]) -> ValidationResult:
    """evidence 必須全部來自 trusted registry。"""
    errors: list[str] = []
    if not evidence:
        errors.append("evidence: 沒有可用證據")

    for item in evidence:
        if not is_trusted(item.source_id):
            errors.append(
                f"evidence {item.evidence_id}: 來源 {item.source_id} 不在信任清單 "
                f"{list(trusted_source_ids())}"
            )
        if not item.evidence_text.strip():
            errors.append(f"evidence {item.evidence_id}: evidenceText 為空")

    return ValidationResult(errors=tuple(errors))


def validate_change_set(
    change_set: ChangeSet,
    evidence: list[EvidenceItem],
    *,
    max_operations: int = MAX_OPERATIONS_PER_RUN,
) -> ValidationResult:
    """business 驗證：每個 operation 都要有可信 evidence，且變更量在門檻內。"""
    errors: list[str] = []
    warnings: list[str] = []

    evidence_by_id = {item.evidence_id: item for item in evidence}

    if len(change_set) > max_operations:
        errors.append(
            f"change_set: operation 數量 {len(change_set)} 超過門檻 {max_operations}，需人工確認"
        )

    for operation in change_set.operations:
        label = f"{operation.op} {operation.target()}"
        if not operation.evidence_ids:
            errors.append(f"{label}: 缺少 evidence")
            continue

        for evidence_id in operation.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None:
                errors.append(f"{label}: 引用了不存在的 evidenceId {evidence_id}")
                continue
            if not is_trusted(item.source_id):
                errors.append(f"{label}: evidence {evidence_id} 來源不可信")

        if operation.confidence == "low":
            warnings.append(f"{label}: confidence 為 low，建議人工確認")

    return ValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def validate_candidate_mapping(
    candidate: dict[str, Any],
    current: dict[str, Any] | None = None,
    *,
    max_total_changes: int = MAX_TOTAL_CHANGES,
) -> ValidationResult:
    """最終 mapping 驗證：schema + 不得刪除 + diff 不得超出安全門檻。"""
    errors: list[str] = []
    warnings: list[str] = []

    try:
        parse_mapping(candidate)
    except SchemaError as exc:
        errors.extend(exc.errors)

    if current is not None:
        summary = build_diff_summary(current, candidate)
        if summary["removedRackParts"]:
            errors.append(f"mapping: MVP 不允許刪除 rack part {summary['removedRackParts']}")
        if summary["addedRackParts"]:
            # rackParts[].id 綁定前端 PowerRackDiagram 的 hover region。
            errors.append(f"mapping: MVP 不允許新增 rack part {summary['addedRackParts']}")
        if summary["removedProductEntries"]:
            errors.append(
                f"mapping: MVP 不允許刪除 product entry {summary['removedProductEntries']}"
            )
        if summary["totalChanges"] > max_total_changes:
            errors.append(
                f"mapping: 變更筆數 {summary['totalChanges']} 超過安全門檻 {max_total_changes}"
            )
        if summary["totalChanges"] == 0:
            warnings.append("mapping: 與現行版本無差異，無需 publish")

    return ValidationResult(errors=tuple(errors), warnings=tuple(warnings))
