"""Run repository 契約測試。

同一組測試同時跑記憶體版與 PostgreSQL 版，確保兩者行為一致。
Postgres 版需要 RESEARCH_PIPELINE_TEST_DSN，未設定時只跑記憶體版。
"""

from __future__ import annotations

import os
import uuid

import pytest

from maya_sawa.research_pipeline.repositories import (
    InMemoryRunRepository,
    InvalidStatusTransition,
    PostgresRunRepository,
    RunAlreadyExistsError,
    RunConcurrencyError,
    RunNotFoundError,
    RunRepositoryError,
)
from maya_sawa.research_pipeline.state import (
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
)

DSN = os.getenv("RESEARCH_PIPELINE_TEST_DSN")


@pytest.fixture(params=["memory", "postgres"])
def repo(request):
    if request.param == "memory":
        return InMemoryRunRepository()
    if not DSN:
        pytest.skip("需要 RESEARCH_PIPELINE_TEST_DSN")
    repository = PostgresRunRepository(DSN)
    repository.create_table()
    return repository


@pytest.fixture
def run_id():
    return f"run-{uuid.uuid4()}"


def test_create_and_get(repo, run_id):
    created = repo.create(run_id, triggered_by="tester", dry_run=True)
    assert created["status"] == STATUS_RUNNING
    assert created["revision"] == 0

    fetched = repo.get(run_id)
    assert fetched["run_id"] == run_id
    assert fetched["triggered_by"] == "tester"
    assert fetched["dry_run"] is True


def test_run_id_is_unique(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    with pytest.raises(RunAlreadyExistsError):
        repo.create(run_id, triggered_by="tester")


def test_get_missing_run(repo, run_id):
    assert repo.get(run_id) is None
    with pytest.raises(RunNotFoundError):
        repo.require(run_id)


def test_update_bumps_revision_and_stores_json(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    updated = repo.update(run_id, current_node="collect_evidence", diff_summary={"totalChanges": 2})

    assert updated["revision"] == 1
    assert updated["current_node"] == "collect_evidence"
    assert updated["diff_summary"] == {"totalChanges": 2}


def test_unknown_field_is_rejected(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    with pytest.raises(RunRepositoryError):
        repo.update(run_id, nonexistent_column="x")


def test_optimistic_concurrency(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    stale = repo.get(run_id)["revision"]
    repo.update(run_id, current_node="collect_evidence")

    with pytest.raises(RunConcurrencyError):
        repo.update(run_id, expected_revision=stale, current_node="generate_change_set")


def test_terminal_status_cannot_transition(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    repo.update(run_id, status=STATUS_COMPLETED)
    with pytest.raises(InvalidStatusTransition):
        repo.update(run_id, status=STATUS_FAILED)


def test_same_status_write_is_allowed(repo, run_id):
    """resume 會重跑節點，重複寫入同一狀態必須是 no-op 而不是錯誤。"""
    repo.create(run_id, triggered_by="tester")
    repo.update(run_id, status=STATUS_AWAITING_APPROVAL)
    assert repo.update(run_id, status=STATUS_AWAITING_APPROVAL)["status"] == STATUS_AWAITING_APPROVAL


def test_record_upserts_for_graph_nodes(repo, run_id):
    run = repo.record(run_id, status=STATUS_RUNNING, triggered_by="graph", current_node="load")
    assert run["triggered_by"] == "graph"
    assert repo.record(run_id, current_node="collect_evidence")["current_node"] == "collect_evidence"


# --- approval audit -------------------------------------------------------


def test_approval_requires_awaiting_approval(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    with pytest.raises(InvalidStatusTransition):
        repo.record_approval(run_id, decision="approved", actor="reviewer")


def test_approval_records_audit_fields(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    repo.update(run_id, status=STATUS_AWAITING_APPROVAL)
    approved = repo.record_approval(
        run_id, decision="approved", actor="reviewer", note="looks good"
    )

    assert approved["approval_decision"] == "approved"
    assert approved["approved_by"] == "reviewer"
    assert approved["approval_note"] == "looks good"
    assert approved["approval_decided_at"] is not None


def test_duplicate_approval_is_rejected(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    repo.update(run_id, status=STATUS_AWAITING_APPROVAL)
    repo.record_approval(run_id, decision="approved", actor="reviewer")

    with pytest.raises(RunRepositoryError):
        repo.record_approval(run_id, decision="approved", actor="another-reviewer")
    with pytest.raises(RunRepositoryError):
        repo.record_approval(run_id, decision="rejected", actor="another-reviewer")


def test_approval_with_stale_revision_is_rejected(repo, run_id):
    repo.create(run_id, triggered_by="tester")
    repo.update(run_id, status=STATUS_AWAITING_APPROVAL)
    stale = 0

    with pytest.raises(RunConcurrencyError):
        repo.record_approval(
            run_id, decision="approved", actor="reviewer", expected_revision=stale
        )
