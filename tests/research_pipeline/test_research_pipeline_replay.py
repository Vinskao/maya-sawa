"""Replay 模式端到端測試：snapshot → CRAG → validation → merge → approval → publish。

零外部呼叫（無網路、無 LLM、無 OCI、無資料庫）。
"""

from __future__ import annotations

import copy

import pytest

from maya_sawa.research_pipeline.checkpointing import memory_checkpointer
from maya_sawa.research_pipeline.crag import CORRECT
from maya_sawa.research_pipeline.graph import build_graph
from maya_sawa.research_pipeline.replay import build_replay_services, load_snapshot
from maya_sawa.research_pipeline.runner import is_awaiting_approval, resume_run, start_run
from maya_sawa.research_pipeline.schemas.mapping import parse_mapping
from maya_sawa.research_pipeline.state import STATUS_COMPLETED, STATUS_FAILED


@pytest.fixture
def services():
    return build_replay_services()


@pytest.fixture
def graph(services):
    return build_graph(services, checkpointer=memory_checkpointer())


def test_replay_dry_run_reproduces_diff(graph, services):
    state = start_run(graph, "replay-dry", triggered_by="ci", dry_run=True)

    assert state["status"] == STATUS_COMPLETED
    assert state["retrieval_verdict"] == CORRECT
    assert state["diff_summary"]["totalChanges"] == 2
    assert services.publisher.published == {}


def test_replay_is_deterministic(services):
    """同一份 snapshot 跑兩次必須得到相同的候選 mapping 與 diff。"""
    first = start_run(
        build_graph(services, checkpointer=memory_checkpointer()),
        "replay-a",
        triggered_by="ci",
        dry_run=True,
    )
    second = start_run(
        build_graph(build_replay_services(), checkpointer=memory_checkpointer()),
        "replay-b",
        triggered_by="ci",
        dry_run=True,
    )

    assert first["candidate_mapping"] == second["candidate_mapping"]
    assert first["diff_summary"] == second["diff_summary"]
    assert first["refined_evidence"] == second["refined_evidence"]


def test_replay_through_approval_and_publish(graph, services):
    start_run(graph, "replay-approve", triggered_by="ci", dry_run=False)
    assert is_awaiting_approval(graph, "replay-approve")

    state = resume_run(graph, "replay-approve", approved=True, approved_by="reviewer")

    assert state["status"] == STATUS_COMPLETED
    published = services.publisher.published["replay-approve"]
    # 發布出去的仍然是合法的 production mapping。
    assert parse_mapping(published) is published


def test_replay_with_tampered_snapshot_fails_closed():
    """把 snapshot 的來源換成不可信網域，整條流程必須在生成前失敗。"""
    evidence = copy.deepcopy(load_snapshot("sample_evidence.json"))
    for item in evidence:
        item["sourceId"] = "random-blog"

    services = build_replay_services(evidence=evidence)
    state = start_run(
        build_graph(services, checkpointer=memory_checkpointer()),
        "replay-tampered",
        triggered_by="ci",
        dry_run=True,
    )

    assert state["status"] == STATUS_FAILED
    assert state["failed_node"] == "collect_evidence"
    assert "change_set" not in state
    assert services.publisher.published == {}
