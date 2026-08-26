"""Pipeline 依賴組裝（application-scoped）。

Graph、checkpointer 與 services 都是 application-scoped：由 FastAPI lifespan
建立一次、關閉一次，不在每個 request 開 context manager。

目前 service 全部是 stub：不接 LLM、OCI、Telegram、Celery。
真實實作補上時只需要換掉這裡的組裝，graph 與 API 都不用改。
"""

from __future__ import annotations

import json
import logging
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Callable

from .checkpointing import ENABLED_ENV, open_checkpointer, pipeline_enabled
from .graph import build_graph
from .repositories import InMemoryRunRepository, PostgresRunRepository
from .services import PipelineServices
from .stubs import (
    FixtureEvidenceCollector,
    StubChangeSetGenerator,
    StubMappingRepository,
    StubNotifier,
    StubPublisher,
)

logger = logging.getLogger(__name__)

FIXTURES = Path(__file__).parent / "fixtures"


class PipelineNotStartedError(RuntimeError):
    """在 lifespan startup 之前就嘗試取用 pipeline。"""


class PipelineDisabledError(RuntimeError):
    """功能未啟用（RESEARCH_PIPELINE_ENABLED != true）。"""


def load_fixture(name: str) -> Any:
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


def build_run_repository():
    """有 DSN 就用 PostgreSQL 業務表，否則退回記憶體版（本地開發用）。"""
    dsn = os.getenv("RESEARCH_PIPELINE_DB_DSN")
    if not dsn:
        return InMemoryRunRepository()
    repository = PostgresRunRepository(dsn)
    if os.getenv("RESEARCH_PIPELINE_DB_AUTO_MIGRATE") == "true":
        repository.create_table()
    return repository


def build_stub_services(run_repository=None) -> PipelineServices:
    return PipelineServices(
        mapping_repository=StubMappingRepository(load_fixture("sample_mapping.json")),
        evidence_collector=FixtureEvidenceCollector(load_fixture("sample_evidence.json")),
        change_set_generator=StubChangeSetGenerator(load_fixture("sample_change_set.json")),
        publisher=StubPublisher(),
        notifier=StubNotifier(),
        run_repository=run_repository or build_run_repository(),
    )


class PipelineContainer:
    """持有 application-scoped 的 services、checkpointer 與 compiled graph。"""

    def __init__(
        self,
        *,
        services_factory: Callable[[], PipelineServices] = build_stub_services,
        checkpointer_factory: Callable[[ExitStack], Any] | None = None,
        enabled_check: Callable[[], bool] | None = None,
    ):
        self._services_factory = services_factory
        self._checkpointer_factory = checkpointer_factory or (
            lambda stack: open_checkpointer(stack)
        )
        self._enabled_check = enabled_check or pipeline_enabled
        self._enabled = True
        self._stack: ExitStack | None = None
        self._graph: Any = None
        self._services: PipelineServices | None = None

    @property
    def started(self) -> bool:
        return self._graph is not None

    def startup(self) -> None:
        """建立 checkpointer 與 graph。

        - 未啟用：完全不初始化，既有 API 照常運作，pipeline API 回 503。
        - 已啟用但設定不完整：直接 raise，讓應用啟動失敗（fail fast）。
        """
        if self.started:
            return

        self._enabled = self._enabled_check()
        if not self._enabled:
            logger.info(
                "research pipeline 未啟用（%s != true），略過初始化；相關 API 將回 503",
                ENABLED_ENV,
            )
            return

        stack = ExitStack()
        try:
            checkpointer = self._checkpointer_factory(stack)
            services = self._services_factory()
            graph = build_graph(services, checkpointer=checkpointer)
        except Exception:
            stack.close()
            raise

        self._stack = stack
        self._services = services
        self._graph = graph
        logger.info("research pipeline container started (%s)", type(checkpointer).__name__)

    def shutdown(self) -> None:
        self._enabled = True
        if self._stack is not None:
            self._stack.close()
        self._stack = None
        self._graph = None
        self._services = None
        logger.info("research pipeline container stopped")

    def pipeline(self) -> tuple[Any, PipelineServices]:
        if not self._enabled:
            raise PipelineDisabledError(
                f"research pipeline 未啟用；請設定 {ENABLED_ENV}=true 後重新啟動"
            )
        if not self.started:
            raise PipelineNotStartedError("research pipeline 尚未啟動")
        return self._graph, self._services  # type: ignore[return-value]


_container = PipelineContainer()


def get_container() -> PipelineContainer:
    return _container


def get_pipeline() -> tuple[Any, PipelineServices]:
    return _container.pipeline()
