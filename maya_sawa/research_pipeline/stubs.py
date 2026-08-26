"""Stub service 實作。

僅供 dry-run 驗證流程與單元測試使用，不做任何網路、LLM 或 OCI I/O。
真實實作在後續 PR 取代，graph 不需改動。
"""

from __future__ import annotations

import copy
from typing import Any

from .repositories.memory import InMemoryRunRepository
from .services import MappingLoadResult

__all__ = [
    "StubMappingRepository",
    "FixtureEvidenceCollector",
    "StubChangeSetGenerator",
    "StubPublisher",
    "StubNotifier",
    "InMemoryRunRepository",
]


class StubMappingRepository:
    def __init__(self, mapping: dict[str, Any], result: MappingLoadResult | None = None):
        self._mapping = mapping
        self._result = result

    def load_current_mapping(self) -> MappingLoadResult:
        if self._result is not None:
            return self._result
        return MappingLoadResult(
            mapping=copy.deepcopy(self._mapping),
            source="stub",
            object_version="stub-version",
            etag="stub-etag",
            fallback_used=False,
        )


class FixtureEvidenceCollector:
    """從固定 fixture 回傳 evidence（trusted registry placeholder 期間唯一允許的來源）。"""

    is_fixture_source = True

    def __init__(self, evidence: list[dict[str, Any]]):
        self._evidence = evidence

    def collect(self, run_id: str, current_mapping: dict[str, Any]) -> list[dict[str, Any]]:
        return copy.deepcopy(self._evidence)


class StubChangeSetGenerator:
    """回傳預先準備好的 change set，取代 LLM。"""

    def __init__(self, change_set: dict[str, Any]):
        self._change_set = change_set

    def generate(
        self, evidence: list[dict[str, Any]], current_mapping: dict[str, Any]
    ) -> dict[str, Any]:
        return copy.deepcopy(self._change_set)


class StubPublisher:
    """以 run_id 作為 idempotency key 的記憶體版 publisher。"""

    def __init__(self, *, verify_result: bool = True):
        self.verify_result = verify_result
        self.backups: dict[str, dict[str, Any]] = {}
        self.published: dict[str, dict[str, Any]] = {}

    def backup_current(self, run_id: str, current_mapping: dict[str, Any]) -> str:
        self.backups[run_id] = copy.deepcopy(current_mapping)
        return f"backup-{run_id}"

    def publish(self, run_id: str, mapping: dict[str, Any]) -> str:
        # idempotent：同一 run_id 重跑不會產生第二個版本。
        self.published[run_id] = copy.deepcopy(mapping)
        return f"published-{run_id}"

    def verify(self, run_id: str, version: str, mapping: dict[str, Any]) -> bool:
        return self.verify_result and self.published.get(run_id) == mapping


class StubNotifier:
    def __init__(self) -> None:
        self.failures: list[tuple[str, str, str]] = []

    def notify_failure(self, run_id: str, stage: str, error: str) -> None:
        self.failures.append((run_id, stage, error))
