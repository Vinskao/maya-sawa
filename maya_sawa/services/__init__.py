"""
服務模組 (Services Module)

這個模組包含系統的服務層類，負責封裝業務邏輯。

服務類：
- EmbeddingService: 向量嵌入服務，統一管理 AI 向量生成
- AI Providers: 多 AI 提供者支持 (OpenAI, Gemini, Qwen)

設計理念：
- 服務層封裝：將業務邏輯從數據層和 API 層分離
- 單一職責：每個服務專注於特定功能
- 可重用性：服務可被多個模組共用

作者: Maya Sawa Team
版本: 0.3.0
"""

from .embedding_service import EmbeddingService, get_embedding_service

__all__ = [
    'EmbeddingService',
    'get_embedding_service',
]
