"""Change set schema（rack-part 導向）。

LLM 只能輸出 change set，永遠不能輸出完整 production mapping。
MVP 僅允許：
- `update_rack_part`      更新 rack part 的雙語 name / summary
- `add_product_entry`     在既有 rack part 內新增一筆 (company, product)
- `update_product_entry`  更新既有 (company, product) 的 product 名稱或 note

明確拒絕刪除、整份取代，以及「新增 rack part」——
rackParts[].id 必須對應前端 PowerRackDiagram.tsx 的 hover region，
新增 id 會讓前端出現無對應區域的資料。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import SchemaError
from .evidence import CONFIDENCE_LEVELS
from .mapping import LANGUAGES

ALLOWED_OPERATIONS = ("update_rack_part", "add_product_entry", "update_product_entry")
REJECTED_OPERATIONS = (
    "add_rack_part",
    "delete_rack_part",
    "remove_rack_part",
    "delete_product_entry",
    "remove_product_entry",
    "delete_company",
    "delete_product",
    "replace_mapping",
)

RACK_PART_FIELDS = ("name", "summary")
ADD_ENTRY_FIELDS = ("note",)
UPDATE_ENTRY_FIELDS = ("product", "note")

PRODUCT_ENTRY_OPERATIONS = ("add_product_entry", "update_product_entry")

_ALLOWED_OP_FIELDS = ("op", "rackPartId", "company", "product", "data", "evidence", "confidence")


@dataclass(frozen=True)
class ChangeOperation:
    op: str
    rack_part_id: str
    data: dict[str, Any]
    evidence_ids: tuple[str, ...]
    company: str | None = None
    product: str | None = None
    confidence: str = "medium"

    @property
    def is_product_entry_op(self) -> bool:
        return self.op in PRODUCT_ENTRY_OPERATIONS

    def target(self) -> str:
        if self.is_product_entry_op:
            return f"{self.rack_part_id}/{self.company}/{self.product}"
        return self.rack_part_id


@dataclass(frozen=True)
class ChangeSet:
    generated_at: str
    operations: tuple[ChangeOperation, ...] = field(default_factory=tuple)

    def __len__(self) -> int:
        return len(self.operations)


def _text_is_valid(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _parse_evidence_refs(payload: Any, label: str, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(payload, list) or not payload:
        errors.append(f"{label}: evidence 必須是非空陣列")
        return ()

    refs: list[str] = []
    for ref in payload:
        if isinstance(ref, str) and ref.strip():
            refs.append(ref)
        elif isinstance(ref, dict) and isinstance(ref.get("evidenceId"), str):
            refs.append(ref["evidenceId"])
        else:
            errors.append(f"{label}: evidence 項目必須是 evidenceId 字串")
    return tuple(refs)


def _validate_rack_part_data(data: dict[str, Any], label: str, errors: list[str]) -> None:
    unknown = sorted(set(data) - set(RACK_PART_FIELDS))
    if unknown:
        errors.append(f"{label}: data 含未知欄位 {unknown}")

    for key in RACK_PART_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, dict):
            errors.append(f"{label}: data.{key} 必須是 {{en, zh}} 物件")
            continue
        unknown_lang = sorted(set(value) - set(LANGUAGES))
        if unknown_lang:
            errors.append(f"{label}: data.{key} 含未知語言 {unknown_lang}")
        for language, text in value.items():
            if text is not None and not isinstance(text, str):
                errors.append(f"{label}: data.{key}.{language} 必須是字串或 null")


def _validate_entry_data(
    data: dict[str, Any], allowed: tuple[str, ...], label: str, errors: list[str]
) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        errors.append(f"{label}: data 含未知欄位 {unknown}")
    for key, value in data.items():
        if value is not None and not isinstance(value, str):
            errors.append(f"{label}: data.{key} 必須是字串或 null")


def _parse_operation(payload: Any, index: int, errors: list[str]) -> ChangeOperation | None:
    label = f"operations[{index}]"
    if not isinstance(payload, dict):
        errors.append(f"{label}: 必須是物件")
        return None

    unknown = sorted(set(payload) - set(_ALLOWED_OP_FIELDS))
    if unknown:
        errors.append(f"{label}: 未知欄位 {unknown}")

    op = payload.get("op")
    if op in REJECTED_OPERATIONS:
        errors.append(f"{label}: MVP 拒絕刪除／新增 rack part／整份取代操作 {op}")
        return None
    if op not in ALLOWED_OPERATIONS:
        errors.append(f"{label}: 不支援的 op {op!r}")
        return None

    rack_part_id = payload.get("rackPartId")
    if not _text_is_valid(rack_part_id):
        errors.append(f"{label}: rackPartId 無效")

    is_entry_op = op in PRODUCT_ENTRY_OPERATIONS
    company = payload.get("company")
    product = payload.get("product")
    if is_entry_op:
        # (company, product) 是 product entry 的識別，不是要寫入的內容。
        if not _text_is_valid(company):
            errors.append(f"{label}: {op} 需要 company")
        if not _text_is_valid(product):
            errors.append(f"{label}: {op} 需要 product")
    else:
        if company is not None or product is not None:
            errors.append(f"{label}: {op} 不應帶 company/product")

    data = payload.get("data")
    if not isinstance(data, dict) or not data:
        if op == "add_product_entry":
            # 新增只靠識別欄位就足夠，note 可省略。
            data = {}
        else:
            errors.append(f"{label}: data 必須是非空物件")
            data = {}
    elif op == "update_rack_part":
        _validate_rack_part_data(data, label, errors)
    elif op == "add_product_entry":
        _validate_entry_data(data, ADD_ENTRY_FIELDS, label, errors)
    else:
        _validate_entry_data(data, UPDATE_ENTRY_FIELDS, label, errors)

    evidence_ids = _parse_evidence_refs(payload.get("evidence"), label, errors)

    confidence = payload.get("confidence", "medium")
    if confidence not in CONFIDENCE_LEVELS:
        errors.append(f"{label}: confidence 必須是 {list(CONFIDENCE_LEVELS)}")

    if errors:
        return None

    return ChangeOperation(
        op=op,
        rack_part_id=rack_part_id,
        company=company if is_entry_op else None,
        product=product if is_entry_op else None,
        data=dict(data),
        evidence_ids=evidence_ids,
        confidence=confidence,
    )


def parse_change_set(payload: Any) -> ChangeSet:
    """解析 LLM 產出的 change set；malformed 一律 raise SchemaError。"""
    if not isinstance(payload, dict):
        raise SchemaError(["change_set: 必須是物件"])

    errors: list[str] = []
    unknown = sorted(set(payload) - {"generatedAt", "operations"})
    if unknown:
        errors.append(f"change_set: 未知欄位 {unknown}")

    generated_at = payload.get("generatedAt")
    if not isinstance(generated_at, str) or not generated_at.strip():
        errors.append("change_set: 缺少 generatedAt")

    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list):
        errors.append("change_set: operations 必須是陣列")
        raw_operations = []

    operations: list[ChangeOperation] = []
    for index, entry in enumerate(raw_operations):
        local: list[str] = []
        operation = _parse_operation(entry, index, local)
        errors.extend(local)
        if operation is not None:
            operations.append(operation)

    seen: set[tuple[str, str]] = set()
    for operation in operations:
        marker = (operation.op, operation.target())
        if marker in seen:
            errors.append(f"change_set: 重複的操作 {operation.op} {operation.target()}")
        seen.add(marker)

    if errors:
        raise SchemaError(errors)

    return ChangeSet(generated_at=generated_at, operations=tuple(operations))
