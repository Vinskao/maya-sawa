"""
核心功能模組

這個包包含系統的核心功能組件，提供：
- 問答鏈處理
- 對話歷史管理
- 文檔載入處理
- 連接池管理
- 同步排程器
- 統一錯誤處理

主要模組：
- qa_chain.py: 問答鏈核心邏輯
- chat_history.py: 對話歷史管理
- loader.py: 文檔載入器
- connection_pool.py: 連接池管理
- scheduler.py: 同步排程器
- qa_engine.py: 問答引擎（佔位符）
- errors.py: 統一錯誤代碼和例外處理

數據庫模組已移至 databases/ 目錄：
- databases/paprika_db.py: Paprika 文章數據庫
- databases/maya_v2_db.py: Maya-v2 對話和 AI 模型數據庫
- databases/postgres_store.py: PostgreSQL 向量存儲

作者: Maya Sawa Team
版本: 0.1.0
"""

# Export error handling utilities
from .errors import (
    ErrorCode,
    AppException,
    ErrorResponse,
    ErrorDetail,
    register_exception_handlers,
    raise_not_found,
    raise_db_unavailable,
    raise_validation_error,
    raise_already_exists,
    raise_operation_failed,
    raise_remote_api_error,
) 