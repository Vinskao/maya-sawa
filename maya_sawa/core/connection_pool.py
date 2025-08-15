"""
Markdown Q&A System - 連接池管理模組

這個模組實現了數據庫連接池管理功能，負責：
1. PostgreSQL 連接池管理
2. Redis 連接池管理
3. 連接資源優化
4. 並發性能提升
5. 連接生命週期管理

主要功能：
- 多數據庫連接池支持
- 連接資源復用
- 並發連接管理
- 自動連接清理
- 錯誤處理和重試

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import logging
import os
from typing import Optional

# 第三方庫導入
import psycopg2
from psycopg2 import pool
import redis
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

# 本地模組導入
from .config import Config

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class ConnectionPoolManager:
    """
    連接池管理器
    
    負責管理 PostgreSQL 和 Redis 的連接池，提供：
    - 連接池初始化
    - 連接獲取和歸還
    - 資源清理
    - 錯誤處理
    """
    
    def __init__(self):
        """
        初始化連接池管理器
        
        創建 PostgreSQL 和 Redis 連接池，設置連接參數
        """
        # PostgreSQL 連接池
        self.postgres_pool = None
        self._init_postgres_pool()
        
        # Redis 連接池
        self.redis_pool = None
        self._init_redis_pool()
    
    def _init_postgres_pool(self):
        """
        初始化 PostgreSQL 連接池
        
        創建 PostgreSQL 線程連接池，設置最小和最大連接數，
        優化並發性能
        """
        try:
            # 從 Config 獲取連接字符串
            connection_string = Config.DB_CONNECTION_STRING
            
            # 創建線程連接池
            self.postgres_pool = pool.ThreadedConnectionPool(
                minconn=1,      # 最小連接數 (減少以避免連接限制)
                maxconn=5,      # 最大連接數 (減少以避免連接限制)
                dsn=connection_string  # 連接字符串
            )
            
            logger.info("PostgreSQL connection pool initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {str(e)}")
            raise
    
    def _init_redis_pool(self):
        """
        初始化 Redis 連接池
        
        創建 Redis 連接池，設置連接參數，
        支持密碼認證和自動解碼
        """
        try:
            # 從環境變數獲取 Redis 配置
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_CUSTOM_PORT", 6379))
            redis_password = os.getenv("REDIS_PASSWORD")
            
            # 創建 Redis 連接池
            self.redis_pool = redis.ConnectionPool(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                max_connections=5,   # 最大連接數 (減少以避免連接限制)
                decode_responses=True  # 自動解碼為字符串
            )
            
            logger.info("Redis connection pool initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis pool: {str(e)}")
            raise
    
    def get_postgres_connection(self):
        """
        獲取 PostgreSQL 連接
        
        從連接池中獲取一個可用的 PostgreSQL 連接
        
        Returns:
            psycopg2.extensions.connection: PostgreSQL 連接對象，如果池未初始化則返回 None
        """
        if self.postgres_pool:
            return self.postgres_pool.getconn()
        return None
    
    def return_postgres_connection(self, conn):
        """
        歸還 PostgreSQL 連接
        
        將使用完畢的 PostgreSQL 連接歸還到連接池，
        供其他線程使用
        
        Args:
            conn: PostgreSQL 連接對象
        """
        if self.postgres_pool and conn:
            self.postgres_pool.putconn(conn)
    
    def get_redis_connection(self):
        """
        獲取 Redis 連接
        
        從連接池中獲取一個可用的 Redis 連接
        
        Returns:
            redis.Redis: Redis 連接對象，如果池未初始化則返回 None
        """
        if self.redis_pool:
            return redis.Redis(connection_pool=self.redis_pool)
        return None
    
    def close_all(self):
        """
        關閉所有連接池
        
        安全地關閉所有連接池，釋放系統資源，
        通常在應用程式關閉時調用
        """
        if self.postgres_pool:
            # 關閉 PostgreSQL 連接池
            self.postgres_pool.closeall()
            logger.info("PostgreSQL connection pool closed")
        
        if self.redis_pool:
            # Redis 連接池會自動管理，記錄關閉信息
            logger.info("Redis connection pool closed")

# ==================== 全局連接池管理器 ====================
# 全局連接池管理器實例（懶加載模式）
_pool_manager = None

def get_pool_manager():
    """
    獲取連接池管理器（懶加載）
    
    使用單例模式管理全局連接池管理器，
    確保整個應用程式使用同一個連接池實例
    
    Returns:
        ConnectionPoolManager: 連接池管理器實例
    """
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = ConnectionPoolManager()
    return _pool_manager 