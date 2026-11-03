"""PipelineContainer 設定行為測試（不需要資料庫）。"""

from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from maya_sawa.research_pipeline.checkpointing import (
    CHECKPOINT_DSN_ENV,
    ENABLED_ENV,
    LOCAL_MODE_ENV,
    RUN_DB_DSN_ENV,
    CheckpointConfigError,
)
from maya_sawa.research_pipeline.container import (
    PipelineContainer,
    PipelineDisabledError,
    PipelineNotStartedError,
)


@pytest.fixture
def clean_env(monkeypatch):
    for name in (CHECKPOINT_DSN_ENV, RUN_DB_DSN_ENV, LOCAL_MODE_ENV, ENABLED_ENV):
        monkeypatch.delenv(name, raising=False)
    # 這些測試針對「已啟用」時的設定嚴格性。
    monkeypatch.setenv(ENABLED_ENV, "true")


@pytest.fixture
def disabled_env(monkeypatch):
    for name in (CHECKPOINT_DSN_ENV, RUN_DB_DSN_ENV, LOCAL_MODE_ENV, ENABLED_ENV):
        monkeypatch.delenv(name, raising=False)


def test_disabled_pipeline_starts_without_dsn(disabled_env):
    """功能未啟用時缺 DSN 不應阻斷既有後端啟動。"""
    container = PipelineContainer()
    container.startup()

    assert not container.started
    with pytest.raises(PipelineDisabledError):
        container.pipeline()


def test_disabled_by_default(disabled_env, monkeypatch):
    monkeypatch.setenv(ENABLED_ENV, "false")
    container = PipelineContainer()
    container.startup()
    with pytest.raises(PipelineDisabledError):
        container.pipeline()


def test_startup_fails_fast_without_dsn(clean_env):
    """正式模式缺少 DSN 必須啟動失敗，不可默默退回 memory。"""
    container = PipelineContainer()
    with pytest.raises(CheckpointConfigError) as exc:
        container.startup()

    assert CHECKPOINT_DSN_ENV in str(exc.value)
    assert not container.started


def test_local_mode_allows_memory_checkpointer(clean_env, monkeypatch):
    monkeypatch.setenv(LOCAL_MODE_ENV, "true")
    container = PipelineContainer()
    container.startup()
    try:
        graph, services = container.pipeline()
        assert isinstance(graph.checkpointer, InMemorySaver)
        assert services.run_repository is not None
    finally:
        container.shutdown()


def test_pipeline_before_startup_raises(clean_env):
    with pytest.raises(PipelineNotStartedError):
        PipelineContainer().pipeline()


def test_shutdown_releases_resources(clean_env, monkeypatch):
    monkeypatch.setenv(LOCAL_MODE_ENV, "true")
    container = PipelineContainer()
    container.startup()
    container.shutdown()

    assert not container.started
    with pytest.raises(PipelineNotStartedError):
        container.pipeline()


def test_failed_startup_does_not_leak_stack(clean_env):
    def exploding_factory(stack):
        raise RuntimeError("boom")

    container = PipelineContainer(checkpointer_factory=exploding_factory)
    with pytest.raises(RuntimeError):
        container.startup()
    assert not container.started
