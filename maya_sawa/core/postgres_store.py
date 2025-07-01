from typing import List, Dict, Any
from langchain_openai import OpenAIEmbeddings
from langchain.schema import Document
import psycopg2
from psycopg2.extras import execute_values
import os
import logging
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class PostgresVectorStore:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE")
        openai_organization = os.getenv("OPENAI_ORGANIZATION")
        self.connection_string = os.getenv(
            "POSTGRES_CONNECTION_STRING",
        )
        
        logger.debug(f"PostgresVectorStore - Using API Base: {api_base}")
        
        # 只在需要時才初始化 embeddings（用於查詢）
        self._embeddings = None
        self.api_key = api_key
        self.api_base = api_base
        self.openai_organization = openai_organization
        
        # 測試資料庫連接
        self._test_connection()

    @property
    def embeddings(self):
        """懶加載 embeddings 模型"""
        if self._embeddings is None:
            self._embeddings = OpenAIEmbeddings(
                base_url=self.api_base,
                api_key=self.api_key,
                openai_organization=self.openai_organization
            )
        return self._embeddings

    def _test_connection(self):
        """測試資料庫連接"""
        try:
            with psycopg2.connect(self.connection_string) as conn:
                logger.info("Successfully connected to PostgreSQL database")
        except Exception as e:
            logger.error(f"Failed to connect to database: {str(e)}")
            raise

    def _parse_embedding(self, embedding_str: str) -> List[float]:
        """解析 embedding 字串為浮點數列表"""
        try:
            # 移除開頭和結尾的方括號，然後分割
            embedding_str = embedding_str.strip('[]')
            return [float(x.strip()) for x in embedding_str.split(',')]
        except Exception as e:
            logger.error(f"Failed to parse embedding: {str(e)}")
            raise ValueError(f"Invalid embedding format: {embedding_str}")

    def add_articles_from_api(self, articles_data: List[Dict[str, Any]]) -> None:
        """從 API 資料添加文章（使用預計算的 embedding）"""
        with psycopg2.connect(self.connection_string) as conn:
            cur = conn.cursor()
            
            # 準備批量插入數據
            data = []
            for article in articles_data:
                try:
                    # 解析預計算的 embedding 並轉換為 PostgreSQL vector 格式
                    embedding_list = self._parse_embedding(article["embedding"])
                    embedding_str = '[' + ','.join(map(str, embedding_list)) + ']'
                    
                    # 轉換日期格式
                    file_date = datetime.fromisoformat(article["file_date"].replace('Z', '+00:00'))
                    
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
        """添加文件到向量存儲（保留原有方法以向後兼容）"""
        with psycopg2.connect(self.connection_string) as conn:
            cur = conn.cursor()
            
            # 批量生成嵌入
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

    def similarity_search(self, query: str, k: int = 4, threshold: float = 0.5) -> List[Document]:
        """搜尋相似文件"""
        # 生成查詢的嵌入向量
        query_embedding = self.embeddings.embed_query(query)
        
        with psycopg2.connect(self.connection_string) as conn:
            cur = conn.cursor()
            
            # 將 Python 列表轉換為 PostgreSQL vector 格式
            embedding_str = '[' + ','.join(map(str, query_embedding)) + ']'
            
            # 直接使用 SQL 查詢，不依賴自定義函數
            cur.execute(
                """
                SELECT 
                    id,
                    file_path,
                    content,
                    1 - (embedding <=> %s::vector) as similarity
                FROM articles
                WHERE 1 - (embedding <=> %s::vector) > %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (embedding_str, embedding_str, threshold, embedding_str, k)
            )
            
            results = cur.fetchall()
            
            # 轉換為 Document 對象
            documents = []
            for result in results:
                doc = Document(
                    page_content=result[2],  # content
                    metadata={
                        "id": result[0],
                        "file_path": result[1],
                        "similarity": result[3]
                    }
                )
                documents.append(doc)
            
            return documents

    def get_article_stats(self) -> Dict[str, Any]:
        """獲取文章統計資訊"""
        with psycopg2.connect(self.connection_string) as conn:
            cur = conn.cursor()
            
            # 獲取基本統計
            cur.execute("""
                SELECT 
                    COUNT(*) as total_articles,
                    pg_size_pretty(pg_total_relation_size('articles')) as table_size,
                    MIN(file_date) as earliest_date,
                    MAX(file_date) as latest_date
                FROM articles
            """)
            
            stats = cur.fetchone()
            
            return {
                "total_articles": stats[0],
                "table_size": stats[1],
                "earliest_date": stats[2].isoformat() if stats[2] else None,
                "latest_date": stats[3].isoformat() if stats[3] else None
            }

    def clear(self) -> None:
        """清除所有文件"""
        with psycopg2.connect(self.connection_string) as conn:
            cur = conn.cursor()
            cur.execute("TRUNCATE TABLE articles") 