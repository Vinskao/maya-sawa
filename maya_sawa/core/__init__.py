"""
核心功能模組

這個包包含系統的核心功能組件，提供：
- 問答鏈處理
- 對話歷史管理
- 文檔載入處理
- 連接池管理
- 同步排程器
- 統一錯誤處理

組織結構：
├── config/          配置管理
│   ├── config.py           主要配置
│   └── config_manager.py   配置管理器
├── database/        數據庫連接
│   └── connection_pool.py  連接池
├── qa/              問答系統
│   ├── qa_chain.py         QA 鏈
│   └── qa_engine.py        QA 引擎
├── processing/      文檔處理
│   ├── loader.py           文檔載入
│   ├── page_analyzer.py    頁面分析
│   └── langchain_shim.py   LangChain 適配
├── services/        服務層
│   ├── chat_history.py     聊天歷史
│   └── scheduler.py        調度器
├── errors/          錯誤處理
│   └── errors.py           錯誤定義
└── data/            數據文件
    ├── constants.json
    ├── keywords.json
    ├── prompts.json
    └── rules.json

作者: Maya Sawa Team
版本: 0.3.0
"""

# ==================== 導出主要組件 ====================

# 配置管理
from .config.config import Config
from .config.config_manager import config_manager

# 數據庫連接
from .database.connection_pool import get_pool_manager

# QA 系統
from .qa.qa_chain import QAChain

# 處理模組
from .processing.loader import DocumentLoader
from .processing.page_analyzer import PageAnalyzer
from .processing.langchain_shim import Document, PromptTemplate, ChatOpenAI

# 服務層
from .services.chat_history import ChatHistoryManager
from .services.scheduler import ArticleSyncScheduler

# 錯誤處理
from .errors.errors import (
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

# ==================== 向後兼容性 ====================

# 為舊的導入提供別名
qa_chain = QAChain