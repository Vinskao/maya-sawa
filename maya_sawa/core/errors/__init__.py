"""
錯誤處理模組
"""

from .errors import (
    ErrorCode,
    AppException,
    ErrorResponse,
    ErrorDetail,
    register_exception_handlers,
    raise_not_found,
    raise_db_unavailable,
    raise_validation_error,
    raise_already_exists,
    raise_operation_failed,
    raise_remote_api_error,
)

__all__ = [
    'ErrorCode',
    'AppException',
    'ErrorResponse',
    'ErrorDetail',
    'register_exception_handlers',
    'raise_not_found',
    'raise_db_unavailable',
    'raise_validation_error',
    'raise_already_exists',
    'raise_operation_failed',
    'raise_remote_api_error',
]
