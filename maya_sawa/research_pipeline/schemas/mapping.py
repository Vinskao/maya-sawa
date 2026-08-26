"""Research Zone rack-part mapping schema。

對齊正式 production 物件（OCI `company-product-mapping.json`，由 TYMB
`/tymb/resources/company-product-mapping` 原樣代理，沒有任何轉換）：

    {
      "version": "1",
      "updatedAt": "2026-06-18",
      "note": "...",
      "rackParts": [
        {"id": "dc-pdu",
         "name": {"en": "...", "zh": "..."},
         "summary": {"en": "...", "zh": "..."},
         "products": [{"company": "...", "product": "...", "note": ""}]}
      ]
    }

`rackParts[].id` 必須對應前端 PowerRackDiagram.tsx 的 hover region，
因此 MVP 不允許新增或刪除 rack part。
"""

from __future__ import annotations

from typing import Any

from ..errors import SchemaError

LANGUAGES = ("en", "zh")

RACK_PART_FIELDS = ("id", "name", "summary", "products")
PRODUCT_ENTRY_FIELDS = ("company", "product", "note")
REQUIRED_PRODUCT_ENTRY_FIELDS = ("company", "product")

# 前端只讀 rackParts，其餘 metadata 是附加資訊，允許但不強制。
REQUIRED_TOP_LEVEL = ("version", "updatedAt", "rackParts")
OPTIONAL_TOP_LEVEL = ("note", "status", "sources", "lastSuccessfulPublishAt")

MAPPING_STATUSES = ("fresh", "stale", "validation_failed", "manual_review_required")

CompanyMapping = dict[str, Any]


def entry_key(entry: dict[str, Any]) -> tuple[str, str]:
    """product entry 的識別：同一個 rack part 內 (company, product) 唯一。"""
    return (str(entry.get("company", "")), str(entry.get("product", "")))


def rack_part_index(mapping: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {part["id"]: part for part in mapping.get("rackParts", []) if isinstance(part, dict) and "id" in part}


def _validate_localized(payload: Any, label: str, errors: list[str], *, required: bool) -> None:
    if payload is None:
        if required:
            errors.append(f"{label}: 缺少雙語欄位")
        return
    if not isinstance(payload, dict):
        errors.append(f"{label}: 必須是 {{en, zh}} 物件")
        return

    unknown = sorted(set(payload) - set(LANGUAGES))
    if unknown:
        errors.append(f"{label}: 未知語言 {unknown}")
    for language in LANGUAGES:
        value = payload.get(language)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}.{language}: 缺少或空白")


def parse_mapping(payload: Any) -> CompanyMapping:
    """驗證 mapping 結構；不合法一律 raise SchemaError。"""
    if not isinstance(payload, dict):
        raise SchemaError(["mapping: 必須是物件"])

    errors: list[str] = []
    unknown = sorted(set(payload) - set(REQUIRED_TOP_LEVEL) - set(OPTIONAL_TOP_LEVEL))
    if unknown:
        errors.append(f"mapping: 未知欄位 {unknown}")

    for name in ("version", "updatedAt"):
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"mapping: 缺少 {name}")

    status = payload.get("status")
    if status is not None and status not in MAPPING_STATUSES:
        errors.append(f"mapping: status 必須是 {list(MAPPING_STATUSES)}")
    if payload.get("sources") is not None and not isinstance(payload["sources"], list):
        errors.append("mapping: sources 必須是陣列")

    rack_parts = payload.get("rackParts")
    if not isinstance(rack_parts, list) or not rack_parts:
        errors.append("mapping: rackParts 必須是非空陣列")
        raise SchemaError(errors)

    seen_ids: set[str] = set()
    for index, part in enumerate(rack_parts):
        label = f"rackParts[{index}]"
        if not isinstance(part, dict):
            errors.append(f"{label}: 必須是物件")
            continue

        unknown_part = sorted(set(part) - set(RACK_PART_FIELDS))
        if unknown_part:
            errors.append(f"{label}: 未知欄位 {unknown_part}")

        part_id = part.get("id")
        if not isinstance(part_id, str) or not part_id.strip():
            errors.append(f"{label}: 缺少 id")
        else:
            label = f"rackParts.{part_id}"
            if part_id in seen_ids:
                errors.append(f"mapping: 重複的 rackPart id {part_id}")
            seen_ids.add(part_id)

        _validate_localized(part.get("name"), f"{label}.name", errors, required=True)
        _validate_localized(part.get("summary"), f"{label}.summary", errors, required=True)

        products = part.get("products")
        if not isinstance(products, list):
            errors.append(f"{label}.products: 必須是陣列")
            continue

        seen_entries: set[tuple[str, str]] = set()
        for entry_index, entry in enumerate(products):
            entry_label = f"{label}.products[{entry_index}]"
            if not isinstance(entry, dict):
                errors.append(f"{entry_label}: 必須是物件")
                continue

            unknown_entry = sorted(set(entry) - set(PRODUCT_ENTRY_FIELDS))
            if unknown_entry:
                errors.append(f"{entry_label}: 未知欄位 {unknown_entry}")

            for name in REQUIRED_PRODUCT_ENTRY_FIELDS:
                value = entry.get(name)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f"{entry_label}: 缺少必要顯示欄位 {name}")

            note = entry.get("note")
            if note is not None and not isinstance(note, str):
                errors.append(f"{entry_label}: note 必須是字串")

            key = entry_key(entry)
            if key in seen_entries:
                errors.append(f"{label}: 重複的 product entry {key}")
            seen_entries.add(key)

    if errors:
        raise SchemaError(errors)
    return payload
