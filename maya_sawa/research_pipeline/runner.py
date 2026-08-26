"""Graph 執行入口。

Celery task（Phase 6）只會呼叫這裡的函式，不直接碰 LangGraph API。
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from .graph import run_config
from .state import ResearchPipelineState, initial_state


def start_run(
    graph: Any,
    run_id: str,
    *,
    triggered_by: str,
    dry_run: bool = True,
) -> ResearchPipelineState:
    """啟動一個 run。非 dry-run 會停在 await_approval 的 interrupt。"""
    return graph.invoke(
        initial_state(run_id, triggered_by=triggered_by, dry_run=dry_run),
        run_config(run_id),
    )


def resume_run(
    graph: Any,
    run_id: str,
    *,
    approved: bool,
    approved_by: str,
) -> ResearchPipelineState:
    """以人工決策 resume；同一 run_id 對應同一條 checkpoint 線。"""
    return graph.invoke(
        Command(resume={"approved": approved, "approvedBy": approved_by}),
        run_config(run_id),
    )


def pending_interrupt(graph: Any, run_id: str) -> dict[str, Any] | None:
    """取得目前等待人工處理的 interrupt payload；沒有則回傳 None。"""
    snapshot = graph.get_state(run_config(run_id))
    for task in snapshot.tasks:
        for item in getattr(task, "interrupts", ()) or ():
            return item.value
    return None


def is_awaiting_approval(graph: Any, run_id: str) -> bool:
    return pending_interrupt(graph, run_id) is not None
