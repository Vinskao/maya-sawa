"""Checkpointer 建構與設定解析。

分工：
- checkpointer（這裡）保存 graph execution state，負責 resume 與人工 interrupt。
- 業務 run 表（RunRepository）保存可查詢的 status、操作者、版本與錯誤。
API 一律讀業務表，不要把 checkpoint 當業務資料查詢。

兩者可以放在同一個 PostgreSQL instance：checkpointer 使用 LangGraph 自己的
checkpoints* 資料表，業務表是 maya_sawa_research_pipeline_runs，彼此不衝突。
需要進一步隔離時，在 DSN 加上 `options=-csearch_path%3D<schema>` 指定 schema。
"""

from __future__ import annotations

import logging
import os
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator

from langgraph.checkpoint.memory import InMemorySaver

logger = logging.getLogger(__name__)

CHECKPOINT_DSN_ENV = "RESEARCH_PIPELINE_CHECKPOINT_DSN"
RUN_DB_DSN_ENV = "RESEARCH_PIPELINE_DB_DSN"
LOCAL_MODE_ENV = "RESEARCH_PIPELINE_LOCAL_MODE"
ENABLED_ENV = "RESEARCH_PIPELINE_ENABLED"

# 多個 replica 同時啟動時，用 advisory lock 讓 setup() 一次只有一個執行。
SETUP_ADVISORY_LOCK_KEY = 8_240_517_001


class CheckpointConfigError(RuntimeError):
    """checkpointer 設定不完整；啟動時應直接失敗。"""


def pipeline_enabled() -> bool:
    """功能未啟用時完全不初始化 pipeline，既有 API 不受影響。"""
    return os.getenv(ENABLED_ENV, "").lower() == "true"


def local_mode_enabled() -> bool:
    return os.getenv(LOCAL_MODE_ENV, "").lower() == "true"


def resolve_checkpoint_dsn() -> str | None:
    """checkpoint 專用 DSN；未設定時沿用業務表所在的同一個 PostgreSQL。"""
    return os.getenv(CHECKPOINT_DSN_ENV) or os.getenv(RUN_DB_DSN_ENV)


def memory_checkpointer() -> InMemorySaver:
    """僅供測試與明確的 local mode；process 結束即消失。"""
    return InMemorySaver()


def setup_with_advisory_lock(saver: Any, dsn: str) -> None:
    """在 advisory lock 保護下執行 setup()，讓多 replica 同時啟動是安全的。

    鎖必須開在另一條 autocommit 連線上：如果借用 saver 自己的連線，
    setup() 的 DDL 交易會和其他 replica 等待中的 advisory lock 互相卡住而 deadlock。
    """
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as lock_conn:
        lock_conn.execute("SELECT pg_advisory_lock(%s)", (SETUP_ADVISORY_LOCK_KEY,))
        try:
            saver.setup()
        finally:
            lock_conn.execute("SELECT pg_advisory_unlock(%s)", (SETUP_ADVISORY_LOCK_KEY,))


def open_postgres_checkpointer(stack: ExitStack, dsn: str, *, setup: bool = True) -> Any:
    """把 PostgresSaver 的生命週期掛到呼叫端的 ExitStack（通常是 app lifespan）。"""
    from langgraph.checkpoint.postgres import PostgresSaver

    saver = stack.enter_context(PostgresSaver.from_conn_string(dsn))
    if setup:
        setup_with_advisory_lock(saver, dsn)
    return saver


def open_checkpointer(stack: ExitStack, *, setup: bool = True) -> Any:
    """依環境變數決定 checkpointer；正式模式缺少 DSN 直接 fail fast。"""
    dsn = resolve_checkpoint_dsn()
    if dsn:
        return open_postgres_checkpointer(stack, dsn, setup=setup)

    if local_mode_enabled():
        logger.warning(
            "%s 未設定且啟用 local mode，改用 in-memory checkpointer："
            "process 重啟後等待審核的 run 將無法 resume。",
            CHECKPOINT_DSN_ENV,
        )
        return memory_checkpointer()

    raise CheckpointConfigError(
        f"缺少 {CHECKPOINT_DSN_ENV}（或 {RUN_DB_DSN_ENV}）。"
        f"research pipeline 的 approve/reject 需要持久化 checkpoint 才能 resume；"
        f"本機開發請明確設定 {LOCAL_MODE_ENV}=true。"
    )


@contextmanager
def postgres_checkpointer(conn_string: str | None = None, *, setup: bool = True) -> Iterator[Any]:
    """獨立的 context manager，供測試與一次性腳本使用。"""
    dsn = conn_string or resolve_checkpoint_dsn()
    if not dsn:
        raise CheckpointConfigError(f"缺少 {CHECKPOINT_DSN_ENV}，無法建立 Postgres checkpointer")

    with ExitStack() as stack:
        yield open_postgres_checkpointer(stack, dsn, setup=setup)
