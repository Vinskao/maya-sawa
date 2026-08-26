"""Service protocol 與依賴容器。

Graph node 只負責流程協調；LLM、OCI、資料庫、通知全部藏在這些 protocol 後面，
Phase 3 只提供 stub 實作，真實實作在後續 PR 補上而不需要改動 graph。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # 只為型別註記，避免 import cycle
    from .crag import CorrectiveRetriever, RetrievalEvaluator


@dataclass(frozen=True)
class MappingLoadResult:
    """mapping 內容 + 來源證明。

    `fallback_used=True` 代表讀到的是 bundled fallback 而不是 OCI 上的正式物件。
    以過期 fallback 為基底做 publish 會直接覆蓋掉 OCI 上的真實資料，
    因此正式 publish run 必須 fail closed。
    """

    mapping: dict[str, Any]
    source: str = "unknown"
    object_version: str | None = None
    etag: str | None = None
    fallback_used: bool = False

    def provenance(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "objectVersion": self.object_version,
            "etag": self.etag,
            "fallbackUsed": self.fallback_used,
        }


@runtime_checkable
class MappingRepository(Protocol):
    """讀取目前 production mapping，並回報來源。"""

    def load_current_mapping(self) -> MappingLoadResult: ...


@runtime_checkable
class EvidenceCollector(Protocol):
    """從可信來源收集證據。

    `is_fixture_source` 為 True 代表資料來自本地 fixture；
    在 trusted source registry 的 base_url placeholder 尚未替換前，
    只有 fixture collector 允許執行（fail closed）。
    """

    is_fixture_source: bool

    def collect(self, run_id: str, current_mapping: dict[str, Any]) -> list[dict[str, Any]]: ...


@runtime_checkable
class ChangeSetGenerator(Protocol):
    """由 evidence 產生受限的 change set（唯一使用 LLM 的地方）。"""

    def generate(
        self, evidence: list[dict[str, Any]], current_mapping: dict[str, Any]
    ) -> dict[str, Any]: ...


@runtime_checkable
class Publisher(Protocol):
    """OCI 發布。所有寫入以 run_id 作為 idempotency key。"""

    def backup_current(self, run_id: str, current_mapping: dict[str, Any]) -> str: ...

    def publish(self, run_id: str, mapping: dict[str, Any]) -> str: ...

    def verify(self, run_id: str, version: str, mapping: dict[str, Any]) -> bool: ...


@runtime_checkable
class Notifier(Protocol):
    def notify_failure(self, run_id: str, stage: str, error: str) -> None: ...


@runtime_checkable
class RunRepository(Protocol):
    """業務 run 表：API 查詢用的可查詢狀態，與 LangGraph checkpoint 分工。

    checkpointer 保存 graph execution state（節點續跑）；
    這裡保存 status、操作者、版本、錯誤等業務欄位。
    """

    def create(
        self, run_id: str, *, triggered_by: str, dry_run: bool = True
    ) -> dict[str, Any]: ...

    def record(self, run_id: str, **fields: Any) -> Any: ...

    def get(self, run_id: str) -> dict[str, Any] | None: ...

    def require(self, run_id: str) -> dict[str, Any]: ...

    def record_approval(
        self,
        run_id: str,
        *,
        decision: str,
        actor: str,
        note: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PipelineServices:
    mapping_repository: MappingRepository
    evidence_collector: EvidenceCollector
    change_set_generator: ChangeSetGenerator
    publisher: Publisher
    notifier: Notifier
    run_repository: RunRepository

    # CRAG：未提供時使用 deterministic evaluator（安全底線）與「不補救」。
    retrieval_evaluator: "RetrievalEvaluator | None" = None
    corrective_retriever: "CorrectiveRetriever | None" = None

    def evaluator(self) -> "RetrievalEvaluator":
        from .crag import DeterministicRetrievalEvaluator

        return self.retrieval_evaluator or DeterministicRetrievalEvaluator()
