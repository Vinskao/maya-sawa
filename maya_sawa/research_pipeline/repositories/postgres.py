"""PostgreSQL 版 run repository。

只保存業務狀態；graph execution state 由 LangGraph checkpointer 負責。
連線以 connection_factory 注入，Phase 6 可換成既有的 ConnectionPoolManager。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Callable

from ..state import STATUS_AWAITING_APPROVAL, STATUS_RUNNING
from .run_status import (
    JSON_FIELDS,
    InvalidStatusTransition,
    RunAlreadyExistsError,
    RunConcurrencyError,
    RunNotFoundError,
    RunRepositoryError,
    assert_transition,
    assert_updatable_fields,
)

TABLE = "maya_sawa_research_pipeline_runs"

_COLUMNS = (
    "run_id",
    "status",
    "triggered_by",
    "dry_run",
    "current_node",
    "mapping_provenance",
    "evidence",
    "retrieval_evaluation",
    "retrieval_verdict",
    "correction_attempts",
    "refined_evidence",
    "change_set",
    "diff_summary",
    "validation_warnings",
    "approval_decision",
    "approved_by",
    "approval_note",
    "approval_decided_at",
    "backup_version",
    "published_version",
    "failed_node",
    "error",
    "revision",
    "created_at",
    "updated_at",
)

_SELECT = f"SELECT {', '.join(_COLUMNS)} FROM {TABLE}"


def _default_connection_factory(dsn: str) -> Callable[[], Any]:
    import psycopg2

    def factory():
        return psycopg2.connect(dsn)

    return factory


def _encode(field: str, value: Any) -> Any:
    if field in JSON_FIELDS and value is not None and not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


class PostgresRunRepository:
    def __init__(
        self,
        dsn: str | None = None,
        *,
        connection_factory: Callable[[], Any] | None = None,
    ):
        if connection_factory is None:
            dsn = dsn or os.getenv("RESEARCH_PIPELINE_DB_DSN")
            if not dsn:
                raise RunRepositoryError("缺少 RESEARCH_PIPELINE_DB_DSN 或 connection_factory")
            connection_factory = _default_connection_factory(dsn)
        self._connection_factory = connection_factory

    # --- 基礎設施 -----------------------------------------------------
    def _execute(self, sql: str, params: tuple[Any, ...] = (), *, fetch: bool = False):
        conn = self._connection_factory()
        try:
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(sql, params)
                    if not fetch:
                        return cursor.rowcount
                    rows = cursor.fetchall()
                    return [dict(zip(_COLUMNS, row)) for row in rows]
        finally:
            conn.close()

    def create_table(self) -> None:
        """建立資料表（測試與初次部署用；正式環境走 sql/ 的 migration）。"""
        ddl_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "sql",
            "create_research_pipeline_runs_table.sql",
        )
        with open(os.path.abspath(ddl_path), encoding="utf-8") as handle:
            self._execute(handle.read())

    # --- 讀取 ---------------------------------------------------------
    def get(self, run_id: str) -> dict[str, Any] | None:
        rows = self._execute(f"{_SELECT} WHERE run_id = %s", (run_id,), fetch=True)
        return rows[0] if rows else None

    def require(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        if run is None:
            raise RunNotFoundError(f"run 不存在：{run_id}")
        return run

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._execute(
            f"{_SELECT} ORDER BY created_at DESC LIMIT %s", (limit,), fetch=True
        )

    # --- 寫入 ---------------------------------------------------------
    def create(
        self,
        run_id: str,
        *,
        triggered_by: str,
        dry_run: bool = True,
        status: str = STATUS_RUNNING,
    ) -> dict[str, Any]:
        # run_id 的 UNIQUE constraint 是最終防線；ON CONFLICT DO NOTHING 讓
        # 重複建立回傳明確錯誤而不是 IntegrityError。
        inserted = self._execute(
            f"INSERT INTO {TABLE} (run_id, status, triggered_by, dry_run) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (run_id) DO NOTHING",
            (run_id, status, triggered_by, dry_run),
        )
        if not inserted:
            raise RunAlreadyExistsError(f"run_id 已存在：{run_id}")
        return self.require(run_id)

    def update(
        self, run_id: str, *, expected_revision: int | None = None, **fields: Any
    ) -> dict[str, Any]:
        assert_updatable_fields(fields)
        current = self.require(run_id)

        if expected_revision is not None and current["revision"] != expected_revision:
            raise RunConcurrencyError(
                f"run {run_id} 已被更新（expected {expected_revision}, "
                f"actual {current['revision']}）"
            )

        new_status = fields.get("status")
        if new_status is not None:
            assert_transition(current["status"], new_status)

        assignments = {key: value for key, value in fields.items() if value is not None}
        if not assignments:
            return current

        columns = sorted(assignments)
        set_clause = ", ".join(f"{column} = %s" for column in columns)
        params = tuple(_encode(column, assignments[column]) for column in columns)

        # 以讀到的 revision 做 CAS，避免兩個 writer 同時更新同一個 run。
        updated = self._execute(
            f"UPDATE {TABLE} SET {set_clause}, revision = revision + 1, updated_at = now() "
            "WHERE run_id = %s AND revision = %s",
            params + (run_id, current["revision"]),
        )
        if not updated:
            raise RunConcurrencyError(f"run {run_id} 在更新期間被其他 writer 修改")
        return self.require(run_id)

    def record(self, run_id: str, **fields: Any) -> dict[str, Any]:
        if self.get(run_id) is None:
            self.create(
                run_id,
                triggered_by=fields.get("triggered_by") or "unknown",
                dry_run=bool(fields.get("dry_run", True)),
            )
        return self.update(run_id, **fields)

    def record_approval(
        self,
        run_id: str,
        *,
        decision: str,
        actor: str,
        note: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        run = self.require(run_id)
        if run["status"] != STATUS_AWAITING_APPROVAL:
            raise InvalidStatusTransition(
                f"run {run_id} 目前狀態為 {run['status']}，只有 awaiting_approval 可以審核"
            )
        if run["approval_decision"] is not None:
            raise RunRepositoryError(f"run {run_id} 已有審核決定：{run['approval_decision']}")

        return self.update(
            run_id,
            expected_revision=expected_revision if expected_revision is not None else run["revision"],
            approval_decision=decision,
            approved_by=actor,
            approval_note=note,
            approval_decided_at=datetime.now(timezone.utc),
        )
