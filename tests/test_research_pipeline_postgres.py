"""Postgres checkpointer + 業務表的跨 process 整合測試。

需要一個可寫的測試用 PostgreSQL：
    RESEARCH_PIPELINE_TEST_DSN=postgresql://user:pass@host:5432/db poetry run pytest \
        tests/test_research_pipeline_postgres.py
未設定時整個模組 skip，CI 預設不會跑。
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import research_pipeline as api
from maya_sawa.core.auth.keycloak import require_manage_users
from maya_sawa.research_pipeline.checkpointing import open_postgres_checkpointer
from maya_sawa.research_pipeline.container import PipelineContainer
from maya_sawa.research_pipeline.repositories import PostgresRunRepository
from maya_sawa.research_pipeline.runner import is_awaiting_approval, resume_run, start_run
from maya_sawa.research_pipeline.state import STATUS_AWAITING_APPROVAL, STATUS_COMPLETED

from tests.test_research_pipeline_graph import make_services

DSN = os.getenv("RESEARCH_PIPELINE_TEST_DSN")

pytestmark = pytest.mark.skipif(not DSN, reason="需要 RESEARCH_PIPELINE_TEST_DSN")


def make_repository() -> PostgresRunRepository:
    repository = PostgresRunRepository(DSN)
    repository.create_table()
    return repository


def make_container(run_repository) -> PipelineContainer:
    """模擬一個 application process：自己的 checkpointer 連線與 compiled graph。"""
    services = make_services(run_repository=run_repository)
    return PipelineContainer(
        services_factory=lambda: services,
        checkpointer_factory=lambda stack: open_postgres_checkpointer(stack, DSN),
        enabled_check=lambda: True,
    )


@pytest.fixture
def run_id():
    return f"run-{uuid.uuid4()}"


def test_awaiting_run_resumes_in_a_new_process(run_id):
    """Process A 停在審核，Process B 用全新 container 接手 approve 並完成 publish。"""
    # --- Process A ---
    repo_a = make_repository()
    container_a = make_container(repo_a)
    container_a.startup()
    graph_a, services_a = container_a.pipeline()

    repo_a.create(run_id, triggered_by="tester", dry_run=False)
    start_run(graph_a, run_id, triggered_by="tester", dry_run=False)

    assert repo_a.require(run_id)["status"] == STATUS_AWAITING_APPROVAL
    assert services_a.change_set_generator.calls == 1
    assert services_a.publisher.published == {}

    container_a.shutdown()  # process A 結束，連線釋放

    # --- Process B：全新 container、全新 services，只共用同一個資料庫 ---
    repo_b = make_repository()
    container_b = make_container(repo_b)
    container_b.startup()
    try:
        graph_b, services_b = container_b.pipeline()
        assert is_awaiting_approval(graph_b, run_id)

        repo_b.record_approval(run_id, decision="approved", actor="reviewer")
        state = resume_run(graph_b, run_id, approved=True, approved_by="reviewer")

        assert state["status"] == STATUS_COMPLETED
        assert state["published_version"] == f"published-{run_id}"
        # 已完成的節點沒有重跑：process B 的 generator 一次都沒被呼叫。
        assert services_b.change_set_generator.calls == 0

        run = repo_b.require(run_id)
        assert run["status"] == STATUS_COMPLETED
        assert run["approval_decision"] == "approved"
        assert run["approved_by"] == "reviewer"
        assert run["published_version"] == f"published-{run_id}"
    finally:
        container_b.shutdown()


def test_approval_audit_is_written_once(run_id):
    """跨 process 之後仍只接受一次審核決定。"""
    repo = make_repository()
    container = make_container(repo)
    container.startup()
    try:
        graph, _services = container.pipeline()
        repo.create(run_id, triggered_by="tester", dry_run=False)
        start_run(graph, run_id, triggered_by="tester", dry_run=False)
        repo.record_approval(run_id, decision="approved", actor="reviewer")

        from maya_sawa.research_pipeline.repositories import RunRepositoryError

        with pytest.raises(RunRepositoryError):
            repo.record_approval(run_id, decision="approved", actor="another")
        assert repo.require(run_id)["approved_by"] == "reviewer"
    finally:
        container.shutdown()


def test_missing_checkpoint_returns_conflict(run_id, monkeypatch):
    """業務表有 run 但 checkpoint 不存在時，API 回 409 而不是 500。"""
    repo = make_repository()
    container = make_container(repo)
    container.startup()
    try:
        # 只建立業務 run，完全沒有跑過 graph，因此沒有對應的 checkpoint。
        repo.create(run_id, triggered_by="tester", dry_run=False)
        repo.update(run_id, status=STATUS_AWAITING_APPROVAL)

        monkeypatch.setattr(api, "get_pipeline", container.pipeline)
        app = FastAPI()
        app.include_router(api.router)
        app.dependency_overrides[require_manage_users] = lambda: {"preferred_username": "reviewer"}
        client = TestClient(app)

        response = client.post(f"/research-pipeline/runs/{run_id}/approve", json={})
        assert response.status_code == 409
        assert "checkpoint" in response.json()["detail"]

        # 審核決定已保留，可在 checkpoint 恢復後重試。
        assert repo.require(run_id)["approval_decision"] == "approved"
    finally:
        container.shutdown()


def test_concurrent_setup_is_safe():
    """多個 replica 同時啟動時，checkpointer setup() 必須是安全的。"""
    import threading
    from contextlib import ExitStack

    errors: list[Exception] = []

    def start_replica():
        try:
            with ExitStack() as stack:
                open_postgres_checkpointer(stack, DSN)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=start_replica) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, errors
