"""
QA 向量數據庫模組 (QA Vector Database)

這是系統的核心 AI 功能模組，相當於 Java 的 SearchService + VectorRepository。

核心功能：
1. 向量嵌入存儲：將文檔轉換為 AI 可理解的數學向量
2. 相似度搜索：基於向量距離找到最相關的文檔 (相當於 Elasticsearch)
3. 批量處理：高效處理大量文檔嵌入
4. 統計查詢：提供系統使用統計

AI 概念解釋：
- 嵌入 (Embedding)：將文字轉換為數字向量 (相當於數字指紋)
- 相似度搜索：比較向量距離，距離越近越相似
- 餘弦相似度：向量間的角度，決定相關性

數據庫設計：
- 使用 PostgreSQL + pgvector 擴展 (相當於 Elasticsearch)
- 支持向量索引和高效搜索
- 結合傳統 SQL 查詢和向量搜索

Java 開發者對應：
- QAVectorDatabase 類 ≡ SearchService + VectorDocumentRepository
- similarity_search() ≡ Elasticsearch 的 search() API
- add_documents() ≡ 批量索引文檔

關鍵差異 (Python vs Java)：
- 懶加載嵌入模型：只在需要時初始化 (相當於 Spring @Lazy)
- 自動向量化：文檔進來自動生成向量 (相當於 AOP 攔截器)
- 異步處理：支持大批量處理而不阻塞

效能特點：
- 批量嵌入生成：減少 API 調用次數
- 向量索引：O(log n) 搜索複雜度
- 連接池：自動管理數據庫連接

作者: Maya Sawa Team
版本: 0.2.0
"""

# 標準庫導入
from typing import List, Dict, Any
import os
import logging
from datetime import datetime
import json

# 第三方庫導入
try:
    from langchain.schema import Document
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError as e:
    raise ImportError(f"Required packages not installed. Please install dependencies with: poetry install") from e
from ..core.config.config import Config
from ..core.database.connection_pool import get_pool_manager
from ..services.embedding_service import get_embedding_service

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)


class QAVectorDatabase:
    """
    QA 向量數據庫類 (相當於 Java 的 SearchService)

    這個類整合了傳統數據庫操作和 AI 向量搜索，是系統的 AI 核心。

    架構組件：
    1. 數據庫連接層：SQLAlchemy session 管理 (相當於 JPA EntityManager)
    2. 嵌入生成層：OpenAI API 調用 (相當於 AI 服務客戶端)
    3. 向量搜索層：pgvector 查詢 (相當於 Elasticsearch 客戶端)
    4. 批量處理層：優化大量數據處理

    關鍵屬性：
    - _embeddings: 懶加載的 OpenAI 嵌入模型 (相當於 @Lazy 初始化)
    - connection_string: PostgreSQL 連接字符串
    - pool_manager: 連接池管理器 (相當於 HikariCP)

    設計模式：
    - 單例模式：確保資源重用和配置一致性
    - 模板方法模式：相似度搜索的標準流程
    - 策略模式：不同的嵌入模型和搜索策略

    資源管理：
    - 自動連接池：避免連接洩漏 (相當於 Spring @Transactional)
    - 懶加載模型：節省啟動時間和內存
    - 異常處理：全面的錯誤恢復機制
    """
    
    def __init__(self):
        """
        初始化 QA 向量數據庫
        
        設置數據庫連接，並使用嵌入服務進行向量生成。
        """
        # 從 Config 獲取 PostgreSQL 連接字符串
        from ..core.config.config import Config
        self.connection_string = Config.DB_CONNECTION_STRING
        
        # 獲取連接池管理器
        self.pool_manager = get_pool_manager()
        
        # 獲取嵌入服務（服務層，負責向量生成）
        self.embedding_service = get_embedding_service()
        
        logger.debug(f"QAVectorDatabase initialized with embedding service")
        
        # 測試數據庫連接
        self._test_connection()

    @property
    def embeddings(self):
        """
        向後兼容屬性：使用嵌入服務的底層模型

        這是為了向後兼容舊代碼而保留的屬性。
        新代碼應該直接使用 self.embedding_service。

        返回：
        - OpenAIEmbeddings 實例（通過服務層獲取）
        """
        return self.embedding_service.embeddings

    def _test_connection(self):
        """
        測試數據庫連接
        
        驗證 PostgreSQL 連接字符串是否有效，
        確保應用程式啟動時能正常連接到數據庫
        """
        try:
            conn = self.pool_manager.get_postgres_connection()
            if conn:
                logger.info("Successfully connected to PostgreSQL database")
                self.pool_manager.return_postgres_connection(conn)
            else:
                raise Exception("Failed to get connection from pool")
        except Exception as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            raise

    def _parse_embedding(self, embedding_str: str) -> List[float]:
        """
        解析 embedding 字串為浮點數列表
        
        將字符串格式的 embedding 轉換為 Python 列表，
        用於後續的向量操作
        
        Args:
            embedding_str (str): 字符串格式的 embedding
            
        Returns:
            List[float]: 浮點數列表
            
        Raises:
            ValueError: 當 embedding 格式無效時拋出異常
        """
        try:
            # 移除開頭和結尾的方括號，然後分割
            embedding_str = embedding_str.strip('[]')
            return [float(x.strip()) for x in embedding_str.split(',')]
        except Exception as e:
            logger.error(f"Failed to parse embedding: {str(e)}")
            raise ValueError(f"Invalid embedding format: {embedding_str}")

    def add_articles_from_api(self, articles_data: List[Dict[str, Any]]) -> None:
        """
        從 API 數據添加文章（使用預計算的 embedding）
        
        批量處理從遠端 API 獲取的文章數據，使用預先計算好的 embedding，
        避免在本地重新計算，提高同步效率
        
        Args:
            articles_data (List[Dict[str, Any]]): 文章數據列表，包含預計算的 embedding
        """
        conn = self.pool_manager.get_postgres_connection()
        if not conn:
            raise Exception("Failed to get connection from pool")
        
        try:
            cur = conn.cursor()
            
            # 準備批量插入數據
            data = []
            for article in articles_data:
                try:
                    # 解析預計算的 embedding 並轉換為 PostgreSQL vector 格式
                    embedding_list = self._parse_embedding(article["embedding"])
                    embedding_str = '[' + ','.join(map(str, embedding_list)) + ']'
                    
                    # 轉換日期格式（處理 ISO 格式的日期字符串）
                    file_date = datetime.fromisoformat(article["file_date"].replace('Z', '+00:00'))
                    
                    # 準備插入數據
                    data.append((
                        article["file_path"],
                        article["content"],
                        file_date,
                        embedding_str
                    ))
                except Exception as e:
                    logger.error(f"Failed to process article {article.get('id', 'unknown')}: {str(e)}")
                    continue
            
            if not data:
                logger.warning("No valid articles to insert")
                return
            
            # 執行批量 upsert (插入或更新)
            execute_values(
                cur,
                """
                INSERT INTO articles (file_path, content, file_date, embedding)
                VALUES %s
                ON CONFLICT (file_path) 
                DO UPDATE SET 
                    content = EXCLUDED.content,
                    file_date = EXCLUDED.file_date,
                    embedding = EXCLUDED.embedding::vector,
                    updated_at = CURRENT_TIMESTAMP
                """,
                data,
                template="(%s, %s, %s, %s::vector)"
            )
            
            conn.commit()
            logger.info(f"Successfully processed {len(data)} articles")
        finally:
            self.pool_manager.return_postgres_connection(conn)

    def add_documents(self, documents: List[Document]) -> None:
        """
        添加文檔到向量存儲（保留原有方法以向後兼容）
        
        批量處理 LangChain Document 對象，自動生成 embedding 並存儲到數據庫。
        這是為了向後兼容而保留的方法。
        
        Args:
            documents (List[Document]): LangChain Document 對象列表
        """
        conn = self.pool_manager.get_postgres_connection()
        if not conn:
            raise Exception("Failed to get connection from pool")
        
        try:
            cur = conn.cursor()
            
            # 批量生成嵌入向量（使用服務層）
            texts = [doc.page_content for doc in documents]
            embeddings = self.embedding_service.embed_documents(texts)
            
            # 準備批量插入數據
            data = [
                (
                    doc.metadata.get("source", "unknown"),
                    doc.page_content,
                    datetime.now(),
                    '[' + ','.join(map(str, embedding)) + ']'
                )
                for doc, embedding in zip(documents, embeddings)
            ]
            
            # 執行批量 upsert (插入或更新)
            execute_values(
                cur,
                """
                INSERT INTO articles (file_path, content, file_date, embedding)
                VALUES %s
                ON CONFLICT (file_path) 
                DO UPDATE SET 
                    content = EXCLUDED.content,
                    file_date = EXCLUDED.file_date,
                    embedding = EXCLUDED.embedding::vector,
                    updated_at = CURRENT_TIMESTAMP
                """,
                data,
                template="(%s, %s, %s, %s::vector)"
            )
            
            conn.commit()
        finally:
            self.pool_manager.return_postgres_connection(conn)

    def similarity_search(self, query: str, k: int = None, threshold: float = None) -> List[Document]:
        """
        向量相似度搜索 (相當於 Elasticsearch 的 search API)

        核心 AI 功能：將用戶問題轉換為向量，找到最相關的文檔。

        工作原理 (Java 開發者理解)：
        1. 將查詢文字轉換為向量 (相當於生成數字指紋)
        2. 在向量數據庫中搜索最相似的向量 (相當於 KNN 搜索)
        3. 返回匹配的文檔，按相似度排序

        參數說明：
        - query: 用戶的搜索問題 (例如："什麼是機器學習？")
        - k: 返回的最大結果數 (默認 3，相當於 MySQL LIMIT)
        - threshold: 相似度閾值 (0.0-1.0，相當於 SQL WHERE 條件)

        處理流程：
        1. 生成查詢向量：embeddings.embed_query(query)
        2. 構造向量搜索 SQL：使用 pgvector 的 <=> 運算符
        3. 執行搜索並過濾：相似度 > threshold
        4. 排序並限制：ORDER BY 相似度 DESC LIMIT k
        5. 封裝結果：轉換為 LangChain Document 對象

        SQL 查詢示例：
        ```sql
        SELECT content, 1 - (embedding <=> $query_vector) as similarity
        FROM articles
        WHERE 1 - (embedding <=> $query_vector) > 0.7
        ORDER BY embedding <=> $query_vector
        LIMIT 3
        ```

        返回：
        - List[Document]: 相關文檔列表
        - 每個 Document 包含內容、元數據和相似度分數
        - 按相似度降序排列 (最相關的在前)
        """
        # 應用預設設定
        if k is None:
            k = Config.ARTICLE_MATCH_COUNT
        if threshold is None:
            threshold = Config.SIMILARITY_THRESHOLD

        # 使用嵌入服務生成查詢的向量（服務層）
        query_embedding = self.embedding_service.embed_query(query)
        
        conn = self.pool_manager.get_postgres_connection()
        if not conn:
            raise Exception("Failed to get connection from pool")
        
        try:
            cur = conn.cursor()
            
            # 將 Python 列表轉換為 PostgreSQL vector 格式
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            # 執行相似度搜索查詢
            # 使用 pgvector 的 <=> 運算符計算餘弦距離
            cur.execute(
                """
                SELECT 
                    id,
                    file_path,
                    content,
                    file_date,
                    1 - (embedding <=> %s::vector) as similarity
                FROM articles
                WHERE 1 - (embedding <=> %s::vector) > %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (embedding_str, embedding_str, threshold, embedding_str, k)
            )
            
            results = cur.fetchall()
            
            # 轉換為 LangChain Document 對象
            documents = []
            for result in results:
                doc = Document(
                    page_content=result[2],  # content
                    metadata={
                        "id": result[0],
                        "file_path": result[1],
                        "file_date": result[3].isoformat() if result[3] else "",
                        "similarity": result[4],
                        "source": result[1]  # 使用 file_path 作為 source
                    }
                )
                documents.append(doc)
            
            return documents
        finally:
            self.pool_manager.return_postgres_connection(conn)

    def get_article_stats(self) -> Dict[str, Any]:
        """
        獲取文章統計信息
        
        查詢數據庫中的文章統計信息，包括：
        - 總文章數量
        - 文件大小統計
        - 最近更新時間
        
        Returns:
            Dict[str, Any]: 包含統計信息的字典
        """
        conn = self.pool_manager.get_postgres_connection()
        if not conn:
            raise Exception("Failed to get connection from pool")
        
        try:
            cur = conn.cursor()
            
            # 獲取基本統計信息
            cur.execute("""
                SELECT 
                    COUNT(*) as total_articles,
                    pg_size_pretty(pg_total_relation_size('articles')) as table_size,
                    MIN(file_date) as earliest_date,
                    MAX(file_date) as latest_date
                FROM articles
            """)
            
            stats = cur.fetchone()
            
            # 返回格式化的統計信息
            return {
                "total_articles": stats[0],
                "table_size": stats[1],
                "earliest_date": stats[2].isoformat() if stats[2] else None,
                "latest_date": stats[3].isoformat() if stats[3] else None
            }
        finally:
            self.pool_manager.return_postgres_connection(conn)

    def clear(self) -> None:
        """
        清除所有文章數據
        
        清空 articles 表中的所有數據，包括：
        - 文章內容
        - 向量嵌入
        - 元數據信息
        
        注意：此操作不可逆，請謹慎使用
        """
        conn = self.pool_manager.get_postgres_connection()
        if not conn:
            raise Exception("Failed to get connection from pool")
        
        try:
            cur = conn.cursor()
            # 使用 TRUNCATE 快速清空表
            cur.execute("TRUNCATE TABLE articles") 
            conn.commit()
            logger.info("All articles have been cleared from the database")
        finally:
            self.pool_manager.return_postgres_connection(conn)


# 向後兼容的別名
PostgresVectorStore = QAVectorDatabase
