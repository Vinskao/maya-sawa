"""證據收集、change set 產生、merge 與驗證節點。

節點只做流程協調：真正的判斷邏輯都在 deterministic 的 merge/validation 模組。
"""

from __future__ import annotations

from typing import Any, Callable

from ..errors import SchemaError
from ..merge import apply_change_set
from ..schemas import parse_change_set, parse_evidence_list
from ..schemas.mapping import parse_mapping
from ..services import PipelineServices
from ..state import STATUS_RUNNING, ResearchPipelineState, failure
from ..trusted_sources import unresolved_placeholder_sources
from ..validation import validate_candidate_mapping, validate_change_set, validate_evidence
from ..diff import build_diff_summary

Node = Callable[[ResearchPipelineState], ResearchPipelineState]


def _record(services: PipelineServices, state: ResearchPipelineState, **fields: Any) -> None:
    services.run_repository.record(state["run_id"], **fields)


def make_load_current_mapping(services: PipelineServices) -> Node:
    def load_current_mapping(state: ResearchPipelineState) -> ResearchPipelineState:
        _record(
            services,
            state,
            status=STATUS_RUNNING,
            triggered_by=state.get("triggered_by"),
            dry_run=state.get("dry_run", True),
            current_node="load_current_mapping",
        )
        result = services.mapping_repository.load_current_mapping()
        provenance = result.provenance()
        _record(services, state, mapping_provenance=provenance)

        try:
            parse_mapping(result.mapping)
        except SchemaError as exc:
            return failure("load_current_mapping", exc.errors)

        if result.fallback_used and not state.get("dry_run", True):
            # 以過期的 bundled fallback 為基底 publish 會直接覆蓋 OCI 上的真實資料。
            return failure(
                "load_current_mapping",
                [
                    f"目前 mapping 來自 fallback（source={result.source}），"
                    "不是 OCI 正式物件，禁止 publish run 以此為基底"
                ],
            )

        warnings = list(state.get("validation_warnings", []))
        if result.fallback_used:
            warnings.append(
                f"dry-run 使用 fallback mapping（source={result.source}），結果僅供參考"
            )

        return {
            "current_mapping": result.mapping,
            "mapping_provenance": provenance,
            "validation_warnings": warnings,
        }

    return load_current_mapping


def make_collect_evidence(services: PipelineServices) -> Node:
    def collect_evidence(state: ResearchPipelineState) -> ResearchPipelineState:
        _record(services, state, current_node="collect_evidence")

        collector = services.evidence_collector
        pending = unresolved_placeholder_sources()
        if not getattr(collector, "is_fixture_source", False) and pending:
            # fail closed：registry 的 base_url 還是 placeholder，不接受真實來源。
            return failure(
                "collect_evidence",
                [f"trusted source registry 尚未完成設定：{list(pending)}，僅允許 fixture evidence"],
            )

        raw_evidence = collector.collect(state["run_id"], state.get("current_mapping", {}))
        try:
            evidence = parse_evidence_list(raw_evidence)
        except SchemaError as exc:
            return failure("collect_evidence", exc.errors)

        result = validate_evidence(evidence)
        if not result.is_valid:
            return failure("collect_evidence", list(result.errors))

        return {"evidence": [item.to_dict() for item in evidence]}

    return collect_evidence


def make_generate_change_set(services: PipelineServices) -> Node:
    def generate_change_set(state: ResearchPipelineState) -> ResearchPipelineState:
        _record(services, state, current_node="generate_change_set")
        try:
            # 只把精煉後、CRAG 判定 correct 的證據交給 generator。
            raw = services.change_set_generator.generate(
                state.get("refined_evidence", []), state.get("current_mapping", {})
            )
            parse_change_set(raw)
        except SchemaError as exc:
            # GenerationError 也是 SchemaError：模型持續產出無效輸出時，
            # 這裡讓 run 乾淨地失敗，而不是讓例外炸穿整個 graph。
            return failure("generate_change_set", exc.errors)
        except Exception as exc:  # noqa: BLE001 - 外部模型呼叫失敗不得中斷 graph
            return failure("generate_change_set", [f"change set 生成失敗：{exc}"])
        return {"change_set": raw}

    return generate_change_set


def make_validate_change_set(services: PipelineServices) -> Node:
    def validate_change_set_node(state: ResearchPipelineState) -> ResearchPipelineState:
        _record(services, state, current_node="validate_change_set")
        try:
            change_set = parse_change_set(state.get("change_set", {}))
            evidence = parse_evidence_list(state.get("evidence", []))
        except SchemaError as exc:
            return failure("validate_change_set", exc.errors)

        result = validate_change_set(change_set, evidence)
        if not result.is_valid:
            return failure("validate_change_set", list(result.errors))
        # 累加而非覆蓋：早期節點（例如 fallback mapping 警告）的內容必須保留到審核畫面。
        return {
            "validation_warnings": [*state.get("validation_warnings", []), *result.warnings]
        }

    return validate_change_set_node


def make_merge_change_set(services: PipelineServices) -> Node:
    def merge_change_set(state: ResearchPipelineState) -> ResearchPipelineState:
        _record(services, state, current_node="merge_change_set")
        try:
            change_set = parse_change_set(state.get("change_set", {}))
            candidate = apply_change_set(state.get("current_mapping", {}), change_set)
        except SchemaError as exc:
            return failure("merge_change_set", exc.errors)
        return {"candidate_mapping": candidate}

    return merge_change_set


def make_validate_candidate(services: PipelineServices) -> Node:
    def validate_candidate(state: ResearchPipelineState) -> ResearchPipelineState:
        _record(services, state, current_node="validate_candidate")
        current = state.get("current_mapping", {})
        candidate = state.get("candidate_mapping", {})
        result = validate_candidate_mapping(candidate, current)
        if not result.is_valid:
            return failure("validate_candidate", list(result.errors))
        return {
            "diff_summary": build_diff_summary(current, candidate),
            "validation_warnings": [
                *state.get("validation_warnings", []),
                *result.warnings,
            ],
        }

    return validate_candidate
