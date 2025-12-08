"""
Paprika Database Connection Module

This module provides database connection and models for the paprika (Laravel) articles.
Uses SQLAlchemy for database operations.

Author: Maya Sawa Team
Version: 0.1.0
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from ..core.config import Config

logger = logging.getLogger(__name__)

# SQLAlchemy Base
Base = declarative_base()


class Article(Base):
    """
    Article model matching the paprika Laravel application schema
    """
    __tablename__ = 'articles'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    file_path = Column(String(500), unique=True, nullable=False)
    content = Column(Text, nullable=False)
    file_date = Column(DateTime, nullable=False)
    embedding = Column(Text, nullable=True)  # JSON string of embedding vector
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # For soft deletes
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert article to dictionary"""
        return {
            'id': self.id,
            'file_path': self.file_path,
            'content': self.content,
            'file_date': self.file_date.isoformat() if self.file_date else None,
            'embedding': self.embedding,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class PaprikaDatabase:
    """
    Database manager for paprika articles
    """
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._engine is None:
            self._initialize_engine()
    
    def _initialize_engine(self):
        """Initialize the database engine"""
        db_url = Config.get_paprika_db_url()
        if not db_url:
            logger.warning("Paprika database URL not configured")
            return
        
        try:
            # Create engine with connection pooling
            self._engine = create_engine(
                db_url,
                poolclass=QueuePool,
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
            
            logger.info(f"Paprika database initialized: {db_url.split('@')[0]}@***")
        except Exception as e:
            logger.error(f"Failed to initialize paprika database: {str(e)}")
            self._engine = None
            self._session_factory = None
    
    @contextmanager
    def get_session(self):
        """Get a database session as context manager"""
        if self._session_factory is None:
            raise RuntimeError("Paprika database not initialized")
        
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
        """Create a new article"""
        with self.get_session() as session:
            article = Article(
                file_path=file_path,
                content=content,
                file_date=file_date,
                embedding=embedding,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            session.add(article)
            session.flush()
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


# Singleton instance
def get_paprika_db() -> PaprikaDatabase:
    """Get paprika database instance"""
    return PaprikaDatabase()



