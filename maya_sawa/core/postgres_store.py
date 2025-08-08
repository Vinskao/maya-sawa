"""
Markdown Q&A System - PostgreSQL 向量存儲模組

這個模組實現了基於 PostgreSQL 的向量存儲功能，負責：
1. 管理文章數據的存儲和檢索
2. 處理向量嵌入的生成和存儲
3. 執行相似度搜索
4. 提供統計信息查詢
5. 支持預計算 embedding 的批量導入

主要功能：
- PostgreSQL 向量數據庫集成
- OpenAI Embeddings 模型支持
- 相似度搜索優化
- 批量數據處理
- 統計信息收集

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
from typing import List, Dict, Any
import os
import logging
from datetime import datetime
import json

# 第三方庫導入
from langchain_openai import OpenAIEmbeddings
from langchain.schema import Document
import psycopg2
from psycopg2.extras import execute_values
from .config import Config

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class PostgresVectorStore:
    """
    PostgreSQL 向量存儲類
    
    負責管理基於 PostgreSQL 的向量數據庫操作，包括：
    - 文章數據的增刪改查
    - 向量嵌入的生成和存儲
    - 相似度搜索
    - 統計信息收集
    """
    
    def __init__(self):
        """
        初始化 PostgreSQL 向量存儲
        
        設置數據庫連接和 OpenAI 配置，並測試連接
        """
        # 從環境變數獲取 OpenAI 配置
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE")
        openai_organization = os.getenv("OPENAI_ORGANIZATION")
        
        # 從環境變數獲取 PostgreSQL 連接字符串
        self.connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
        
        logger.debug(f"PostgresVectorStore - Using API Base: {api_base}")
        
        # 懶加載 embeddings 模型（只在需要時初始化）
        self._embeddings = None
        self.api_key = api_key
        self.api_base = api_base
        self.openai_organization = openai_organization
        
        # 測試數據庫連接
        self._test_connection()

    @property
    def embeddings(self):
        """
        embeddings 模型屬性（懶加載）
        
        只在第一次訪問時初始化 OpenAI Embeddings 模型，
        避免在不需要時浪費資源
        
        Returns:
            OpenAIEmbeddings: 初始化後的 embeddings 模型
        """
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                base_url=self.api_base,
                api_key=self.api_key,
                openai_organization=self.openai_organization
            )
        return self._embeddings

    def _test_connection(self):
        """
        測試數據庫連接
        
        驗證 PostgreSQL 連接字符串是否有效，
        確保應用程式啟動時能正常連接到數據庫
        """
        try:
            with psycopg2.connect(self.connection_string) as conn:
                logger.info("Successfully connected to PostgreSQL database")
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
        with psycopg2.connect(self.connection_string) as conn:
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

    def add_documents(self, documents: List[Document]) -> None:
        """
        添加文檔到向量存儲（保留原有方法以向後兼容）
        
        批量處理 LangChain Document 對象，自動生成 embedding 並存儲到數據庫。
        這是為了向後兼容而保留的方法。
        
        Args:
            documents (List[Document]): LangChain Document 對象列表
        """
        with psycopg2.connect(self.connection_string) as conn:
            cur = conn.cursor()
            
            # 批量生成嵌入向量
            texts = [doc.page_content for doc in documents]
            embeddings = self.embeddings.embed_documents(texts)
            
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

    def similarity_search(self, query: str, k: int = None, threshold: float = None) -> List[Document]:
        """
        執行相似度搜索
        
        使用向量相似度搜索找到與查詢最相關的文檔，
        支持相似度閾值過濾和結果數量限制
        
        Args:
            query (str): 搜索查詢文本
            k (int): 返回結果的最大數量（默認取 Config.ARTICLE_MATCH_COUNT）
            threshold (float): 相似度閾值（默認取 Config.SIMILARITY_THRESHOLD）
            
        Returns:
            List[Document]: 相關文檔列表，按相似度排序
        """
        # 應用預設設定
        if k is None:
            k = Config.ARTICLE_MATCH_COUNT
        if threshold is None:
            threshold = Config.SIMILARITY_THRESHOLD

        # 生成查詢的嵌入向量
        query_embedding = self.embeddings.embed_query(query)
        
        with psycopg2.connect(self.connection_string) as conn:
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
        with psycopg2.connect(self.connection_string) as conn:
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

    def clear(self) -> None:
        """
        清除所有文章數據
        
        清空 articles 表中的所有數據，包括：
        - 文章內容
        - 向量嵌入
        - 元數據信息
        
        注意：此操作不可逆，請謹慎使用
        """
        with psycopg2.connect(self.connection_string) as conn:
            cur = conn.cursor()
            # 使用 TRUNCATE 快速清空表
            cur.execute("TRUNCATE TABLE articles") 
            conn.commit()
            logger.info("All articles have been cleared from the database") 