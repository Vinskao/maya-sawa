"""Mapping diff summary（rack-part 導向）。

供人工審核與「diff 是否超過安全門檻」判斷使用，輸出必須 deterministic。
"""

from __future__ import annotations

from typing import Any

from .schemas.mapping import LANGUAGES, entry_key, rack_part_index


def _entries(part: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    products = part.get("products", [])
    if not isinstance(products, list):
        return {}
    return {entry_key(entry): entry for entry in products if isinstance(entry, dict)}


def _localized_changes(before: dict[str, Any], after: dict[str, Any], key: str) -> list[str]:
    left = before.get(key) if isinstance(before.get(key), dict) else {}
    right = after.get(key) if isinstance(after.get(key), dict) else {}
    return [f"{key}.{language}" for language in LANGUAGES if left.get(language) != right.get(language)]


def _entry_label(rack_part_id: str, key: tuple[str, str]) -> str:
    return f"{rack_part_id}/{key[0]}/{key[1]}"


def build_diff_summary(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    before_parts = rack_part_index(before)
    after_parts = rack_part_index(after)

    added_rack_parts = sorted(set(after_parts) - set(before_parts))
    removed_rack_parts = sorted(set(before_parts) - set(after_parts))

    updated_rack_parts: list[dict[str, Any]] = []
    added_entries: list[str] = []
    removed_entries: list[str] = []
    updated_entries: list[dict[str, Any]] = []

    for part_id in sorted(set(before_parts) & set(after_parts)):
        before_part = before_parts[part_id]
        after_part = after_parts[part_id]

        fields = _localized_changes(before_part, after_part, "name") + _localized_changes(
            before_part, after_part, "summary"
        )
        if fields:
            updated_rack_parts.append({"rackPartId": part_id, "fields": fields})

        before_entries = _entries(before_part)
        after_entries = _entries(after_part)

        added_entries.extend(
            _entry_label(part_id, key) for key in sorted(set(after_entries) - set(before_entries))
        )
        removed_entries.extend(
            _entry_label(part_id, key) for key in sorted(set(before_entries) - set(after_entries))
        )
        for key in sorted(set(before_entries) & set(after_entries)):
            changed = sorted(
                field
                for field in ("company", "product", "note")
                if before_entries[key].get(field, "") != after_entries[key].get(field, "")
            )
            if changed:
                updated_entries.append(
                    {"productEntry": _entry_label(part_id, key), "fields": changed}
                )

    for part_id in added_rack_parts:
        added_entries.extend(_entry_label(part_id, key) for key in sorted(_entries(after_parts[part_id])))
    for part_id in removed_rack_parts:
        removed_entries.extend(
            _entry_label(part_id, key) for key in sorted(_entries(before_parts[part_id]))
        )

    total = (
        len(added_rack_parts)
        + len(removed_rack_parts)
        + len(updated_rack_parts)
        + len(added_entries)
        + len(removed_entries)
        + len(updated_entries)
    )

    return {
        "addedRackParts": added_rack_parts,
        "removedRackParts": removed_rack_parts,
        "updatedRackParts": updated_rack_parts,
        "addedProductEntries": sorted(added_entries),
        "removedProductEntries": sorted(removed_entries),
        "updatedProductEntries": updated_entries,
        "totalChanges": total,
    }
