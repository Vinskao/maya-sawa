"""Change-set 生成 prompt。

刻意不重用 qa_chain 的 prompt：這裡的目標不是回答問題，而是在極窄的
詞彙內產生結構化 change set。模型只看得到精煉後的證據與目標 rack part
的現況，看不到完整 production mapping。
"""

from __future__ import annotations

import json
from typing import Any

from ..schemas.change_set import ALLOWED_OPERATIONS
from ..schemas.mapping import rack_part_index

SYSTEM_MESSAGE = (
    "You produce structured change sets for a hardware research dataset. "
    "You never invent facts and you never output prose."
)

_RULES = f"""Rules (violating any of these makes the answer invalid):
1. Output a single JSON object and nothing else. No markdown, no explanation.
2. Allowed operations: {", ".join(ALLOWED_OPERATIONS)}. Any other operation is forbidden.
3. Deletions and adding new rack parts are forbidden.
4. Every operation MUST cite at least one evidenceId from the EVIDENCE section, verbatim.
5. Only use rackPartId values listed in the CURRENT STATE section.
6. Base every field strictly on the evidence text. If the evidence does not state it, omit it.
7. If the evidence does not support any change, return {{"generatedAt": "...", "operations": []}}.
8. Never output the full mapping."""

_SHAPE = """Output shape:
{
  "generatedAt": "<ISO-8601 timestamp>",
  "operations": [
    {"op": "add_product_entry", "rackPartId": "...", "company": "...", "product": "...",
     "data": {"note": "..."}, "evidence": ["<evidenceId>"], "confidence": "high|medium|low"},
    {"op": "update_product_entry", "rackPartId": "...", "company": "...", "product": "...",
     "data": {"product": "...", "note": "..."}, "evidence": ["<evidenceId>"]},
    {"op": "update_rack_part", "rackPartId": "...",
     "data": {"name": {"en": "...", "zh": "..."}, "summary": {"en": "...", "zh": "..."}},
     "evidence": ["<evidenceId>"]}
  ]
}"""


def summarize_current_state(
    mapping: dict[str, Any], rack_part_ids: list[str]
) -> list[dict[str, Any]]:
    """只給模型看相關 rack part 的現況，避免它輸出整份 mapping。"""
    index = rack_part_index(mapping)
    summary: list[dict[str, Any]] = []
    for rack_part_id in sorted(set(rack_part_ids)):
        part = index.get(rack_part_id)
        if part is None:
            continue
        summary.append(
            {
                "rackPartId": rack_part_id,
                "name": part.get("name", {}).get("en"),
                "existingEntries": [
                    {"company": entry.get("company"), "product": entry.get("product")}
                    for entry in part.get("products", [])
                    if isinstance(entry, dict)
                ],
            }
        )
    return summary


def build_change_set_prompt(
    refined_evidence: list[dict[str, Any]], current_mapping: dict[str, Any]
) -> str:
    rack_part_ids = [
        item.get("rackPartId") for item in refined_evidence if item.get("rackPartId")
    ]
    evidence_block = [
        {
            "evidenceId": item.get("evidenceId"),
            "rackPartId": item.get("rackPartId"),
            "company": item.get("company"),
            "product": item.get("product"),
            "sourceUrl": item.get("sourceUrl"),
            "text": item.get("evidenceText"),
        }
        for item in refined_evidence
    ]

    return "\n\n".join(
        [
            _RULES,
            _SHAPE,
            "CURRENT STATE (the only rackPartId values you may use):\n"
            + json.dumps(
                summarize_current_state(current_mapping, rack_part_ids),
                ensure_ascii=False,
                indent=2,
            ),
            "EVIDENCE (the only facts you may use):\n"
            + json.dumps(evidence_block, ensure_ascii=False, indent=2),
            "Return the JSON object now.",
        ]
    )
