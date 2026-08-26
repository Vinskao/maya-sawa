"""Replay 模式。

從 evidence snapshot 與固定的 fake LLM 輸出重跑整條管線：

    evidence fixture → fake change set → CRAG → validation → merge → approval

完全不呼叫外部 API，CI 可以無條件執行。真實 collector 與 LLM 接上後，
把新的 snapshot 存成 fixture 就能重現當時的判斷。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .container import FIXTURES
from .crag import DeterministicRetrievalEvaluator
from .services import PipelineServices
from .stubs import (
    FixtureEvidenceCollector,
    StubChangeSetGenerator,
    StubMappingRepository,
    StubNotifier,
    StubPublisher,
)
from .repositories import InMemoryRunRepository


def load_snapshot(name: str, base: Path = FIXTURES) -> Any:
    with open(base / name, encoding="utf-8") as handle:
        return json.load(handle)


def build_replay_services(
    *,
    mapping: Any = None,
    evidence: Any = None,
    change_set: Any = None,
    run_repository: Any = None,
    base: Path = FIXTURES,
) -> PipelineServices:
    """以 snapshot 組裝一組完全離線的 services。"""
    return PipelineServices(
        mapping_repository=StubMappingRepository(
            mapping if mapping is not None else load_snapshot("sample_mapping.json", base)
        ),
        evidence_collector=FixtureEvidenceCollector(
            evidence if evidence is not None else load_snapshot("sample_evidence.json", base)
        ),
        change_set_generator=StubChangeSetGenerator(
            change_set if change_set is not None else load_snapshot("sample_change_set.json", base)
        ),
        publisher=StubPublisher(),
        notifier=StubNotifier(),
        run_repository=run_repository or InMemoryRunRepository(),
        # replay 一律使用 deterministic evaluator，結果才可重現。
        retrieval_evaluator=DeterministicRetrievalEvaluator(),
        corrective_retriever=None,
    )
