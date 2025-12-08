"""
Unified Error Handling Module

This module provides centralized error codes and exception handling
for the Maya Sawa Unified API, similar to Java's enum-based error management.

Features:
- ErrorCode enum for all error codes
- AppException custom exception class
- Standardized error response format
- Global exception handlers for FastAPI

Author: Maya Sawa Team
Version: 0.1.0
"""

from enum import Enum
from typing import Any, Dict, Optional, List
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


# ==================== Error Codes Enum ====================

class ErrorCode(Enum):
    """
    Centralized error codes for the application.
    
    Each error code contains:
    - code: Unique error code string
    - message: Default error message (Chinese)
    - message_en: Default error message (English)
    - http_status: HTTP status code to return
    
    Usage:
        raise AppException(ErrorCode.RESOURCE_NOT_FOUND, detail={"id": 123})
    """
    
    # ==================== General Errors (1000-1099) ====================
    INTERNAL_SERVER_ERROR = (
        "E1000", 
        "伺服器內部錯誤", 
        "Internal server error",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    BAD_REQUEST = (
        "E1001", 
        "請求參數錯誤", 
        "Bad request",
        status.HTTP_400_BAD_REQUEST
    )
    VALIDATION_ERROR = (
        "E1002", 
        "資料驗證失敗", 
        "Validation failed",
        status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    UNAUTHORIZED = (
        "E1003", 
        "未授權的請求", 
        "Unauthorized",
        status.HTTP_401_UNAUTHORIZED
    )
    FORBIDDEN = (
        "E1004", 
        "禁止訪問", 
        "Forbidden",
        status.HTTP_403_FORBIDDEN
    )
    NOT_FOUND = (
        "E1005", 
        "資源不存在", 
        "Resource not found",
        status.HTTP_404_NOT_FOUND
    )
    METHOD_NOT_ALLOWED = (
        "E1006", 
        "請求方法不允許", 
        "Method not allowed",
        status.HTTP_405_METHOD_NOT_ALLOWED
    )
    CONFLICT = (
        "E1007", 
        "資源衝突", 
        "Resource conflict",
        status.HTTP_409_CONFLICT
    )
    TOO_MANY_REQUESTS = (
        "E1008", 
        "請求過於頻繁", 
        "Too many requests",
        status.HTTP_429_TOO_MANY_REQUESTS
    )
    
    # ==================== Database Errors (2000-2099) ====================
    DATABASE_UNAVAILABLE = (
        "E2000", 
        "資料庫服務不可用", 
        "Database service unavailable",
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    DATABASE_CONNECTION_ERROR = (
        "E2001", 
        "資料庫連接失敗", 
        "Database connection error",
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    DATABASE_QUERY_ERROR = (
        "E2002", 
        "資料庫查詢錯誤", 
        "Database query error",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    DATABASE_WRITE_ERROR = (
        "E2003", 
        "資料庫寫入錯誤", 
        "Database write error",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    
    # ==================== Article Errors (3000-3099) ====================
    ARTICLE_NOT_FOUND = (
        "E3000", 
        "文章不存在", 
        "Article not found",
        status.HTTP_404_NOT_FOUND
    )
    ARTICLE_ALREADY_EXISTS = (
        "E3001", 
        "文章已存在", 
        "Article already exists",
        status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    ARTICLE_CREATE_FAILED = (
        "E3002", 
        "文章建立失敗", 
        "Failed to create article",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    ARTICLE_UPDATE_FAILED = (
        "E3003", 
        "文章更新失敗", 
        "Failed to update article",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    ARTICLE_DELETE_FAILED = (
        "E3004", 
        "文章刪除失敗", 
        "Failed to delete article",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    ARTICLE_SYNC_FAILED = (
        "E3005", 
        "文章同步失敗", 
        "Failed to sync articles",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    ARTICLE_FETCH_FAILED = (
        "E3006", 
        "文章獲取失敗", 
        "Failed to fetch articles",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    
    # ==================== AI Model Errors (4000-4099) ====================
    AI_MODEL_NOT_FOUND = (
        "E4000", 
        "AI 模型不存在", 
        "AI model not found",
        status.HTTP_404_NOT_FOUND
    )
    AI_MODEL_UNAVAILABLE = (
        "E4001", 
        "AI 模型不可用", 
        "AI model unavailable",
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    AI_PROVIDER_NOT_CONFIGURED = (
        "E4002", 
        "AI 服務提供者未配置", 
        "AI provider not configured",
        status.HTTP_400_BAD_REQUEST
    )
    AI_PROCESSING_FAILED = (
        "E4003", 
        "AI 處理失敗", 
        "AI processing failed",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    AI_MODEL_FETCH_FAILED = (
        "E4004", 
        "AI 模型獲取失敗", 
        "Failed to fetch AI model",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    AI_MODEL_CREATE_FAILED = (
        "E4005", 
        "AI 模型建立失敗", 
        "Failed to create AI model",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    
    # ==================== Conversation Errors (5000-5099) ====================
    CONVERSATION_NOT_FOUND = (
        "E5000", 
        "對話不存在", 
        "Conversation not found",
        status.HTTP_404_NOT_FOUND
    )
    CONVERSATION_CREATE_FAILED = (
        "E5001", 
        "對話建立失敗", 
        "Failed to create conversation",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    CONVERSATION_UPDATE_FAILED = (
        "E5002", 
        "對話更新失敗", 
        "Failed to update conversation",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    CONVERSATION_DELETE_FAILED = (
        "E5003", 
        "對話刪除失敗", 
        "Failed to delete conversation",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    MESSAGE_SEND_FAILED = (
        "E5004", 
        "訊息發送失敗", 
        "Failed to send message",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    MESSAGE_FETCH_FAILED = (
        "E5005", 
        "訊息獲取失敗", 
        "Failed to fetch messages",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    SESSION_ALREADY_EXISTS = (
        "E5006", 
        "會話 ID 已存在", 
        "Session ID already exists",
        status.HTTP_400_BAD_REQUEST
    )
    CHAT_HISTORY_FAILED = (
        "E5007", 
        "聊天記錄獲取失敗", 
        "Failed to get chat history",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    
    # ==================== Task Errors (6000-6099) ====================
    TASK_NOT_FOUND = (
        "E6000", 
        "任務不存在", 
        "Task not found",
        status.HTTP_404_NOT_FOUND
    )
    TASK_CREATE_FAILED = (
        "E6001", 
        "任務建立失敗", 
        "Failed to create task",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    TASK_STATUS_FAILED = (
        "E6002", 
        "任務狀態獲取失敗", 
        "Failed to get task status",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    TASK_QUEUE_FAILED = (
        "E6003", 
        "任務排程失敗", 
        "Failed to queue task",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    
    # ==================== External Service Errors (7000-7099) ====================
    REMOTE_API_ERROR = (
        "E7000", 
        "遠端 API 錯誤", 
        "Remote API error",
        status.HTTP_502_BAD_GATEWAY
    )
    REMOTE_API_UNAVAILABLE = (
        "E7001", 
        "無法連接遠端 API", 
        "Cannot connect to remote API",
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    REMOTE_API_TIMEOUT = (
        "E7002", 
        "遠端 API 超時", 
        "Remote API timeout",
        status.HTTP_504_GATEWAY_TIMEOUT
    )
    OPENAI_CLIENT_UNAVAILABLE = (
        "E7003", 
        "OpenAI 客戶端不可用", 
        "OpenAI client unavailable",
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    EMBEDDING_GENERATION_FAILED = (
        "E7004", 
        "Embedding 生成失敗", 
        "Failed to generate embedding",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    REDIS_UNAVAILABLE = (
        "E7005", 
        "Redis 服務不可用", 
        "Redis service unavailable",
        status.HTTP_503_SERVICE_UNAVAILABLE
    )
    
    # ==================== QA/Search Errors (8000-8099) ====================
    SEARCH_FAILED = (
        "E8000", 
        "搜索失敗", 
        "Search failed",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    QA_QUERY_FAILED = (
        "E8001", 
        "問答查詢失敗", 
        "Q&A query failed",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    STATS_FETCH_FAILED = (
        "E8002", 
        "統計資訊獲取失敗", 
        "Failed to fetch statistics",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    SYNC_FAILED = (
        "E8003", 
        "同步失敗", 
        "Sync failed",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    PAGE_ANALYSIS_FAILED = (
        "E8004", 
        "頁面分析失敗", 
        "Page analysis failed",
        status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    
    def __init__(self, code: str, message: str, message_en: str, http_status: int):
        self._code = code
        self._message = message
        self._message_en = message_en
        self._http_status = http_status
    
    @property
    def code(self) -> str:
        """Return the error code string"""
        return self._code
    
    @property
    def message(self) -> str:
        """Return the default message (Chinese)"""
        return self._message
    
    @property
    def message_en(self) -> str:
        """Return the default message (English)"""
        return self._message_en
    
    @property
    def http_status(self) -> int:
        """Return the HTTP status code"""
        return self._http_status


# ==================== Response Models ====================

class ErrorDetail(BaseModel):
    """Error detail model for validation errors"""
    field: str
    message: str
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    """
    Standardized error response model.
    
    All API errors will return responses in this format.
    """
    success: bool = False
    error_code: str
    message: str
    message_en: Optional[str] = None
    detail: Optional[Any] = None
    errors: Optional[List[ErrorDetail]] = None
    timestamp: Optional[str] = None
    path: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": False,
                "error_code": "E3000",
                "message": "文章不存在",
                "message_en": "Article not found",
                "detail": {"article_id": 123},
                "timestamp": "2024-01-01T00:00:00Z",
                "path": "/maya-sawa/paprika/articles/123"
            }
        }


# ==================== Custom Exception ====================

class AppException(Exception):
    """
    Custom application exception with error code support.
    
    Usage:
        raise AppException(ErrorCode.ARTICLE_NOT_FOUND, detail={"id": 123})
        raise AppException(ErrorCode.DATABASE_UNAVAILABLE, message="Paprika database not available")
    """
    
    def __init__(
        self,
        error_code: ErrorCode,
        message: Optional[str] = None,
        message_en: Optional[str] = None,
        detail: Optional[Any] = None,
        errors: Optional[List[Dict[str, str]]] = None
    ):
        self.error_code = error_code
        self.message = message or error_code.message
        self.message_en = message_en or error_code.message_en
        self.detail = detail
        self.errors = errors
        self.http_status = error_code.http_status
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for JSON response"""
        response = {
            "success": False,
            "error_code": self.error_code.code,
            "message": self.message,
            "message_en": self.message_en,
        }
        if self.detail is not None:
            response["detail"] = self.detail
        if self.errors is not None:
            response["errors"] = self.errors
        return response


# ==================== Exception Handlers ====================

async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Global handler for AppException.
    
    Returns standardized JSON response with error details.
    """
    from datetime import datetime
    
    logger.error(
        f"AppException: {exc.error_code.code} - {exc.message}",
        extra={"detail": exc.detail, "path": request.url.path}
    )
    
    response_data = exc.to_dict()
    response_data["timestamp"] = datetime.utcnow().isoformat()
    response_data["path"] = str(request.url.path)
    
    return JSONResponse(
        status_code=exc.http_status,
        content=response_data
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """
    Global handler for HTTPException.
    
    Converts HTTPException to standardized response format.
    """
    from datetime import datetime
    
    # Map HTTP status to error code
    status_to_error_code = {
        status.HTTP_400_BAD_REQUEST: ErrorCode.BAD_REQUEST,
        status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
        status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
        status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.METHOD_NOT_ALLOWED,
        status.HTTP_409_CONFLICT: ErrorCode.CONFLICT,
        status.HTTP_422_UNPROCESSABLE_ENTITY: ErrorCode.VALIDATION_ERROR,
        status.HTTP_429_TOO_MANY_REQUESTS: ErrorCode.TOO_MANY_REQUESTS,
        status.HTTP_500_INTERNAL_SERVER_ERROR: ErrorCode.INTERNAL_SERVER_ERROR,
        status.HTTP_502_BAD_GATEWAY: ErrorCode.REMOTE_API_ERROR,
        status.HTTP_503_SERVICE_UNAVAILABLE: ErrorCode.DATABASE_UNAVAILABLE,
        status.HTTP_504_GATEWAY_TIMEOUT: ErrorCode.REMOTE_API_TIMEOUT,
    }
    
    error_code = status_to_error_code.get(exc.status_code, ErrorCode.INTERNAL_SERVER_ERROR)
    
    # Handle detail as string or dict
    detail = exc.detail
    message = error_code.message
    
    if isinstance(detail, str):
        message = detail
    elif isinstance(detail, dict):
        message = detail.get("message", error_code.message)
    
    logger.warning(
        f"HTTPException: {exc.status_code} - {message}",
        extra={"path": request.url.path}
    )
    
    response_data = {
        "success": False,
        "error_code": error_code.code,
        "message": message,
        "message_en": error_code.message_en,
        "timestamp": datetime.utcnow().isoformat(),
        "path": str(request.url.path)
    }
    
    if isinstance(detail, dict) and "errors" in detail:
        response_data["errors"] = detail["errors"]
    
    return JSONResponse(
        status_code=exc.status_code,
        content=response_data
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Global handler for RequestValidationError.
    
    Converts Pydantic validation errors to standardized format.
    """
    from datetime import datetime
    
    errors = []
    for error in exc.errors():
        field = ".".join(str(loc) for loc in error["loc"])
        errors.append({
            "field": field,
            "message": error["msg"],
            "code": error.get("type", "validation_error")
        })
    
    logger.warning(
        f"ValidationError: {len(errors)} validation errors",
        extra={"path": request.url.path, "errors": errors}
    )
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "error_code": ErrorCode.VALIDATION_ERROR.code,
            "message": ErrorCode.VALIDATION_ERROR.message,
            "message_en": ErrorCode.VALIDATION_ERROR.message_en,
            "errors": errors,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url.path)
        }
    )


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Global handler for unhandled exceptions.
    
    Catches all unhandled exceptions and returns a standardized 500 response.
    """
    from datetime import datetime
    
    logger.exception(
        f"Unhandled exception: {type(exc).__name__} - {str(exc)}",
        extra={"path": request.url.path}
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error_code": ErrorCode.INTERNAL_SERVER_ERROR.code,
            "message": ErrorCode.INTERNAL_SERVER_ERROR.message,
            "message_en": ErrorCode.INTERNAL_SERVER_ERROR.message_en,
            "detail": str(exc) if logger.level <= logging.DEBUG else None,
            "timestamp": datetime.utcnow().isoformat(),
            "path": str(request.url.path)
        }
    )


# ==================== Helper Functions ====================

def raise_not_found(
    resource_type: str,
    resource_id: Any,
    error_code: Optional[ErrorCode] = None
) -> None:
    """
    Helper to raise a not found exception.
    
    Usage:
        raise_not_found("Article", article_id)
        raise_not_found("AI Model", model_id, ErrorCode.AI_MODEL_NOT_FOUND)
    """
    code = error_code or ErrorCode.NOT_FOUND
    raise AppException(
        code,
        message=f"{resource_type} {resource_id} 不存在",
        message_en=f"{resource_type} {resource_id} not found",
        detail={f"{resource_type.lower()}_id": resource_id}
    )


def raise_db_unavailable(db_name: str) -> None:
    """
    Helper to raise a database unavailable exception.
    
    Usage:
        raise_db_unavailable("Paprika")
        raise_db_unavailable("Maya-v2")
    """
    raise AppException(
        ErrorCode.DATABASE_UNAVAILABLE,
        message=f"{db_name} 資料庫不可用",
        message_en=f"{db_name} database not available",
        detail={"database": db_name}
    )


def raise_validation_error(
    field: str,
    message: str,
    message_en: Optional[str] = None
) -> None:
    """
    Helper to raise a validation error.
    
    Usage:
        raise_validation_error("file_path", "此路徑的文章已存在")
    """
    raise AppException(
        ErrorCode.VALIDATION_ERROR,
        errors=[{
            "field": field,
            "message": message,
            "message_en": message_en or message
        }]
    )


def raise_already_exists(
    resource_type: str,
    field: str,
    value: Any
) -> None:
    """
    Helper to raise an already exists exception.
    
    Usage:
        raise_already_exists("Article", "file_path", "/path/to/article.md")
    """
    raise AppException(
        ErrorCode.CONFLICT if resource_type != "Article" else ErrorCode.ARTICLE_ALREADY_EXISTS,
        message=f"{resource_type} 已存在（{field}: {value}）",
        message_en=f"{resource_type} already exists ({field}: {value})",
        detail={field: value}
    )


def raise_operation_failed(
    operation: str,
    error_code: ErrorCode,
    original_error: Optional[Exception] = None
) -> None:
    """
    Helper to raise an operation failed exception.
    
    Usage:
        raise_operation_failed("建立文章", ErrorCode.ARTICLE_CREATE_FAILED, e)
    """
    detail = None
    if original_error:
        detail = {"error": str(original_error)}
    
    raise AppException(
        error_code,
        message=f"{operation}失敗",
        message_en=f"Failed to {operation}",
        detail=detail
    )


def raise_remote_api_error(
    url: str,
    original_error: Optional[Exception] = None
) -> None:
    """
    Helper to raise a remote API error.
    
    Usage:
        raise_remote_api_error("https://api.example.com/articles", e)
    """
    raise AppException(
        ErrorCode.REMOTE_API_UNAVAILABLE,
        message=f"無法連接到遠端 API: {url}",
        message_en=f"Cannot connect to remote API: {url}",
        detail={
            "url": url,
            "error": str(original_error) if original_error else None
        }
    )


# ==================== Register Exception Handlers ====================

def register_exception_handlers(app) -> None:
    """
    Register all exception handlers with the FastAPI app.
    
    Usage:
        from maya_sawa.core.errors import register_exception_handlers
        register_exception_handlers(app)
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    logger.info("Exception handlers registered successfully")

