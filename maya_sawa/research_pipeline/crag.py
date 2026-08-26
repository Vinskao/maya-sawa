"""CRAG（Corrective RAG）檢索品質評估與知識精煉。

依 CRAG 的核心概念：先評估檢索品質，再依 correct / ambiguous / incorrect
採取不同的補救檢索與知識精煉，最後才允許進入生成階段。

在這條管線裡，CRAG 是 generator 前的**硬性 gate**，不是事後補一個分數：
- evidence_gate 判定 insufficient 就 fail closed，禁止產生 change set。
- validate_grounding 要求每個 operation 引用的 evidence 都是 correct。

所有評分邏輯都是 deterministic 純函式。未來可加 LLM evaluator，
但它只能「加強」語意判斷，不能取代這裡的安全規則。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

from .schemas.evidence import EvidenceItem
from .schemas.mapping import rack_part_index
from .trusted_sources import get_source

CORRECT = "correct"
AMBIGUOUS = "ambiguous"
INCORRECT = "incorrect"

# 最多兩輪補救檢索，之後仍不足就 fail closed。
MAX_CORRECTION_ATTEMPTS = 2

CORRECT_THRESHOLD = 0.85
AMBIGUOUS_THRESHOLD = 0.5

# 這幾項不通過就不可能是 correct，無論分數多高。
CRITICAL_CHECKS = ("rack_part_match", "company_match", "primary_source", "complete_fields")

CHECK_WEIGHTS = {
    "rack_part_match": 0.2,
    "company_match": 0.2,
    "product_match": 0.2,
    "supporting_statement": 0.15,
    "primary_source": 0.15,
    "complete_fields": 0.1,
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset({"the", "and", "inc", "ltd", "co", "corp", "company", "electronics"})


def _tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


def _token_coverage(needle: str | None, haystack_tokens: set[str]) -> float:
    """needle 的關鍵 token 有多少比例出現在文字中。"""
    if not needle:
        return 0.0
    wanted = _tokens(needle)
    if not wanted:
        return 0.0
    hit = sum(1 for token in wanted if token in haystack_tokens)
    return hit / len(wanted)


@dataclass(frozen=True)
class EvidenceEvaluation:
    evidence_id: str
    verdict: str
    score: float
    checks: dict[str, bool]
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_correct(self) -> bool:
        return self.verdict == CORRECT

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "verdict": self.verdict,
            "score": round(self.score, 3),
            "checks": dict(self.checks),
            "reasons": list(self.reasons),
        }


@runtime_checkable
class RetrievalEvaluator(Protocol):
    """檢索品質評估器。deterministic 版本是安全底線，LLM 版本只能加強語意判斷。"""

    def evaluate(
        self, evidence: list[EvidenceItem], current_mapping: dict[str, Any]
    ) -> list[EvidenceEvaluation]: ...


@runtime_checkable
class CorrectiveRetriever(Protocol):
    """補救檢索。只能從 evidence_targets 與 trusted-source registry 擴充或改寫查詢。"""

    def retrieve(
        self,
        run_id: str,
        attempt: int,
        current_mapping: dict[str, Any],
        attempted_evidence_ids: set[str],
    ) -> list[dict[str, Any]]: ...


class DeterministicRetrievalEvaluator:
    """以 entity、keyword、來源與欄位覆蓋率評分，不呼叫任何模型。"""

    def __init__(self, *, min_text_chars: int = 40):
        self._min_text_chars = min_text_chars

    def _check_url(self, item: EvidenceItem) -> bool:
        parsed = urlparse(item.source_url)
        source = get_source(item.source_id)
        return bool(
            parsed.scheme == "https"
            and parsed.hostname
            and source
            and source.allows_host(parsed.hostname)
        )

    def evaluate_one(
        self, item: EvidenceItem, rack_part_ids: set[str]
    ) -> EvidenceEvaluation:
        source = get_source(item.source_id)
        text_tokens = set(_tokens(item.evidence_text))
        reasons: list[str] = []

        checks = {
            "rack_part_match": bool(item.rack_part_id and item.rack_part_id in rack_part_ids),
            "company_match": _token_coverage(item.company, text_tokens) >= 0.5,
            "product_match": _token_coverage(item.product, text_tokens) >= 0.5,
            "supporting_statement": len(item.evidence_text.strip()) >= self._min_text_chars
            and bool(item.company)
            and _token_coverage(item.company, text_tokens) > 0,
            "primary_source": bool(source and source.trust_level == "primary"),
            "complete_fields": bool(
                item.fetched_at.strip() and item.evidence_text.strip() and self._check_url(item)
            ),
        }

        if not checks["rack_part_match"]:
            reasons.append(f"rackPartId {item.rack_part_id!r} 不對應目前 mapping 的任何 rack part")
        if not checks["company_match"]:
            reasons.append(f"內文找不到 company {item.company!r} 的關鍵字")
        if not checks["product_match"]:
            reasons.append(f"內文找不到 product {item.product!r} 的關鍵字")
        if not checks["supporting_statement"]:
            reasons.append("缺少足以支持變更的明確敘述")
        if not checks["primary_source"]:
            reasons.append(f"來源 {item.source_id} 不是 allowlist 的 primary source")
        if not checks["complete_fields"]:
            reasons.append("時間、URL 或內容欄位不完整")

        score = sum(CHECK_WEIGHTS[name] for name, passed in checks.items() if passed)
        critical_ok = all(checks[name] for name in CRITICAL_CHECKS)

        if critical_ok and score >= CORRECT_THRESHOLD:
            verdict = CORRECT
        elif score >= AMBIGUOUS_THRESHOLD:
            verdict = AMBIGUOUS
        else:
            verdict = INCORRECT

        return EvidenceEvaluation(
            evidence_id=item.evidence_id,
            verdict=verdict,
            score=score,
            checks=checks,
            reasons=tuple(reasons),
        )

    def evaluate(
        self, evidence: list[EvidenceItem], current_mapping: dict[str, Any]
    ) -> list[EvidenceEvaluation]:
        rack_part_ids = set(rack_part_index(current_mapping))
        return [self.evaluate_one(item, rack_part_ids) for item in evidence]


def aggregate_verdict(evaluations: list[EvidenceEvaluation]) -> str:
    """整批檢索的判定：有 correct 就 correct，否則看是否還有 ambiguous 可補救。"""
    if any(evaluation.verdict == CORRECT for evaluation in evaluations):
        return CORRECT
    if any(evaluation.verdict == AMBIGUOUS for evaluation in evaluations):
        return AMBIGUOUS
    return INCORRECT


def refine_evidence(
    evidence: list[EvidenceItem],
    evaluations: list[EvidenceEvaluation],
    *,
    max_chars: int = 600,
) -> list[dict[str, Any]]:
    """知識精煉：只保留 correct evidence 中能支持 company/product/rack-part 關係的句子。

    ambiguous evidence 會留在 state 供人工查看，但不會進入 refined_evidence，
    因此無法單獨支持任何 operation。
    """
    verdicts = {evaluation.evidence_id: evaluation for evaluation in evaluations}
    seen_sentences: set[str] = set()
    refined: list[dict[str, Any]] = []

    for item in evidence:
        evaluation = verdicts.get(item.evidence_id)
        if evaluation is None or not evaluation.is_correct:
            continue

        wanted = set(_tokens(item.company or "")) | set(_tokens(item.product or ""))
        kept: list[str] = []
        for sentence in _SENTENCE_SPLIT.split(item.evidence_text):
            cleaned = sentence.strip()
            if not cleaned:
                continue
            fingerprint = " ".join(_tokens(cleaned))
            if not fingerprint or fingerprint in seen_sentences:
                continue  # 去重：跨 evidence 的重複句子只留一次
            if wanted and not (wanted & set(_tokens(cleaned))):
                continue  # 過濾：與 company/product 無關的句子
            seen_sentences.add(fingerprint)
            kept.append(cleaned)

        if not kept:
            continue

        payload = item.to_dict()
        payload["evidenceText"] = " ".join(kept)[:max_chars]
        payload["verdict"] = evaluation.verdict
        payload["score"] = round(evaluation.score, 3)
        refined.append(payload)

    return refined


def grounding_errors(
    change_set: Any, refined_evidence: list[dict[str, Any]], evaluations: list[dict[str, Any]]
) -> list[str]:
    """每個 operation 都必須引用存在、且 CRAG 判定為 correct 的 evidence。"""
    correct_ids = {
        evaluation["evidenceId"]
        for evaluation in evaluations
        if evaluation.get("verdict") == CORRECT
    }
    refined_by_id = {item["evidenceId"]: item for item in refined_evidence}

    errors: list[str] = []
    for operation in change_set.operations:
        label = f"{operation.op} {operation.target()}"
        for evidence_id in operation.evidence_ids:
            if evidence_id not in refined_by_id:
                errors.append(f"{label}: 引用的 evidence {evidence_id} 不在精煉後的證據中")
                continue
            if evidence_id not in correct_ids:
                errors.append(
                    f"{label}: 引用的 evidence {evidence_id} 的 CRAG 判定不是 correct"
                )
                continue
            evidence_rack_part = refined_by_id[evidence_id].get("rackPartId")
            if evidence_rack_part != operation.rack_part_id:
                errors.append(
                    f"{label}: evidence {evidence_id} 對應的 rackPart 是 "
                    f"{evidence_rack_part}，與 operation 不符"
                )
    return errors


class TargetRegistryRetriever:
    """補救檢索：只從既有 evidence targets 擴充，永遠不接受 LLM 提供的 URL。

    collector_factory 接受一批 target 並回傳 collector，
    讓補救檢索沿用同一套 URL allowlist / timeout / size 限制。
    """

    def __init__(self, collector_factory: Any, targets: list[Any]):
        self._collector_factory = collector_factory
        self._targets = list(targets)

    def retrieve(
        self,
        run_id: str,
        attempt: int,
        current_mapping: dict[str, Any],
        attempted_evidence_ids: set[str],
    ) -> list[dict[str, Any]]:
        remaining = [
            target
            for target in self._targets
            if target.evidence_id not in attempted_evidence_ids
        ]
        if not remaining:
            return []

        # 每一輪只擴充一批，讓 correction 次數可預測。
        batch_size = max(1, len(self._targets) // MAX_CORRECTION_ATTEMPTS)
        return self._collector_factory(remaining[:batch_size]).collect(run_id, current_mapping)
