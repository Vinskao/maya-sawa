"""Research pipeline LangGraph workflow 測試（in-memory checkpointer，無外部服務）。"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from maya_sawa.research_pipeline.checkpointing import memory_checkpointer
from maya_sawa.research_pipeline.graph import build_graph
from maya_sawa.research_pipeline.runner import (
    is_awaiting_approval,
    pending_interrupt,
    resume_run,
    start_run,
)
from maya_sawa.research_pipeline.services import PipelineServices
from maya_sawa.research_pipeline.state import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PUBLISH_VERIFICATION_FAILED,
    STATUS_REJECTED,
)
from maya_sawa.research_pipeline.stubs import (
    FixtureEvidenceCollector,
    InMemoryRunRepository,
    StubChangeSetGenerator,
    StubMappingRepository,
    StubNotifier,
    StubPublisher,
)

CURRENT_MAPPING = json.loads(
    (Path("maya_sawa/research_pipeline/fixtures") / "sample_mapping.json").read_text(encoding="utf-8")
)

EVIDENCE = json.loads(
    (Path("maya_sawa/research_pipeline/fixtures") / "sample_evidence.json").read_text(encoding="utf-8")
)

CHANGE_SET = json.loads(
    (Path("maya_sawa/research_pipeline/fixtures") / "sample_change_set.json").read_text(encoding="utf-8")
)

EVIDENCE_ID = EVIDENCE[0]["evidenceId"]
ADDED_ENTRY = "dc-pdu/Delta Electronics/800V→48V DC-DC power module (ORv3)"


class CountingGenerator(StubChangeSetGenerator):
    def __init__(self, change_set):
        super().__init__(change_set)
        self.calls = 0

    def generate(self, evidence, current_mapping):
        self.calls += 1
        return super().generate(evidence, current_mapping)


class NetworkEvidenceCollector(FixtureEvidenceCollector):
    """模擬真實來源 collector（非 fixture），placeholder 未替換前必須被擋下。"""

    is_fixture_source = False


def make_services(
    *,
    evidence=None,
    change_set=None,
    collector=None,
    verify_result=True,
    run_repository=None,
) -> PipelineServices:
    return PipelineServices(
        mapping_repository=StubMappingRepository(copy.deepcopy(CURRENT_MAPPING)),
        evidence_collector=collector or FixtureEvidenceCollector(evidence or EVIDENCE),
        change_set_generator=CountingGenerator(change_set or CHANGE_SET),
        publisher=StubPublisher(verify_result=verify_result),
        notifier=StubNotifier(),
        run_repository=run_repository or InMemoryRunRepository(),
    )


@pytest.fixture
def services():
    return make_services()


@pytest.fixture
def graph(services):
    return build_graph(services, checkpointer=memory_checkpointer())


# --- dry-run ---------------------------------------------------------------


def test_dry_run_completes_after_prepare_review(graph, services):
    state = start_run(graph, "run-dry", triggered_by="tester", dry_run=True)

    assert state["status"] == STATUS_COMPLETED
    assert state["diff_summary"]["addedProductEntries"] == [ADDED_ENTRY]
    # dry-run 不得有任何 publish 副作用
    assert services.publisher.published == {}
    assert services.publisher.backups == {}
    assert not is_awaiting_approval(graph, "run-dry")


# --- 人工審核 --------------------------------------------------------------


def test_non_dry_run_interrupts_before_publish(graph, services):
    start_run(graph, "run-1", triggered_by="tester", dry_run=False)

    payload = pending_interrupt(graph, "run-1")
    assert payload is not None
    assert payload["runId"] == "run-1"
    assert payload["diffSummary"]["totalChanges"] == 2
    # 尚未 approve，絕不可 publish
    assert services.publisher.published == {}
    assert services.run_repository.get("run-1")["status"] == "awaiting_approval"


def test_approval_publishes_and_verifies(graph, services):
    start_run(graph, "run-2", triggered_by="tester", dry_run=False)
    state = resume_run(graph, "run-2", approved=True, approved_by="reviewer")

    assert state["status"] == STATUS_COMPLETED
    assert state["backup_version"] == "backup-run-2"
    assert state["published_version"] == "published-run-2"
    published = services.publisher.published["run-2"]["rackParts"][0]["products"]
    assert any(entry["product"].endswith("(ORv3)") for entry in published)

    run = services.run_repository.get("run-2")
    assert run["status"] == STATUS_COMPLETED
    assert run["approved_by"] == "reviewer"


def test_rejection_skips_publish(graph, services):
    start_run(graph, "run-3", triggered_by="tester", dry_run=False)
    state = resume_run(graph, "run-3", approved=False, approved_by="reviewer")

    assert state["status"] == STATUS_REJECTED
    assert services.publisher.published == {}
    assert services.run_repository.get("run-3")["status"] == STATUS_REJECTED


def test_completed_nodes_are_not_rerun_on_resume(graph, services):
    start_run(graph, "run-4", triggered_by="tester", dry_run=False)
    assert services.change_set_generator.calls == 1

    resume_run(graph, "run-4", approved=True, approved_by="reviewer")
    # idempotency 由 run_id + checkpoint 保證：resume 不會重跑已完成的節點。
    assert services.change_set_generator.calls == 1


# --- resume / 重啟 ---------------------------------------------------------


def test_resume_after_worker_restart_with_same_run_id(services):
    """模擬 worker 重啟：graph 物件重建，靠同一份 checkpoint 續跑。"""
    saver = memory_checkpointer()
    first_graph = build_graph(services, checkpointer=saver)
    start_run(first_graph, "run-restart", triggered_by="tester", dry_run=False)
    del first_graph

    restarted_graph = build_graph(services, checkpointer=saver)
    assert is_awaiting_approval(restarted_graph, "run-restart")

    state = resume_run(restarted_graph, "run-restart", approved=True, approved_by="reviewer")
    assert state["status"] == STATUS_COMPLETED
    assert services.change_set_generator.calls == 1


# --- 失敗路徑 --------------------------------------------------------------


def test_untrusted_evidence_fails_before_publish():
    services = make_services(
        evidence=[{**EVIDENCE[0], "sourceId": "random-blog"}]
    )
    graph = build_graph(services, checkpointer=memory_checkpointer())
    state = start_run(graph, "run-untrusted", triggered_by="tester", dry_run=False)

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "collect_evidence"
    assert services.publisher.published == {}
    assert services.notifier.failures[0][1] == "collect_evidence"


def test_non_fixture_collector_fails_closed_while_registry_has_placeholders(monkeypatch):
    monkeypatch.setattr(
        "maya_sawa.research_pipeline.nodes.research.unresolved_placeholder_sources",
        lambda: ("some-source",),
    )
    services = make_services(collector=NetworkEvidenceCollector(EVIDENCE))
    graph = build_graph(services, checkpointer=memory_checkpointer())
    state = start_run(graph, "run-failclosed", triggered_by="tester", dry_run=True)

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "collect_evidence"
    assert "registry" in state["error"]


def test_non_fixture_collector_is_allowed_once_registry_is_resolved():
    """registry 完成設定後，真實 collector 才能進入流程。"""
    services = make_services(collector=NetworkEvidenceCollector(EVIDENCE))
    graph = build_graph(services, checkpointer=memory_checkpointer())
    state = start_run(graph, "run-resolved", triggered_by="tester", dry_run=True)

    assert state["status"] == STATUS_COMPLETED


def test_malformed_change_set_fails_at_generation():
    services = make_services(change_set={"generatedAt": "2026-06-25T00:00:00Z", "operations": [
        {"op": "delete_product_entry", "rackPartId": "dc-pdu"}
    ]})
    graph = build_graph(services, checkpointer=memory_checkpointer())
    state = start_run(graph, "run-delete", triggered_by="tester", dry_run=True)

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "generate_change_set"
    assert services.publisher.published == {}


def test_publish_verification_failure_is_not_auto_rolled_back():
    services = make_services(verify_result=False)
    graph = build_graph(services, checkpointer=memory_checkpointer())
    start_run(graph, "run-verify", triggered_by="tester", dry_run=False)
    state = resume_run(graph, "run-verify", approved=True, approved_by="reviewer")

    assert state["status"] == STATUS_PUBLISH_VERIFICATION_FAILED
    # 已備份、已寫入，但不自動 rollback，交人工判斷
    assert services.publisher.backups["run-verify"] == CURRENT_MAPPING
    assert services.notifier.failures[0][1] == "verify_publication"
