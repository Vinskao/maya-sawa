"""Deterministic merger（rack-part 導向）。

唯一被允許改寫 mapping 的地方。純函式：相同輸入必然得到相同輸出，
不讀時鐘、不讀環境變數、不做 I/O。

product entry 是陣列，順序即前端顯示順序，因此既有順序一律保留，
新增的 entry 依 operation 排序後附加在該 rack part 尾端。
"""

from __future__ import annotations

import copy
from typing import Any

from .errors import SchemaError
from .schemas.change_set import ChangeOperation, ChangeSet
from .schemas.mapping import LANGUAGES, entry_key, rack_part_index


class MergeError(SchemaError):
    """change set 無法安全套用到目前 mapping。"""


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _clean(value: str) -> str:
    return value.strip()


def _merge_localized(target: dict[str, Any], key: str, value: dict[str, Any]) -> None:
    """雙語欄位逐語言合併；空值不覆蓋既有內容。"""
    current = target.get(key)
    if not isinstance(current, dict):
        current = {}
    merged = dict(current)
    for language in LANGUAGES:
        text = value.get(language)
        if _is_empty(text):
            continue
        merged[language] = _clean(text)
    target[key] = {language: merged[language] for language in LANGUAGES if language in merged}


def _apply_rack_part_update(part: dict[str, Any], data: dict[str, Any]) -> None:
    for key in sorted(data):
        value = data[key]
        if isinstance(value, dict):
            _merge_localized(part, key, value)


def _find_entry(part: dict[str, Any], key: tuple[str, str]) -> dict[str, Any] | None:
    for entry in part.get("products", []):
        if isinstance(entry, dict) and entry_key(entry) == key:
            return entry
    return None


def _apply_operation(
    parts: dict[str, dict[str, Any]], operation: ChangeOperation, errors: list[str]
) -> None:
    label = f"{operation.op} {operation.target()}"
    part = parts.get(operation.rack_part_id)
    if part is None:
        # rackPart id 綁定前端 hover region，不存在就不可能是安全的變更。
        errors.append(f"{label}: rackPart {operation.rack_part_id} 不存在")
        return

    if operation.op == "update_rack_part":
        _apply_rack_part_update(part, operation.data)
        return

    products = part.setdefault("products", [])
    key = (operation.company or "", operation.product or "")

    if operation.op == "add_product_entry":
        if _find_entry(part, key) is not None:
            errors.append(f"{label}: product entry 已存在，add 不得覆蓋")
            return
        entry = {"company": _clean(key[0]), "product": _clean(key[1])}
        note = operation.data.get("note")
        entry["note"] = _clean(note) if not _is_empty(note) else ""
        products.append(entry)
        return

    if operation.op == "update_product_entry":
        entry = _find_entry(part, key)
        if entry is None:
            errors.append(f"{label}: update 目標 product entry 不存在")
            return

        new_product = operation.data.get("product")
        if not _is_empty(new_product):
            renamed = (key[0], _clean(new_product))
            if renamed != key and _find_entry(part, renamed) is not None:
                errors.append(f"{label}: 改名後與既有 product entry {renamed} 衝突")
                return
            entry["product"] = _clean(new_product)

        note = operation.data.get("note")
        if not _is_empty(note):
            entry["note"] = _clean(note)
        return

    errors.append(f"{label}: 未知 operation")


def apply_change_set(current_mapping: dict[str, Any], change_set: ChangeSet) -> dict[str, Any]:
    """套用 change set 並回傳候選 mapping；不修改輸入。

    任何一個 operation 失敗即整批拒絕（all-or-nothing），避免半套用狀態。
    """
    candidate = copy.deepcopy(current_mapping)
    parts = rack_part_index(candidate)

    errors: list[str] = []
    # 先 rack part、再新增 entry、最後更新 entry，讓同一批 change set 可以
    # 「新增一筆並在之後修正」；同類操作以 target 排序確保輸出穩定。
    order = {"update_rack_part": 0, "add_product_entry": 1, "update_product_entry": 2}
    ordered = sorted(change_set.operations, key=lambda op: (order[op.op], op.target()))
    for operation in ordered:
        _apply_operation(parts, operation, errors)

    if errors:
        raise MergeError(errors)

    return candidate
