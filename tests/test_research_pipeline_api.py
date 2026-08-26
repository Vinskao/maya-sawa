"""Research pipeline workflow API 測試（stub services + in-memory repository）。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import research_pipeline as api
from maya_sawa.core.auth.keycloak import require_manage_users
from maya_sawa.research_pipeline.checkpointing import memory_checkpointer
from maya_sawa.research_pipeline.container import build_stub_services
from maya_sawa.research_pipeline.graph import build_graph
from maya_sawa.research_pipeline.repositories import InMemoryRunRepository


@pytest.fixture
def pipeline(monkeypatch):
    services = build_stub_services(run_repository=InMemoryRunRepository())
    graph = build_graph(services, checkpointer=memory_checkpointer())
    monkeypatch.setattr(api, "get_pipeline", lambda: (graph, services))
    return graph, services


@pytest.fixture
def client(pipeline):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_manage_users] = lambda: {"preferred_username": "reviewer"}
    return TestClient(app)


def create_run(client, dry_run: bool):
    response = client.post("/research-pipeline/runs", json={"dry_run": dry_run})
    assert response.status_code == 201, response.text
    return response.json()


# --- 建立 run -------------------------------------------------------------


def test_dry_run_completes_without_publish(client, pipeline):
    _graph, services = pipeline
    run = create_run(client, dry_run=True)

    assert run["status"] == "completed"
    assert run["triggered_by"] == "reviewer"
    assert run["diff_summary"]["totalChanges"] == 2
    assert services.publisher.published == {}


def test_non_dry_run_waits_for_approval(client, pipeline):
    _graph, services = pipeline
    run = create_run(client, dry_run=False)

    assert run["status"] == "awaiting_approval"
    assert run["change_set"]["operations"][0]["op"] == "add_product_entry"
    assert run["evidence"][0]["rackPartId"] == "dc-pdu"
    assert services.publisher.published == {}


def test_get_run_returns_business_row(client):
    created = create_run(client, dry_run=False)
    response = client.get(f"/research-pipeline/runs/{created['run_id']}")

    assert response.status_code == 200
    assert response.json()["run_id"] == created["run_id"]


def test_get_unknown_run_is_404(client):
    assert client.get("/research-pipeline/runs/does-not-exist").status_code == 404


# --- approve / reject -----------------------------------------------------


def test_approve_publishes(client, pipeline):
    _graph, services = pipeline
    run_id = create_run(client, dry_run=False)["run_id"]

    response = client.post(f"/research-pipeline/runs/{run_id}/approve", json={"note": "ok"})
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "completed"
    assert body["approval_decision"] == "approved"
    assert body["approved_by"] == "reviewer"
    assert body["approval_note"] == "ok"
    assert body["published_version"] == f"published-{run_id}"
    assert list(services.publisher.published) == [run_id]


def test_reject_skips_publish(client, pipeline):
    _graph, services = pipeline
    run_id = create_run(client, dry_run=False)["run_id"]

    body = client.post(f"/research-pipeline/runs/{run_id}/reject", json={}).json()
    assert body["status"] == "rejected"
    assert body["approval_decision"] == "rejected"
    assert services.publisher.published == {}


def test_duplicate_approve_is_rejected_and_does_not_resume_twice(client, pipeline):
    _graph, services = pipeline
    run_id = create_run(client, dry_run=False)["run_id"]
    client.post(f"/research-pipeline/runs/{run_id}/approve", json={})

    second = client.post(f"/research-pipeline/runs/{run_id}/approve", json={})
    assert second.status_code == 409
    # 第二次沒有 resume graph，也沒有第二次 publish。
    assert list(services.publisher.published) == [run_id]


def test_approve_after_rejection_is_rejected(client):
    run_id = create_run(client, dry_run=False)["run_id"]
    client.post(f"/research-pipeline/runs/{run_id}/reject", json={})

    assert client.post(f"/research-pipeline/runs/{run_id}/approve", json={}).status_code == 409


def test_approve_on_dry_run_is_rejected(client, pipeline):
    _graph, services = pipeline
    run_id = create_run(client, dry_run=True)["run_id"]

    response = client.post(f"/research-pipeline/runs/{run_id}/approve", json={})
    assert response.status_code == 409
    assert "awaiting_approval" in response.json()["detail"]
    assert services.publisher.published == {}


def test_stale_revision_is_rejected(client):
    run = create_run(client, dry_run=False)
    response = client.post(
        f"/research-pipeline/runs/{run['run_id']}/approve",
        json={"expected_revision": run["revision"] - 1},
    )
    assert response.status_code == 409


def test_approve_unknown_run_is_404(client):
    assert client.post("/research-pipeline/runs/nope/approve", json={}).status_code == 404


# --- resume 失敗後的重試 ---------------------------------------------------


def test_failed_resume_keeps_decision_and_allows_retry(client, pipeline, monkeypatch):
    """resume 失敗回 503，決策保留，再打同一個端點即可重試。"""
    _graph, services = pipeline
    run_id = create_run(client, dry_run=False)["run_id"]

    calls = {"count": 0}
    real_resume = api.resume_run

    def flaky_resume(graph, rid, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("OCI 暫時無法連線")
        return real_resume(graph, rid, **kwargs)

    monkeypatch.setattr(api, "resume_run", flaky_resume)

    first = client.post(f"/research-pipeline/runs/{run_id}/approve", json={"note": "ok"})
    assert first.status_code == 503
    assert services.publisher.published == {}

    run = client.get(f"/research-pipeline/runs/{run_id}").json()
    assert run["status"] == "awaiting_approval"
    assert run["approval_decision"] == "approved"
    assert run["approved_by"] == "reviewer"

    second = client.post(f"/research-pipeline/runs/{run_id}/approve", json={})
    assert second.status_code == 200
    assert second.json()["status"] == "completed"
    assert list(services.publisher.published) == [run_id]


def test_cannot_change_decision_after_failed_resume(client, pipeline, monkeypatch):
    _graph, services = pipeline
    run_id = create_run(client, dry_run=False)["run_id"]

    def failing_resume(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(api, "resume_run", failing_resume)
    assert client.post(f"/research-pipeline/runs/{run_id}/approve", json={}).status_code == 503

    # 已核准的 run 不允許改成 reject，只能重試 resume。
    response = client.post(f"/research-pipeline/runs/{run_id}/reject", json={})
    assert response.status_code == 409
    assert "approved" in response.json()["detail"]
    assert services.publisher.published == {}


def test_disabled_pipeline_returns_503(monkeypatch):
    """功能未啟用時 pipeline API 回 503，其餘 API 不受影響。"""
    from maya_sawa.research_pipeline.container import PipelineContainer

    container = PipelineContainer(enabled_check=lambda: False)
    container.startup()
    monkeypatch.setattr(api, "get_pipeline", container.pipeline)

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[require_manage_users] = lambda: {"preferred_username": "reviewer"}
    client = TestClient(app)

    response = client.post("/research-pipeline/runs", json={"dry_run": True})
    assert response.status_code == 503
    assert "RESEARCH_PIPELINE_ENABLED" in response.json()["detail"]
