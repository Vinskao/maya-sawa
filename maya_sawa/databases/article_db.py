"""
文章數據庫模組 (Article Database)

這就像 Java 的 ArticleRepository + ArticleService 的組合。

核心功能：
1. 文章 CRUD 操作 (就像 JPA Repository)
2. 批量處理 (優化效能，避免 N+1 問題)
3. 軟刪除 (邏輯刪除，不真正刪除數據)
4. 數據同步 (從外部 API 導入數據)

設計理念：
- 使用 SQLAlchemy ORM (相當於 JPA/Hibernate)
- 單例模式確保數據庫連接重用
- 批量操作提升效能
- 完整的事務管理

數據庫表結構 (相當於 JPA @Entity)：
```sql
CREATE TABLE articles (
    id SERIAL PRIMARY KEY,                    -- 自動增長主鍵
    file_path VARCHAR(500) UNIQUE NOT NULL,   -- 文件路徑，唯一約束
    content TEXT NOT NULL,                    -- 文章內容
    file_date TIMESTAMP NOT NULL,             -- 文件日期
    embedding TEXT,                           -- 向量嵌入 (JSON 字符串)
    created_at TIMESTAMP DEFAULT NOW(),       -- 創建時間
    updated_at TIMESTAMP DEFAULT NOW(),       -- 更新時間
    deleted_at TIMESTAMP                      -- 軟刪除標記
);
```

Java 開發者對應概念：
- ArticleDatabase 類 ≡ ArticleService + ArticleRepository
- Article 類 ≡ JPA @Entity 註解的類
- get_article_db() 函數 ≡ Spring @Autowired 或 @Service

重要方法說明：
- create_article() - 相當於 JPA save()
- get_article_by_id() - 相當於 JPA findById()
- bulk_create_articles() - 批量插入，效能優化
- sync_articles() - 數據同步，處理創建/更新邏輯

異常處理：
- 使用 try-catch 包裝數據庫操作
- 拋出自定義異常 (相當於 Java 自定義 Exception)
- 提供詳細的錯誤信息

作者: Maya Sawa Team
版本: 0.2.0
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Set
from contextlib import contextmanager

try:
    from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, pool
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, Session
except ImportError as e:
    raise ImportError(f"SQLAlchemy is required but not installed. Please install it with: poetry install") from e

from ..core.config.config import Config

logger = logging.getLogger(__name__)

# SQLAlchemy Base
Base = declarative_base()


class Article(Base):
    """
    文章實體類 (相當於 Java JPA @Entity)

    這個類代表數據庫中的一篇文章，就像 Java 的 POJO/Entity。

    字段說明 (相當於 JPA @Column)：
    - id: 主鍵，自動增長 (相當於 @Id @GeneratedValue)
    - file_path: 文件路徑，唯一且非空 (相當於 @Column(unique=true, nullable=false))
    - content: 文章內容，非空
    - file_date: 文件日期，非空
    - embedding: AI 向量嵌入，可空 (存儲為 JSON 字符串)
    - created_at: 創建時間，自動設置 (相當於 @CreationTimestamp)
    - updated_at: 更新時間，自動更新 (相當於 @UpdateTimestamp)
    - deleted_at: 軟刪除標記，可空 (相當於邏輯刪除字段)

    數據庫約束：
    - 主鍵約束：id 是主鍵
    - 唯一約束：file_path 不能重複 (防止同名文件)
    - 非空約束：file_path, content, file_date 必須有值
    """
    __tablename__ = 'articles'  # 表名 (相當於 JPA @Table(name="articles"))

    # 主鍵字段 (相當於 @Id @GeneratedValue(strategy=GenerationType.IDENTITY))
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 文件路徑，唯一且必填 (相當於 @Column(unique=true, nullable=false, length=500))
    file_path = Column(String(500), unique=True, nullable=False)

    # 文章內容，必填 (相當於 @Column(nullable=false, columnDefinition="TEXT"))
    content = Column(Text, nullable=False)

    # 文件日期，必填 (相當於 @Column(nullable=false))
    file_date = Column(DateTime, nullable=False)

    # AI 向量嵌入，可選 (存儲為 JSON 字符串)
    embedding = Column(Text, nullable=True)  # JSON string of embedding vector

    # 時間戳字段 (相當於 @CreationTimestamp, @UpdateTimestamp)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # For soft deletes

    def to_dict(self) -> Dict[str, Any]:
        """
        轉換為字典 (相當於 Java 的 toString() 或序列化方法)

        將數據庫實體轉換為字典格式，用於 API 響應。
        相當於 Java 的 Bean 序列化。

        返回:
            包含所有字段的字典，按 ISO 格式處理日期
        """
        return {
            'id': self.id,
            'file_path': self.file_path,
            'content': self.content,
            'file_date': self.file_date.isoformat() if self.file_date else None,
            'embedding': self.embedding,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ArticleDatabase:
    """
    文章數據庫管理類 (相當於 Java 的 ArticleService + ArticleRepository)

    這個類封裝了所有文章相關的數據庫操作，相當於 Spring 的 Service 層。

    設計模式：
    - 單例模式：_instance 確保全局只有一個實例
    - DAO 模式：所有數據庫操作都通過這個類
    - 事務管理：每個操作都在 session 上下文管理器中

    連接管理：
    - 使用 SQLAlchemy 連接池 (相當於 Java 的 HikariCP)
    - 自動重連和錯誤處理
    - session 生命周期管理 (相當於 JPA EntityManager)

    錯誤處理：
    - try-catch 包裝所有數據庫操作
    - 拋出 RuntimeError 或自定義異常
    - 記錄詳細錯誤日誌
    """
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        """
        單例模式實現 (相當於 Java 的 Singleton 模式)

        確保整個應用程序只有一個 ArticleDatabase 實例。
        相當於 Java 的：
        ```java
        private static ArticleDatabase instance;
        public static ArticleDatabase getInstance() { ... }
        ```
        """
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """
        初始化數據庫連接 (相當於 Java 的構造函數)

        只在第一次創建實例時調用 _initialize_engine()。
        之後的實例化會重用已創建的連接。
        """
        if self._engine is None:
            self._initialize_engine()
    
    def _initialize_engine(self):
        """Initialize the database engine"""
        db_url = Config.get_paprika_db_url()
        if not db_url:
            logger.warning("Article database URL not configured")
            return
        
        try:
            # Create engine with connection pooling
            self._engine = create_engine(
                db_url,
                poolclass=pool.QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
                echo=False
            )
            
            # Create session factory
            self._session_factory = sessionmaker(bind=self._engine)
            
            # Create tables if they don't exist
            Base.metadata.create_all(self._engine)
            
            logger.info(f"Article database initialized: {db_url.split('@')[0] if '@' in db_url else db_url[:30]}...")
        except Exception as e:
            logger.error(f"Failed to initialize article database: {str(e)}")
            self._engine = None
            self._session_factory = None
    
    @contextmanager
    def get_session(self):
        """Get a database session as context manager"""
        if self._session_factory is None:
            raise RuntimeError("Article database not initialized")
        
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def is_available(self) -> bool:
        """Check if database is available"""
        return self._engine is not None
    
    # Article CRUD Operations
    
    def get_all_articles(self, include_deleted: bool = False) -> List[Article]:
        """Get all articles"""
        with self.get_session() as session:
            query = session.query(Article)
            if not include_deleted:
                query = query.filter(Article.deleted_at.is_(None))
            articles = query.order_by(Article.file_date.desc()).all()
            # Detach from session
            return [self._detach_article(a) for a in articles]
    
    def get_article_by_id(self, article_id: int) -> Optional[Article]:
        """Get article by ID"""
        with self.get_session() as session:
            article = session.query(Article).filter(
                Article.id == article_id,
                Article.deleted_at.is_(None)
            ).first()
            return self._detach_article(article) if article else None
    
    def get_article_by_file_path(self, file_path: str) -> Optional[Article]:
        """Get article by file path"""
        with self.get_session() as session:
            article = session.query(Article).filter(
                Article.file_path == file_path,
                Article.deleted_at.is_(None)
            ).first()
            return self._detach_article(article) if article else None
    
    def create_article(self, file_path: str, content: str, file_date: datetime,
                       embedding: Optional[str] = None) -> Article:
        """
        創建新文章 (相當於 JPA save() 或 INSERT 操作)

        參數說明：
        - file_path: 文件路徑，必須唯一 (相當於業務主鍵)
        - content: 文章內容
        - file_date: 文件日期
        - embedding: AI 向量嵌入 (可選)

        處理邏輯：
        1. 創建 Article 實例 (相當於 new Article())
        2. session.add() 添加到會話 (相當於 JPA persist())
        3. session.flush() 立即執行 SQL (相當於 JPA flush())
        4. _detach_article() 從會話分離 (相當於脫離狀態)

        事務安全：
        - 在 session 上下文管理器中自動處理事務
        - 出錯時自動回滾 (相當於 @Transactional)

        返回:
            新創建的 Article 實例，包含自動生成的主鍵
        """
        with self.get_session() as session:
            # 創建實例 (相當於 new Article())
            article = Article(
                file_path=file_path,
                content=content,
                file_date=file_date,
                embedding=embedding,
                created_at=datetime.utcnow(),  # 服務器時間戳
                updated_at=datetime.utcnow()
            )
            # 添加到會話 (相當於 JPA persist())
            session.add(article)
            # 立即執行 SQL 並獲取自動生成的主鍵
            session.flush()
            # 分離實例以避免懶加載問題
            return self._detach_article(article)
    
    def update_article(self, article_id: int, content: str, file_date: datetime,
                       embedding: Optional[str] = None) -> Optional[Article]:
        """Update an existing article"""
        with self.get_session() as session:
            article = session.query(Article).filter(
                Article.id == article_id,
                Article.deleted_at.is_(None)
            ).first()
            if article:
                article.content = content
                article.file_date = file_date
                if embedding is not None:
                    article.embedding = embedding
                article.updated_at = datetime.utcnow()
                session.flush()
                return self._detach_article(article)
            return None
    
    def delete_article(self, article_id: int, soft_delete: bool = True) -> bool:
        """Delete an article (soft delete by default)"""
        with self.get_session() as session:
            article = session.query(Article).filter(
                Article.id == article_id,
                Article.deleted_at.is_(None)
            ).first()
            if article:
                if soft_delete:
                    article.deleted_at = datetime.utcnow()
                else:
                    session.delete(article)
                return True
            return False
    
    def sync_articles(self, articles_data: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Sync articles from external source
        
        Args:
            articles_data: List of article dictionaries with file_path, content, file_date
            
        Returns:
            Statistics about created, updated, skipped articles
        """
        stats = {
            'total_received': len(articles_data),
            'created': 0,
            'updated': 0,
            'skipped': 0
        }
        
        with self.get_session() as session:
            for article_data in articles_data:
                file_path = article_data.get('file_path')
                content = article_data.get('content')
                file_date_str = article_data.get('file_date')
                
                if not all([file_path, content, file_date_str]):
                    stats['skipped'] += 1
                    continue
                
                # Parse file_date
                if isinstance(file_date_str, str):
                    try:
                        file_date = datetime.fromisoformat(file_date_str.replace('Z', '+00:00'))
                    except ValueError:
                        file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                else:
                    file_date = file_date_str
                
                # Check if article exists
                existing = session.query(Article).filter(
                    Article.file_path == file_path
                ).first()
                
                if not existing:
                    # Create new article
                    article = Article(
                        file_path=file_path,
                        content=content,
                        file_date=file_date,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(article)
                    stats['created'] += 1
                else:
                    # Update if file_date is newer
                    if file_date > existing.file_date:
                        existing.content = content
                        existing.file_date = file_date
                        existing.updated_at = datetime.utcnow()
                        existing.deleted_at = None  # Restore if soft deleted
                        stats['updated'] += 1
                    else:
                        stats['skipped'] += 1
        
        return stats
    
    def get_existing_file_paths_set(self, file_paths: List[str]) -> Set[str]:
        """
        Batch check which file_paths already exist in the database.

        This method checks ALL articles (including soft-deleted ones) because
        the UNIQUE constraint on file_path applies to all records, not just active ones.

        Args:
            file_paths: List of file_paths to check

        Returns:
            Set of file_paths that already exist in the database (any status)
        """
        if not file_paths:
            return set()

        with self.get_session() as session:
            existing_articles = session.query(Article.file_path).filter(
                Article.file_path.in_(file_paths)
            ).all()
            return {article.file_path for article in existing_articles}
    
    def bulk_create_articles(self, articles_data: List[Dict[str, Any]]) -> List[Article]:
        """
        批量創建文章 (效能優化版本，相當於 JPA batch insert)

        為什麼需要批量操作：
        - 單個插入：N 次數據庫往返 (N = 文章數量)
        - 批量插入：1 次數據庫往返
        - 效能提升：數量級的改善

        Java 對應概念：
        - 相當於 Spring Data JPA 的 saveAll()
        - 或 JdbcTemplate 的 batchUpdate()

        參數：
        - articles_data: 文章數據列表，每個包含 file_path, content, file_date

        處理流程：
        1. 準備所有 Article 實例 (內存操作)
        2. session.add_all() 批量添加到會話 (相當於 JPA persist() 循環)
        3. session.flush() 一次性執行所有 INSERT SQL
        4. 分離實例並返回

        效能特點：
        - 減少數據庫連接開銷
        - 利用數據庫批量插入優化
        - 減少事務管理開銷

        返回：
        - 創建成功的 Article 實例列表，按輸入順序
        - 包含自動生成的主鍵 ID
        """
        if not articles_data:
            return []

        # 統一時間戳 (相當於 Java 的 Instant.now())
        now = datetime.utcnow()

        with self.get_session() as session:
            # 步驟1: 準備所有實例 (內存操作，相當於 Java 的 new ArrayList<>())
            articles_to_insert = []
            for data in articles_data:
                # 創建每個實例 (相當於 new Article())
                article = Article(
                    file_path=data['file_path'],
                    content=data['content'],
                    file_date=data['file_date'],
                    embedding=data.get('embedding'),  # 可選字段
                    created_at=now,  # 統一創建時間
                    updated_at=now
                )
                articles_to_insert.append(article)

            # 步驟2: 批量添加到會話 (相當於 JPA entityManager.persist() 循環)
            session.add_all(articles_to_insert)

            # 步驟3: 一次性執行所有 SQL (相當於 flush())
            # 這會生成批量 INSERT 語句，而不是 N 個單獨的 INSERT
            session.flush()

            # 步驟4: 分離實例避免懶加載問題
            return [self._detach_article(a) for a in articles_to_insert]
    
    def _detach_article(self, article: Article) -> Article:
        """Create a detached copy of article"""
        if article is None:
            return None
        
        # Create a new instance with same values
        detached = Article(
            id=article.id,
            file_path=article.file_path,
            content=article.content,
            file_date=article.file_date,
            embedding=article.embedding,
            created_at=article.created_at,
            updated_at=article.updated_at,
            deleted_at=article.deleted_at
        )
        return detached


# Singleton instance getter
def get_article_db() -> ArticleDatabase:
    """Get article database instance"""
    return ArticleDatabase()


# 向後兼容的別名
PaprikaDatabase = ArticleDatabase
get_paprika_db = get_article_db
