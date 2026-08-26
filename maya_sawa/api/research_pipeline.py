"""Research Zone AI 更新管線的人工審核 API。

設計約束：
- API 只讀 RunRepository 業務表，不讀 LangGraph checkpoint。
- approve/reject 只有在 status 為 awaiting_approval 時才接受，重複審核安全拒絕。
- 目前使用 stub service，不接 Celery、OCI、LLM。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..core.auth.keycloak import require_manage_users
from ..research_pipeline.container import (
    PipelineDisabledError,
    PipelineNotStartedError,
    get_pipeline,
)
from ..research_pipeline.repositories import (
    InvalidStatusTransition,
    RunAlreadyExistsError,
    RunConcurrencyError,
    RunNotFoundError,
    RunRepositoryError,
)
from ..research_pipeline.runner import is_awaiting_approval, resume_run, start_run
from ..research_pipeline.state import STATUS_AWAITING_APPROVAL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/research-pipeline", tags=["Research Pipeline"])


class CreateRunRequest(BaseModel):
    dry_run: bool = Field(default=True, description="預設 dry-run，不會產生任何 publish 副作用")


class ApprovalRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)
    expected_revision: Optional[int] = Field(
        default=None, description="帶入 GET 讀到的 revision 以避免同時審核覆蓋"
    )


class RunResponse(BaseModel):
    run_id: str
    status: str
    triggered_by: str
    dry_run: bool
    current_node: Optional[str] = None
    revision: int

    mapping_provenance: Optional[Dict[str, Any]] = None
    evidence: Optional[List[Dict[str, Any]]] = None
    retrieval_evaluation: Optional[List[Dict[str, Any]]] = None
    retrieval_verdict: Optional[str] = None
    correction_attempts: Optional[int] = None
    refined_evidence: Optional[List[Dict[str, Any]]] = None
    change_set: Optional[Dict[str, Any]] = None
    diff_summary: Optional[Dict[str, Any]] = None
    validation_warnings: Optional[List[str]] = None

    approval_decision: Optional[str] = None
    approved_by: Optional[str] = None
    approval_note: Optional[str] = None
    approval_decided_at: Optional[str] = None

    backup_version: Optional[str] = None
    published_version: Optional[str] = None
    failed_node: Optional[str] = None
    error: Optional[str] = None

    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def _to_response(run: Dict[str, Any]) -> RunResponse:
    payload = dict(run)
    for key in ("approval_decided_at", "created_at", "updated_at"):
        value = payload.get(key)
        if value is not None and not isinstance(value, str):
            payload[key] = value.isoformat()
    return RunResponse(**{key: payload.get(key) for key in RunResponse.model_fields})


def _actor(claims: Dict[str, Any]) -> str:
    return (
        claims.get("preferred_username")
        or claims.get("email")
        or claims.get("sub")
        or "unknown"
    )


def _pipeline():
    try:
        return get_pipeline()
    except (PipelineDisabledError, PipelineNotStartedError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_run(repository, run_id: str) -> Dict[str, Any]:
    try:
        return repository.require(run_id)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _decide(run_id: str, decision: str, request: ApprovalRequest, claims: Dict[str, Any]):
    graph, services = _pipeline()
    repository = services.run_repository

    run = _require_run(repository, run_id)
    if run["status"] != STATUS_AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail=f"run 目前狀態為 {run['status']}，只有 {STATUS_AWAITING_APPROVAL} 可以審核",
        )

    existing = run["approval_decision"]
    if existing is not None and existing != decision:
        raise HTTPException(
            status_code=409, detail=f"run 已有審核決定：{existing}，不可再改為 {decision}"
        )

    actor = _actor(claims)
    if existing is None:
        try:
            # 先寫審核 audit：重複審核或 revision 過期會在這裡被擋下，
            # graph 不會被 resume 第二次。
            repository.record_approval(
                run_id,
                decision=decision,
                actor=actor,
                note=request.note,
                expected_revision=request.expected_revision,
            )
        except (InvalidStatusTransition, RunConcurrencyError, RunRepositoryError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    else:
        # 前一次 resume 失敗留下的狀態：保留原決策直接重試，不重新審核。
        logger.info("run %s 沿用既有審核決定 %s 重試 resume", run_id, existing)
        actor = run["approved_by"] or actor

    if not is_awaiting_approval(graph, run_id):
        # 業務表說在等審核，但 checkpoint 沒有對應的 interrupt：
        # checkpoint 遺失或被清除，必須人工重跑，不能當成 500。
        raise HTTPException(
            status_code=409,
            detail=(
                f"run {run_id} 的 checkpoint 不存在或已無等待中的審核，無法 resume；"
                "審核決定已保留，請確認 checkpoint 儲存後重試或重新建立 run"
            ),
        )

    try:
        resume_run(graph, run_id, approved=decision == "approved", approved_by=actor)
    except Exception as exc:  # noqa: BLE001
        logger.exception("resume research pipeline run %s failed", run_id)
        # 決策已寫入 audit，run 維持 awaiting_approval，可以再次呼叫同一個端點重試。
        raise HTTPException(status_code=503, detail=f"resume 失敗，可重試：{exc}") from exc

    return _to_response(_require_run(repository, run_id))


@router.post("/runs", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
def create_run(
    request: CreateRunRequest,
    claims: Dict[str, Any] = Depends(require_manage_users),
):
    graph, services = _pipeline()
    repository = services.run_repository

    run_id = str(uuid.uuid4())
    triggered_by = _actor(claims)
    try:
        repository.create(run_id, triggered_by=triggered_by, dry_run=request.dry_run)
    except RunAlreadyExistsError as exc:  # pragma: no cover - uuid 幾乎不可能碰撞
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    try:
        start_run(graph, run_id, triggered_by=triggered_by, dry_run=request.dry_run)
    except Exception as exc:  # noqa: BLE001
        logger.exception("research pipeline run %s failed", run_id)
        raise HTTPException(status_code=500, detail=f"啟動失敗：{exc}") from exc

    return _to_response(_require_run(repository, run_id))


@router.get("/runs/{run_id}", response_model=RunResponse)
def get_run(run_id: str, _claims: Dict[str, Any] = Depends(require_manage_users)):
    _graph, services = _pipeline()
    return _to_response(_require_run(services.run_repository, run_id))


@router.post("/runs/{run_id}/approve", response_model=RunResponse)
def approve_run(
    run_id: str,
    request: ApprovalRequest,
    claims: Dict[str, Any] = Depends(require_manage_users),
):
    return _decide(run_id, "approved", request, claims)


@router.post("/runs/{run_id}/reject", response_model=RunResponse)
def reject_run(
    run_id: str,
    request: ApprovalRequest,
    claims: Dict[str, Any] = Depends(require_manage_users),
):
    return _decide(run_id, "rejected", request, claims)
