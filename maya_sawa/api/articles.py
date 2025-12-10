"""
Paprika Articles API Module

This module provides API endpoints for article management,
migrated from the Laravel paprika application.

Endpoints:
- GET /paprika/articles - List all articles
- GET /paprika/articles/{id} - Get single article
- POST /paprika/articles - Create article
- PUT /paprika/articles/{id} - Update article
- DELETE /paprika/articles/{id} - Delete article
- POST /paprika/articles/batch - Batch create articles
- POST /paprika/articles/sync - Batch sync articles
- GET /paprika/up - Health check

Author: Maya Sawa Team
Version: 0.1.0
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, status, HTTPException
from pydantic import BaseModel, Field

from ..databases.article_db import get_article_db
from ..core.errors.errors import (
    ErrorCode,
    AppException,
    raise_not_found,
    raise_db_unavailable,
    raise_already_exists,
)
from ..services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)

# Create router with paprika prefix
router = APIRouter(prefix="/paprika", tags=["Paprika Articles"])


# ==================== Request/Response Models ====================

class ArticleBase(BaseModel):
    """Base article model"""
    file_path: str = Field(..., max_length=500)
    content: str
    file_date: datetime


class ArticleCreate(ArticleBase):
    """Article creation request"""
    pass


class ArticleUpdate(BaseModel):
    """Article update request"""
    content: str
    file_date: datetime


class ArticleResponse(BaseModel):
    """Article response model"""
    id: int
    file_path: str
    content: str
    file_date: Optional[str] = None
    embedding: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ArticleSyncItem(BaseModel):
    """Single article for sync"""
    file_path: str = Field(..., max_length=500)
    content: str
    file_date: str


class ArticleSyncRequest(BaseModel):
    """Batch sync request"""
    articles: List[ArticleSyncItem]


class ArticleSyncResponse(BaseModel):
    """Sync response with statistics"""
    success: bool
    message: str
    data: Dict[str, int]
    timestamp: str


class VectorizeArticleItem(BaseModel):
    """單篇文章向量化請求"""
    file_path: str = Field(..., max_length=500)
    content: str


class VectorizeArticlesRequest(BaseModel):
    """批量文章向量化請求"""
    articles: List[VectorizeArticleItem]
    overwrite: bool = True


class PurgeDeletedResponse(BaseModel):
    """永久刪除已軟刪除文章的回應"""
    success: bool
    deleted: int
    message: str


# ==================== Helper Functions ====================

def _ensure_db_available():
    """
    Check if Paprika database is available.
    Raises AppException if not available.
    """
    db = get_article_db()
    if not db.is_available():
        raise_db_unavailable("Paprika")
    return db


# ==================== API Endpoints ====================

@router.get("/up")
async def health_check():
    """
    Health check endpoint
    
    Returns the service status and current timestamp
    """
    db = get_article_db()
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "database_available": db.is_available()
    }


@router.get("/articles", response_model=Dict[str, Any])
async def list_articles():
    """
    Get all articles
    
    Returns a list of all articles ordered by file_date descending
    """
    db = _ensure_db_available()
    
    try:
        articles = db.get_all_articles()
        return {
            "success": True,
            "data": [a.to_dict() for a in articles]
        }
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch articles: {str(e)}")
        raise AppException(
            ErrorCode.ARTICLE_FETCH_FAILED,
            detail={"error": str(e)}
        )


@router.get("/articles/{article_id}", response_model=Dict[str, Any])
async def get_article(article_id: int):
    """
    Get single article by ID
    
    Args:
        article_id: The article ID
        
    Returns:
        The article data
    """
    db = _ensure_db_available()
    
    try:
        article = db.get_article_by_id(article_id)
        
        if not article:
            raise_not_found("Article", article_id, ErrorCode.ARTICLE_NOT_FOUND)
        
        return {
            "success": True,
            "data": article.to_dict()
        }
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch article: {str(e)}")
        raise AppException(
            ErrorCode.ARTICLE_FETCH_FAILED,
            detail={"article_id": article_id, "error": str(e)}
        )


@router.post("/articles", response_model=Dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_article(request: ArticleCreate):
    """
    Create a new article
    
    Args:
        request: Article creation data
        
    Returns:
        The created article
    """
    db = _ensure_db_available()
    
    try:
        # Check if article with same file_path exists
        existing = db.get_article_by_file_path(request.file_path)
        if existing:
            raise_already_exists("Article", "file_path", request.file_path)
        
        article = db.create_article(
            file_path=request.file_path,
            content=request.content,
            file_date=request.file_date
        )
        
        return {
            "success": True,
            "message": "Article created successfully",
            "data": article.to_dict()
        }
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to create article: {str(e)}")
        raise AppException(
            ErrorCode.ARTICLE_CREATE_FAILED,
            detail={"file_path": request.file_path, "error": str(e)}
        )


@router.put("/articles/{article_id}", response_model=Dict[str, Any])
async def update_article(article_id: int, request: ArticleUpdate):
    """
    Update an existing article
    
    Args:
        article_id: The article ID
        request: Article update data
        
    Returns:
        The updated article
    """
    db = _ensure_db_available()
    
    try:
        article = db.update_article(
            article_id=article_id,
            content=request.content,
            file_date=request.file_date
        )
        
        if not article:
            raise_not_found("Article", article_id, ErrorCode.ARTICLE_NOT_FOUND)
        
        return {
            "success": True,
            "message": "Article updated successfully",
            "data": article.to_dict()
        }
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to update article: {str(e)}")
        raise AppException(
            ErrorCode.ARTICLE_UPDATE_FAILED,
            detail={"article_id": article_id, "error": str(e)}
        )


@router.delete("/articles/{article_id}", response_model=Dict[str, Any])
async def delete_article(article_id: int):
    """
    Delete an article (soft delete)
    
    Args:
        article_id: The article ID
        
    Returns:
        Success message
    """
    db = _ensure_db_available()
    
    try:
        success = db.delete_article(article_id, soft_delete=True)
        
        if not success:
            raise_not_found("Article", article_id, ErrorCode.ARTICLE_NOT_FOUND)
        
        return {
            "success": True,
            "message": "Article deleted successfully"
        }
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete article: {str(e)}")
        raise AppException(
            ErrorCode.ARTICLE_DELETE_FAILED,
            detail={"article_id": article_id, "error": str(e)}
        )


@router.post("/articles/batch", response_model=Dict[str, Any])
async def create_articles_batch(request: List[ArticleCreate]):
    """
    Batch create multiple articles

    Accepts an array of articles and creates them in batch.
    Skips articles with duplicate file_path.
    
    Optimizations:
    - Input validation for empty arrays and batch size limits
    - Single query to check all duplicates (instead of N queries)
    - Bulk insert for all new articles (instead of N inserts)

    Args:
        request: Array of article creation data (max 1000 items)

    Returns:
        Batch creation results with statistics
    """
    # Input validation
    if not request:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request array cannot be empty"
        )
    
    if len(request) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Batch size exceeds maximum limit of 1000"
        )
    
    db = _ensure_db_available()

    results = {
        "success": True,
        "total_requested": len(request),
        "created": 0,
        "updated": 0,
        "skipped_duplicate": 0,
        "skipped_unchanged": 0,
        "failed": 0,
        "deleted": 0,
        "errors": [],
        "articles": []
    }

    # Track which file_paths we've seen in this request to detect duplicates
    # 目標：避免單次 payload 內的重複，並後續用來判斷缺席的舊文
    seen_in_request = set()
    duplicate_in_request = set()

    # First pass: identify duplicates within the request
    # 記錄 request 內部的重複 file_path
    for article_data in request:
        file_path = article_data.file_path
        if file_path in seen_in_request:
            duplicate_in_request.add(file_path)
        else:
            seen_in_request.add(file_path)

    # Get unique file paths to check against database (excluding duplicates within request)
    # 單次查詢抓出 DB 已有的文章，避免 N+1
    unique_file_paths = seen_in_request - duplicate_in_request
    existing_articles = db.get_articles_by_file_paths(unique_file_paths) if unique_file_paths else {}
    existing_paths = set(existing_articles.keys())

    # Second pass: process each item
    to_create = []

    for i, article_data in enumerate(request):
        file_path = article_data.file_path

        # Check if this file_path appears multiple times in the request
        # 同一批次內重複，直接記錯誤並跳過
        if file_path in duplicate_in_request:
            results["skipped_duplicate"] += 1
            results["errors"].append({
                "index": i,
                "file_path": file_path,
                "error_code": ErrorCode.ARTICLE_ALREADY_EXISTS.code,
                "error": "Article with this file_path appears multiple times in request"
            })
            continue

        # Check if this file_path already exists in database
        # 若已存在：比對內容，不同則更新並重置 embedding，否則跳過
        if file_path in existing_paths:
            existing = existing_articles[file_path]
            if existing.content != article_data.content:
                try:
                    updated = db.update_content_if_changed(
                        file_path=file_path,
                        content=article_data.content,
                        file_date=article_data.file_date,
                        reset_embedding=True,
                    )
                    if updated:
                        results["updated"] += 1
                        results["articles"].append({
                            "index": i,
                            "file_path": file_path,
                            "updated": True
                        })
                    else:
                        results["skipped_unchanged"] += 1
                except Exception as update_error:
                    results["failed"] += 1
                    results["errors"].append({
                        "index": i,
                        "file_path": file_path,
                        "error_code": ErrorCode.ARTICLE_UPDATE_FAILED.code,
                        "error": str(update_error)
                    })
            else:
                results["skipped_unchanged"] += 1
            continue

        # This file_path is unique within request and doesn't exist in DB
        # 新檔案：待批次創建
        to_create.append((i, article_data))
    
    # Bulk create all non-duplicate articles
    # 優先批量寫入，失敗再退回逐筆
    if to_create:
        try:
            articles_data = [
                {
                    "file_path": data.file_path,
                    "content": data.content,
                    "file_date": data.file_date
                }
                for _, data in to_create
            ]
            created_articles = db.bulk_create_articles(articles_data)
            
            for (index, _), article in zip(to_create, created_articles):
                results["created"] += 1
                results["articles"].append({
                    "index": index,
                    "id": article.id,
                    "file_path": article.file_path,
                    "created": True
                })
        except Exception as e:
            # If bulk insert fails, fall back to individual inserts
            logger.warning(f"Bulk insert failed, falling back to individual inserts: {e}")
            for index, article_data in to_create:
                try:
                    article = db.create_article(
                        file_path=article_data.file_path,
                        content=article_data.content,
                        file_date=article_data.file_date
                    )
                    results["created"] += 1
                    results["articles"].append({
                        "index": index,
                        "id": article.id,
                        "file_path": article.file_path,
                        "created": True
                    })
                except Exception as create_error:
                    results["failed"] += 1
                    results["errors"].append({
                        "index": index,
                        "file_path": article_data.file_path,
                        "error_code": ErrorCode.ARTICLE_CREATE_FAILED.code,
                        "error": str(create_error)
                    })

    # Prune articles that are no longer present in request (soft delete)
    # 用本次 payload 清單對帳，未出現者標記軟刪除
    try:
        pruned = db.soft_delete_articles_not_in(seen_in_request)
        results["deleted"] = pruned
    except Exception as prune_error:
        results["errors"].append({
            "file_paths": "ALL_EXCLUDING_REQUEST",
            "error_code": ErrorCode.ARTICLE_DELETE_FAILED.code,
            "error": str(prune_error)
        })

    results["message"] = (
        f"Batch completed: {results['created']} created, "
        f"{results['updated']} updated, "
        f"{results['skipped_unchanged']} skipped (unchanged), "
        f"{results['skipped_duplicate']} skipped (duplicate in request), "
        f"{results['deleted']} deleted, "
        f"{results['failed']} failed"
    )

    return results


@router.post("/articles/sync", response_model=ArticleSyncResponse)
async def sync_articles(request: ArticleSyncRequest):
    """
    Batch sync articles
    
    Creates new articles or updates existing ones based on file_path.
    Only updates if the new file_date is more recent.
    
    Args:
        request: List of articles to sync
        
    Returns:
        Sync statistics
    """
    db = _ensure_db_available()
    
    try:
        # Convert request to dict format
        articles_data = [
            {
                "file_path": a.file_path,
                "content": a.content,
                "file_date": a.file_date
            }
            for a in request.articles
        ]
        
        stats = db.sync_articles(articles_data)
        
        return ArticleSyncResponse(
            success=True,
            message="Articles synced successfully",
            data=stats,
            timestamp=datetime.utcnow().isoformat()
        )
    except AppException:
        raise
    except Exception as e:
        logger.error(f"Article sync failed: {str(e)}")
        raise AppException(
            ErrorCode.ARTICLE_SYNC_FAILED,
            detail={"error": str(e)}
        )


@router.post("/articles/vectorize", response_model=Dict[str, Any])
async def vectorize_articles(request: VectorizeArticlesRequest):
    """
    將文章內容轉為向量並寫回資料庫（embedding 欄位）

    - 使用共用的 EmbeddingService 生成向量
    - 只更新已存在的文章，避免誤創建
    - 默認允許覆寫既有 embedding（可透過 overwrite=false 跳過）
    """
    db = _ensure_db_available()

    if not request.articles:
        raise HTTPException(status_code=400, detail="articles cannot be empty")

    embedding_service = get_embedding_service()

    stats = {
        "total_requested": len(request.articles),
        "vectorized": 0,
        "skipped_empty": 0,
        "not_found": 0,
        "skipped_unchanged": 0,
        "errors": []
    }

    for item in request.articles:
        # 內容空白直接跳過
        if not item.content or not item.content.strip():
            stats["skipped_empty"] += 1
            continue

        article = db.get_article_by_file_path(item.file_path)
        # 找不到既有文章就記錄 not_found
        if not article:
            stats["not_found"] += 1
            continue

        content_changed = article.content != item.content

        try:
            if content_changed:
                # 內容變更：重寫內容並重算 embedding
                vector = embedding_service.generate_embedding(item.content)
                updated = db.update_content_and_embedding(
                    file_path=item.file_path,
                    content=item.content,
                    embedding=vector,
                )
                if updated:
                    stats["vectorized"] += 1
                else:
                    stats["not_found"] += 1
            else:
                # 內容相同：已有 embedding 且不覆寫則跳過；否則可重算覆寫
                if article.embedding and not request.overwrite:
                    stats["skipped_unchanged"] += 1
                else:
                    vector = embedding_service.generate_embedding(item.content)
                    updated = db.update_embedding_by_file_path(
                        item.file_path,
                        vector,
                        overwrite=True,
                    )
                    if updated:
                        stats["vectorized"] += 1
                    else:
                        stats["not_found"] += 1

        except Exception as e:
            logger.error(f"Failed to vectorize article {item.file_path}: {e}")
            stats["errors"].append({"file_path": item.file_path, "error": str(e)})

    return {
        "success": len(stats["errors"]) == 0,
        "message": (
            f"Vectorized {stats['vectorized']} articles, "
            f"skipped {stats['skipped_empty']} empty, "
            f"{stats['skipped_unchanged']} unchanged, "
            f"{stats['not_found']} not found"
        ),
        "data": stats,
    }


@router.post("/articles/purge-deleted", response_model=PurgeDeletedResponse)
async def purge_deleted_articles():
    """
    永久刪除已軟刪除的文章 (deleted_at is not null)
    """
    db = _ensure_db_available()
    try:
        deleted = db.hard_delete_soft_deleted()
        return PurgeDeletedResponse(
            success=True,
            deleted=deleted,
            message=f"Permanently removed {deleted} soft-deleted articles"
        )
    except Exception as e:
        logger.error(f"Failed to purge soft-deleted articles: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to purge soft-deleted articles: {str(e)}"
        )
