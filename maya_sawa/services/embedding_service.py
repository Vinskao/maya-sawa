"""
向量嵌入服務 (Embedding Service)

這是一個服務層類，封裝 AI 向量嵌入的生成邏輯。
相當於 Java 的 EmbeddingService 或 VectorService。

功能：
- 將文字轉換為向量嵌入 (AI 數字指紋)
- 批量處理文檔向量化
- 統一的嵌入模型管理
- 支持不同的嵌入模型配置

設計理念：
- 服務層封裝：將 OpenAI API 調用封裝在服務層
- 單一職責：只負責向量生成，不涉及數據庫操作
- 可重用：可被多個模組共用（API、數據庫層、業務層）
- 懶加載：只在需要時初始化嵌入模型

Java 對應概念：
```java
@Service
public class EmbeddingService {
    @Autowired
    private OpenAIClient openAIClient;
    
    public List<Float> generateEmbedding(String text) { ... }
    public List<List<Float>> batchGenerateEmbeddings(List<String> texts) { ... }
}
```

使用方式：
```python
# 獲取服務實例
service = get_embedding_service()

# 生成單個向量
vector = service.generate_embedding("你好")

# 批量生成向量
vectors = service.batch_generate_embeddings(["你好", "世界"])
```

作者: Maya Sawa Team
版本: 0.3.0
"""

import os
import logging
from typing import List, Optional, Dict, Any

try:
    from langchain_openai import OpenAIEmbeddings
except ImportError as e:
    raise ImportError(f"langchain_openai is required but not installed. Please install with: poetry install") from e

from ..core.config.config import Config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    向量嵌入服務類 (相當於 Java 的 @Service)

    封裝 OpenAI 嵌入模型，提供統一的向量生成接口。

    設計模式：
    - 單例模式：確保全局只有一個嵌入模型實例
    - 服務層模式：封裝業務邏輯，與數據層解耦
    - 懶加載模式：只在需要時初始化嵌入模型

    主要功能：
    - generate_embedding(): 生成單個文本的向量
    - batch_generate_embeddings(): 批量生成多個文本的向量
    - embed_query(): 針對查詢優化的向量生成
    - embed_documents(): 針對文檔優化的向量生成

    配置管理：
    - 從環境變數讀取 OpenAI API 配置
    - 支持自定義 API 端點和組織 ID
    - 自動重試和錯誤處理
    """
    
    # 類變數：單例實例
    _instance: Optional['EmbeddingService'] = None
    _embeddings: Optional[OpenAIEmbeddings] = None
    
    def __new__(cls):
        """
        單例模式實現 (相當於 Java Singleton)

        確保整個應用程序只有一個 EmbeddingService 實例，
        避免重複初始化 OpenAI 客戶端。
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """
        初始化嵌入服務

        讀取配置但不立即初始化嵌入模型（懶加載）。
        """
        if not hasattr(self, '_initialized'):
            # 從環境變數或配置讀取 OpenAI 配置
            self.api_key = os.getenv("OPENAI_API_KEY") or Config.OPENAI_API_KEY
            self.api_base = os.getenv("OPENAI_API_BASE") or Config.OPENAI_API_BASE
            self.organization = os.getenv("OPENAI_ORGANIZATION")
            
            # 嵌入模型配置
            self.model_name = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            self.embedding_dimensions = int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", "1536"))
            
            self._initialized = True
            logger.info(f"EmbeddingService initialized with model: {self.model_name}")
    
    @property
    def embeddings(self) -> OpenAIEmbeddings:
        """
        獲取嵌入模型實例 (懶加載，相當於 Spring @Lazy)

        只在第一次訪問時初始化 OpenAI Embeddings 模型。

        返回：
            OpenAIEmbeddings 實例，用於生成向量嵌入
        """
        if self._embeddings is None:
            # 初始化 OpenAI 嵌入模型
            self._embeddings = OpenAIEmbeddings(
                base_url=self.api_base,
                api_key=self.api_key,
                openai_organization=self.organization,
                model=self.model_name
            )
            logger.info(f"OpenAI Embeddings model initialized: {self.model_name}")
        return self._embeddings
    
    def generate_embedding(self, text: str) -> List[float]:
        """
        生成單個文本的向量嵌入 (相當於 Java service.generateEmbedding())

        將文本轉換為固定維度的浮點數向量。

        參數：
            text: 要轉換的文本內容

        返回：
            浮點數列表，代表文本的向量嵌入
            例如：[0.123, -0.456, 0.789, ...]

        異常：
            如果 OpenAI API 調用失敗，會拋出異常

        使用場景：
        - 用戶查詢轉向量（用於搜索）
        - 單個文檔轉向量
        - 實時向量生成
        """
        try:
            # 調用 OpenAI API 生成向量
            vector = self.embeddings.embed_query(text)
            logger.debug(f"Generated embedding for text (length: {len(text)} chars, vector dim: {len(vector)})")
            return vector
        except Exception as e:
            logger.error(f"Failed to generate embedding: {str(e)}")
            raise
    
    def batch_generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成多個文本的向量嵌入 (相當於 Java service.batchGenerateEmbeddings())

        批量處理比單個處理更高效，減少 API 調用次數。

        參數：
            texts: 要轉換的文本列表

        返回：
            向量列表的列表，每個文本對應一個向量
            例如：[[0.1, 0.2, ...], [0.3, 0.4, ...], ...]

        效能優化：
        - 單次 API 調用處理多個文本
        - 減少網絡往返次數
        - 適合大批量數據處理

        使用場景：
        - 批量文檔導入
        - 數據遷移
        - 離線向量生成
        """
        try:
            if not texts:
                return []
            
            # 批量調用 OpenAI API
            vectors = self.embeddings.embed_documents(texts)
            logger.info(f"Generated embeddings for {len(texts)} texts")
            return vectors
        except Exception as e:
            logger.error(f"Failed to batch generate embeddings: {str(e)}")
            raise
    
    def embed_query(self, query: str) -> List[float]:
        """
        針對查詢優化的向量生成 (語義搜索用)

        這是 generate_embedding() 的別名，但語義上更清晰。
        用於表示這個向量是用來搜索的，而不是存儲的。

        參數：
            query: 搜索查詢文本

        返回：
            查詢的向量嵌入
        """
        return self.generate_embedding(query)
    
    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """
        針對文檔優化的向量生成 (存儲用)

        這是 batch_generate_embeddings() 的別名，但語義上更清晰。
        用於表示這些向量是要存儲到數據庫的。

        參數：
            documents: 文檔內容列表

        返回：
            文檔的向量嵌入列表
        """
        return self.batch_generate_embeddings(documents)
    
    def get_embedding_info(self) -> Dict[str, Any]:
        """
        獲取嵌入模型的配置信息

        返回：
            包含模型名稱、維度等信息的字典
        """
        return {
            "model_name": self.model_name,
            "dimensions": self.embedding_dimensions,
            "api_base": self.api_base,
            "initialized": self._embeddings is not None
        }


# 單例實例獲取函數 (相當於 Spring 的 getBean())
_service_instance: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """
    獲取嵌入服務實例 (相當於 Java 的依賴注入)

    這是一個工廠函數，確保全局只有一個服務實例。

    相當於 Java：
    ```java
    @Autowired
    private EmbeddingService embeddingService;
    ```

    返回：
        EmbeddingService 單例實例
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = EmbeddingService()
    return _service_instance
