"""Mapping 來源證明與 fallback fail-closed 測試。

正式 publish run 不得以 bundled fallback 為基底：那會用過期資料覆蓋 OCI 上的正式物件。
"""

from __future__ import annotations

import copy

import pytest

from maya_sawa.research_pipeline.checkpointing import memory_checkpointer
from maya_sawa.research_pipeline.graph import build_graph
from maya_sawa.research_pipeline.runner import is_awaiting_approval, start_run
from maya_sawa.research_pipeline.services import MappingLoadResult
from maya_sawa.research_pipeline.state import STATUS_COMPLETED, STATUS_FAILED
from maya_sawa.research_pipeline.stubs import StubMappingRepository

from tests.test_research_pipeline_graph import CURRENT_MAPPING, make_services


def make_repository(*, fallback: bool):
    return StubMappingRepository(
        CURRENT_MAPPING,
        result=MappingLoadResult(
            mapping=copy.deepcopy(CURRENT_MAPPING),
            source="classpath-fallback" if fallback else "oci",
            object_version=None if fallback else "v42",
            etag=None if fallback else "etag-42",
            fallback_used=fallback,
        ),
    )


def run(services, run_id, *, dry_run):
    graph = build_graph(services, checkpointer=memory_checkpointer())
    state = start_run(graph, run_id, triggered_by="tester", dry_run=dry_run)
    return graph, state


def with_repository(repository):
    services = make_services()
    return services.__class__(**{**services.__dict__, "mapping_repository": repository})


def test_provenance_is_reported():
    services = with_repository(make_repository(fallback=False))
    _graph, state = run(services, "run-prov", dry_run=True)

    assert state["mapping_provenance"] == {
        "source": "oci",
        "objectVersion": "v42",
        "etag": "etag-42",
        "fallbackUsed": False,
    }
    assert services.run_repository.get("run-prov")["mapping_provenance"]["source"] == "oci"


def test_publish_run_fails_closed_on_fallback():
    services = with_repository(make_repository(fallback=True))
    graph, state = run(services, "run-fallback", dry_run=False)

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "load_current_mapping"
    assert "fallback" in state["error"]
    # 連人工審核都不該出現：這條 run 從一開始就不該存在。
    assert not is_awaiting_approval(graph, "run-fallback")
    assert services.publisher.published == {}
    assert services.publisher.backups == {}


def test_dry_run_on_fallback_is_allowed_but_warned():
    services = with_repository(make_repository(fallback=True))
    _graph, state = run(services, "run-fallback-dry", dry_run=True)

    assert state["status"] == STATUS_COMPLETED
    assert any("fallback" in warning for warning in state["validation_warnings"])
    assert state["mapping_provenance"]["fallbackUsed"] is True
    assert services.publisher.published == {}


def test_publish_run_proceeds_when_source_is_oci():
    services = with_repository(make_repository(fallback=False))
    graph, _state = run(services, "run-oci", dry_run=False)

    assert is_awaiting_approval(graph, "run-oci")
    assert services.run_repository.get("run-oci")["status"] == "awaiting_approval"
