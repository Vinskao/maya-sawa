"""
數據庫連接模組
"""

from .connection_pool import get_pool_manager

__all__ = ['get_pool_manager']