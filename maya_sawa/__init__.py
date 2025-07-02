"""
Maya Sawa - Markdown Q&A System

這是一個基於 FastAPI、LangChain 和 PostgreSQL 的智能文檔問答系統。

主要功能：
- 支持 Markdown 和 PDF 文檔的智能問答
- 基於向量相似度的文檔檢索
- 多用戶對話歷史管理
- 自動化文章同步
- RESTful API 接口

系統架構：
- FastAPI: Web 框架
- LangChain: AI 應用開發框架
- PostgreSQL + pgvector: 向量數據庫
- Redis: 對話歷史緩存
- OpenAI GPT: 語言模型

作者: Maya Sawa Team
版本: 0.1.0
"""

# 版本信息
__version__ = "0.1.0" 