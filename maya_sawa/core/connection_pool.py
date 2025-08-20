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
from typing import Optional, Dict, Any

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
    - 主數據庫連接池（用於 articles 表）
    - 人員數據庫連接池（用於 people 和 weapon 表）
    - Redis 連接池
    - 連接獲取和歸還
    - 資源清理
    - 錯誤處理
    """
    
    def __init__(self):
        """
        初始化連接池管理器
        
        創建主數據庫、人員數據庫和 Redis 連接池，設置連接參數
        """
        # 主數據庫連接池（用於 articles 表）
        self.postgres_pool = None
        self._init_main_postgres_pool()
        
        # 人員數據庫連接池（用於 people 和 weapon 表）
        self.people_postgres_pool = None
        self._init_people_postgres_pool()
        
        # Redis 連接池
        self.redis_pool = None
        self._init_redis_pool()
    
    def _init_main_postgres_pool(self):
        """
        初始化主 PostgreSQL 連接池
        
        創建主數據庫的線程連接池，設置最小和最大連接數，
        優化並發性能
        """
        try:
            # 從 Config 獲取主數據庫連接字符串
            connection_string = Config.DB_CONNECTION_STRING
            
            if connection_string:
                # 創建線程連接池
                self.postgres_pool = pool.ThreadedConnectionPool(
                    minconn=1,      # 最小連接數
                    maxconn=5,      # 最大連接數 (每個數據庫最多 5 個連接)
                    dsn=connection_string  # 連接字符串
                )
                logger.info("Main PostgreSQL connection pool initialized")
            else:
                logger.warning("Main database connection string not available")
                
        except Exception as e:
            logger.error(f"Failed to initialize main PostgreSQL pool: {str(e)}")
            raise
    
    def _init_people_postgres_pool(self):
        """
        初始化人員 PostgreSQL 連接池
        
        創建人員數據庫的線程連接池，設置最小和最大連接數，
        優化並發性能
        """
        try:
            # 從 Config 獲取人員數據庫連接字符串
            connection_string = Config.PEOPLE_DB_CONNECTION_STRING
            
            if connection_string:
                # 創建線程連接池
                self.people_postgres_pool = pool.ThreadedConnectionPool(
                    minconn=1,      # 最小連接數
                    maxconn=5,      # 最大連接數 (每個數據庫最多 5 個連接)
                    dsn=connection_string  # 連接字符串
                )
                logger.info("People PostgreSQL connection pool initialized")
            else:
                logger.warning("People database connection string not available")
                
        except Exception as e:
            logger.error(f"Failed to initialize people PostgreSQL pool: {str(e)}")
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
        獲取主 PostgreSQL 連接（用於 articles 表）
        
        從主數據庫連接池中獲取一個可用的 PostgreSQL 連接
        
        Returns:
            psycopg2.extensions.connection: PostgreSQL 連接對象，如果池未初始化則返回 None
        """
        if self.postgres_pool:
            return self.postgres_pool.getconn()
        return None
    
    def return_postgres_connection(self, conn):
        """
        歸還主 PostgreSQL 連接
        
        將使用完畢的主數據庫 PostgreSQL 連接歸還到連接池，
        供其他線程使用
        
        Args:
            conn: PostgreSQL 連接對象
        """
        if self.postgres_pool and conn:
            self.postgres_pool.putconn(conn)
    
    def get_people_postgres_connection(self):
        """
        獲取人員 PostgreSQL 連接（用於 people 和 weapon 表）
        
        從人員數據庫連接池中獲取一個可用的 PostgreSQL 連接
        
        Returns:
            psycopg2.extensions.connection: PostgreSQL 連接對象，如果池未初始化則返回 None
        """
        if self.people_postgres_pool:
            return self.people_postgres_pool.getconn()
        return None
    
    def return_people_postgres_connection(self, conn):
        """
        歸還人員 PostgreSQL 連接
        
        將使用完畢的人員數據庫 PostgreSQL 連接歸還到連接池，
        供其他線程使用
        
        Args:
            conn: PostgreSQL 連接對象
        """
        if self.people_postgres_pool and conn:
            self.people_postgres_pool.putconn(conn)
    
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
            # 關閉主 PostgreSQL 連接池
            self.postgres_pool.closeall()
            logger.info("Main PostgreSQL connection pool closed")
        
        if self.people_postgres_pool:
            # 關閉人員 PostgreSQL 連接池
            self.people_postgres_pool.closeall()
            logger.info("People PostgreSQL connection pool closed")
        
        if self.redis_pool:
            # Redis 連接池會自動管理，記錄關閉信息
            logger.info("Redis connection pool closed")
    
    def get_pool_status(self) -> Dict[str, Any]:
        """
        獲取連接池狀態
        
        返回當前連接池的使用情況，用於監控和調試
        
        Returns:
            Dict[str, Any]: 包含連接池狀態的字典
        """
        status = {
            "main_postgres": {
                "pool_initialized": self.postgres_pool is not None,
                "max_connections": 5,
                "min_connections": 1,
                "purpose": "articles table"
            },
            "people_postgres": {
                "pool_initialized": self.people_postgres_pool is not None,
                "max_connections": 5,
                "min_connections": 1,
                "purpose": "people and weapon tables"
            },
            "redis": {
                "pool_initialized": self.redis_pool is not None,
                "max_connections": 5
            }
        }
        
        # 如果主 PostgreSQL 連接池已初始化，獲取詳細狀態
        if self.postgres_pool:
            try:
                status["main_postgres"]["pool_type"] = "ThreadedConnectionPool"
                status["main_postgres"]["status"] = "active"
            except Exception as e:
                status["main_postgres"]["status"] = f"error: {str(e)}"
        
        # 如果人員 PostgreSQL 連接池已初始化，獲取詳細狀態
        if self.people_postgres_pool:
            try:
                status["people_postgres"]["pool_type"] = "ThreadedConnectionPool"
                status["people_postgres"]["status"] = "active"
            except Exception as e:
                status["people_postgres"]["status"] = f"error: {str(e)}"
        
        return status

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