"""Evidence item schema。

Evidence 是唯一允許進入 LLM 的事實來源，也是 change set 能被接受的前提。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..errors import SchemaError

CONFIDENCE_LEVELS = ("low", "medium", "high")

_REQUIRED_FIELDS = ("sourceId", "sourceUrl", "fetchedAt", "evidenceText")
_ALLOWED_FIELDS = _REQUIRED_FIELDS + (
    "evidenceId",
    "rackPartId",
    "company",
    "product",
    "confidence",
)


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    source_id: str
    source_url: str
    fetched_at: str
    evidence_text: str
    rack_part_id: str | None = None
    company: str | None = None
    product: str | None = None
    confidence: str = "medium"
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "sourceId": self.source_id,
            "sourceUrl": self.source_url,
            "fetchedAt": self.fetched_at,
            "evidenceText": self.evidence_text,
            "rackPartId": self.rack_part_id,
            "company": self.company,
            "product": self.product,
            "confidence": self.confidence,
        }


def _parse_evidence(payload: Any, index: int, errors: list[str]) -> EvidenceItem | None:
    label = f"evidence[{index}]"
    if not isinstance(payload, dict):
        errors.append(f"{label}: 必須是物件")
        return None

    unknown = sorted(set(payload) - set(_ALLOWED_FIELDS))
    if unknown:
        errors.append(f"{label}: 未知欄位 {unknown}")

    for name in _REQUIRED_FIELDS:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}: 缺少或空白的 {name}")

    confidence = payload.get("confidence", "medium")
    if confidence not in CONFIDENCE_LEVELS:
        errors.append(f"{label}: confidence 必須是 {list(CONFIDENCE_LEVELS)}")

    for name in ("rackPartId", "company", "product"):
        value = payload.get(name)
        if value is not None and not isinstance(value, str):
            errors.append(f"{label}: {name} 必須是字串或 null")

    if errors:
        return None

    return EvidenceItem(
        evidence_id=str(payload.get("evidenceId") or f"{payload['sourceId']}#{index}"),
        source_id=payload["sourceId"],
        source_url=payload["sourceUrl"],
        fetched_at=payload["fetchedAt"],
        evidence_text=payload["evidenceText"],
        rack_part_id=payload.get("rackPartId"),
        company=payload.get("company"),
        product=payload.get("product"),
        confidence=confidence,
        raw=dict(payload),
    )


def parse_evidence_list(payload: Any) -> list[EvidenceItem]:
    """解析 evidence 陣列，任何一筆錯誤都直接 raise SchemaError。"""
    if not isinstance(payload, list):
        raise SchemaError(["evidence: 必須是陣列"])

    errors: list[str] = []
    items: list[EvidenceItem] = []
    for index, entry in enumerate(payload):
        local: list[str] = []
        item = _parse_evidence(entry, index, local)
        errors.extend(local)
        if item is not None:
            items.append(item)

    seen: set[str] = set()
    for item in items:
        if item.evidence_id in seen:
            errors.append(f"evidence: 重複的 evidenceId {item.evidence_id}")
        seen.add(item.evidence_id)

    if errors:
        raise SchemaError(errors)
    return items
