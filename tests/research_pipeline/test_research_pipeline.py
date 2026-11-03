"""Research pipeline deterministic core 測試（純函式，不需要外部服務）。

mapping 形狀對齊正式 production 物件（rackParts）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from maya_sawa.research_pipeline.diff import build_diff_summary
from maya_sawa.research_pipeline.errors import SchemaError
from maya_sawa.research_pipeline.merge import MergeError, apply_change_set
from maya_sawa.research_pipeline.schemas import parse_change_set, parse_evidence_list
from maya_sawa.research_pipeline.schemas.mapping import parse_mapping
from maya_sawa.research_pipeline.validation import (
    validate_candidate_mapping,
    validate_change_set,
    validate_evidence,
)

FIXTURES = Path("maya_sawa/research_pipeline/fixtures")
EVIDENCE_ID = "delta-official:https://www.deltaww.com/en-US/products/dc-dc-power-module"


def make_evidence(evidence_id=EVIDENCE_ID, source_id="delta-official"):
    return {
        "evidenceId": evidence_id,
        "sourceId": source_id,
        "sourceUrl": "https://www.deltaww.com/en-US/products/dc-dc-power-module",
        "fetchedAt": "2026-06-25T00:00:00Z",
        "rackPartId": "dc-pdu",
        "company": "Delta Electronics",
        "product": "800V→48V DC-DC power module",
        "evidenceText": "Delta launched an ORv3 800V to 48V DC-DC power module.",
        "confidence": "high",
    }


def make_change_set(operations):
    return {"generatedAt": "2026-06-25T00:00:00Z", "operations": operations}


def add_entry_op(company="Delta Electronics", product="New DC-DC module", note=None):
    operation = {
        "op": "add_product_entry",
        "rackPartId": "dc-pdu",
        "company": company,
        "product": product,
        "evidence": [EVIDENCE_ID],
        "confidence": "high",
    }
    if note is not None:
        operation["data"] = {"note": note}
    return operation


@pytest.fixture
def current_mapping():
    """正式 production mapping 的副本。"""
    return json.loads((FIXTURES / "sample_mapping.json").read_text(encoding="utf-8"))


# --- schema ---------------------------------------------------------------


def test_production_mapping_passes_schema(current_mapping):
    assert parse_mapping(current_mapping) is current_mapping


def test_parse_mapping_rejects_missing_language(current_mapping):
    del current_mapping["rackParts"][0]["name"]["zh"]
    with pytest.raises(SchemaError):
        parse_mapping(current_mapping)


def test_parse_mapping_rejects_entry_without_company(current_mapping):
    current_mapping["rackParts"][0]["products"][0].pop("company")
    with pytest.raises(SchemaError):
        parse_mapping(current_mapping)


def test_parse_evidence_rejects_missing_fields():
    with pytest.raises(SchemaError):
        parse_evidence_list([{"sourceId": "delta-official"}])


def test_parse_change_set_rejects_delete_operation():
    with pytest.raises(SchemaError) as exc:
        parse_change_set(make_change_set([{"op": "delete_product_entry", "rackPartId": "dc-pdu"}]))
    assert any("拒絕" in message for message in exc.value.errors)


def test_parse_change_set_rejects_adding_rack_part():
    """rackParts[].id 綁定前端 hover region，MVP 不得新增。"""
    with pytest.raises(SchemaError):
        parse_change_set(make_change_set([{"op": "add_rack_part", "rackPartId": "new-part"}]))


def test_parse_change_set_rejects_malformed_payload():
    with pytest.raises(SchemaError):
        parse_change_set("not a json object")
    with pytest.raises(SchemaError):
        parse_change_set(make_change_set([{**add_entry_op(), "data": {"note": 123}}]))
    with pytest.raises(SchemaError):
        parse_change_set(make_change_set([{**add_entry_op(), "evidence": []}]))


def test_parse_change_set_rejects_unknown_fields():
    with pytest.raises(SchemaError):
        parse_change_set(make_change_set([{**add_entry_op(), "priority": "high"}]))


def test_parse_change_set_rejects_unknown_language():
    operation = {
        "op": "update_rack_part",
        "rackPartId": "dc-pdu",
        "data": {"summary": {"jp": "..."}},
        "evidence": [EVIDENCE_ID],
    }
    with pytest.raises(SchemaError):
        parse_change_set(make_change_set([operation]))


# --- merge ----------------------------------------------------------------


def test_add_product_entry_appends(current_mapping):
    change_set = parse_change_set(make_change_set([add_entry_op(note="from official page")]))
    candidate = apply_change_set(current_mapping, change_set)

    entries = candidate["rackParts"][0]["products"]
    assert entries[-1] == {
        "company": "Delta Electronics",
        "product": "New DC-DC module",
        "note": "from official page",
    }
    # 既有 entry 的顯示順序不變。
    assert entries[:3] == current_mapping["rackParts"][0]["products"]


def test_update_rack_part_merges_each_language(current_mapping):
    change_set = parse_change_set(
        make_change_set(
            [
                {
                    "op": "update_rack_part",
                    "rackPartId": "dc-pdu",
                    "data": {"summary": {"en": "Updated english summary."}},
                    "evidence": [EVIDENCE_ID],
                }
            ]
        )
    )
    candidate = apply_change_set(current_mapping, change_set)
    summary = candidate["rackParts"][0]["summary"]

    assert summary["en"] == "Updated english summary."
    # 沒有提供的語言必須保留原值。
    assert summary["zh"] == current_mapping["rackParts"][0]["summary"]["zh"]


def test_empty_value_does_not_overwrite_existing(current_mapping):
    change_set = parse_change_set(
        make_change_set(
            [
                {
                    "op": "update_rack_part",
                    "rackPartId": "dc-pdu",
                    "data": {"summary": {"en": "   ", "zh": None}},
                    "evidence": [EVIDENCE_ID],
                }
            ]
        )
    )
    candidate = apply_change_set(current_mapping, change_set)
    assert candidate["rackParts"][0]["summary"] == current_mapping["rackParts"][0]["summary"]


def test_add_does_not_overwrite_existing_entry(current_mapping):
    existing = current_mapping["rackParts"][0]["products"][0]
    change_set = parse_change_set(
        make_change_set([add_entry_op(company=existing["company"], product=existing["product"])])
    )
    with pytest.raises(MergeError):
        apply_change_set(current_mapping, change_set)


def test_update_requires_existing_entry(current_mapping):
    change_set = parse_change_set(
        make_change_set(
            [
                {
                    "op": "update_product_entry",
                    "rackPartId": "dc-pdu",
                    "company": "Delta Electronics",
                    "product": "does-not-exist",
                    "data": {"note": "x"},
                    "evidence": [EVIDENCE_ID],
                }
            ]
        )
    )
    with pytest.raises(MergeError):
        apply_change_set(current_mapping, change_set)


def test_unknown_rack_part_is_rejected(current_mapping):
    change_set = parse_change_set(
        make_change_set([{**add_entry_op(), "rackPartId": "no-such-part"}])
    )
    with pytest.raises(MergeError):
        apply_change_set(current_mapping, change_set)


def test_rename_conflicting_with_existing_entry_is_rejected(current_mapping):
    products = current_mapping["rackParts"][0]["products"]
    first, second = products[0], products[1]
    change_set = parse_change_set(
        make_change_set(
            [
                {
                    "op": "update_product_entry",
                    "rackPartId": "dc-pdu",
                    "company": first["company"],
                    "product": first["product"],
                    "data": {"product": second["product"]},
                    "evidence": [EVIDENCE_ID],
                }
            ]
        )
    )
    # 只有同 company 才會衝突；不同 company 時允許改名。
    if first["company"] == second["company"]:
        with pytest.raises(MergeError):
            apply_change_set(current_mapping, change_set)
    else:
        assert apply_change_set(current_mapping, change_set)


def test_merge_is_deterministic_and_rejects_replay(current_mapping):
    change_set = parse_change_set(make_change_set([add_entry_op()]))
    original = copy.deepcopy(current_mapping)

    first = apply_change_set(current_mapping, change_set)
    second = apply_change_set(current_mapping, change_set)
    assert first == second
    assert current_mapping == original, "merge 不得修改輸入"

    # change set 本身不是 idempotent：對已存在的 entry 再做一次 add 理應失敗。
    # 「同一 run 不重複寫入」由 run_id + checkpoint 保證，不是靠 merge 容忍重放。
    with pytest.raises(MergeError):
        apply_change_set(first, change_set)


# --- validation -----------------------------------------------------------


def test_untrusted_source_is_rejected():
    evidence = parse_evidence_list([make_evidence(source_id="random-blog")])
    assert not validate_evidence(evidence).is_valid


def test_change_set_referencing_unknown_evidence_is_rejected():
    evidence = parse_evidence_list([make_evidence(evidence_id="other")])
    change_set = parse_change_set(make_change_set([add_entry_op()]))
    assert not validate_change_set(change_set, evidence).is_valid


def test_valid_change_set_passes_validation():
    evidence = parse_evidence_list([make_evidence()])
    change_set = parse_change_set(make_change_set([add_entry_op()]))
    assert validate_evidence(evidence).is_valid
    assert validate_change_set(change_set, evidence).is_valid


def test_oversized_diff_is_rejected(current_mapping):
    candidate = copy.deepcopy(current_mapping)
    for index in range(40):
        candidate["rackParts"][0]["products"].append(
            {"company": f"Vendor {index}", "product": "x", "note": ""}
        )
    result = validate_candidate_mapping(candidate, current_mapping)
    assert not result.is_valid
    assert any("安全門檻" in message for message in result.errors)


def test_removal_is_rejected(current_mapping):
    candidate = copy.deepcopy(current_mapping)
    candidate["rackParts"][0]["products"].pop()
    assert not validate_candidate_mapping(candidate, current_mapping).is_valid


def test_adding_rack_part_is_rejected(current_mapping):
    candidate = copy.deepcopy(current_mapping)
    candidate["rackParts"].append(
        {
            "id": "new-part",
            "name": {"en": "New", "zh": "新"},
            "summary": {"en": "New", "zh": "新"},
            "products": [],
        }
    )
    result = validate_candidate_mapping(candidate, current_mapping)
    assert not result.is_valid
    assert any("新增 rack part" in message for message in result.errors)


def test_candidate_missing_display_field_is_rejected(current_mapping):
    candidate = copy.deepcopy(current_mapping)
    candidate["rackParts"][0]["products"][0].pop("product")
    assert not validate_candidate_mapping(candidate, current_mapping).is_valid


def test_diff_summary_counts(current_mapping):
    change_set = parse_change_set(make_change_set([add_entry_op()]))
    candidate = apply_change_set(current_mapping, change_set)
    summary = build_diff_summary(current_mapping, candidate)

    assert summary["addedProductEntries"] == ["dc-pdu/Delta Electronics/New DC-DC module"]
    assert summary["totalChanges"] == 1
