import psycopg2
from psycopg2 import pool
import redis
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

class ConnectionPoolManager:
    """連接池管理器，優化並發性能"""
    
    def __init__(self):
        # PostgreSQL 連接池
        self.postgres_pool = None
        self._init_postgres_pool()
        
        # Redis 連接池
        self.redis_pool = None
        self._init_redis_pool()
    
    def _init_postgres_pool(self):
        """初始化 PostgreSQL 連接池"""
        try:
            connection_string = os.getenv("POSTGRES_CONNECTION_STRING")
            
            # 創建連接池
            self.postgres_pool = pool.ThreadedConnectionPool(
                minconn=5,      # 最小連接數
                maxconn=20,     # 最大連接數
                dsn=connection_string
            )
            
            logger.info("PostgreSQL connection pool initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL pool: {str(e)}")
            raise
    
    def _init_redis_pool(self):
        """初始化 Redis 連接池"""
        try:
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_CUSTOM_PORT", 6379))
            redis_password = os.getenv("REDIS_PASSWORD")
            
            # 創建 Redis 連接池
            self.redis_pool = redis.ConnectionPool(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                max_connections=20,  # 最大連接數
                decode_responses=True
            )
            
            logger.info("Redis connection pool initialized")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis pool: {str(e)}")
            raise
    
    def get_postgres_connection(self):
        """獲取 PostgreSQL 連接"""
        if self.postgres_pool:
            return self.postgres_pool.getconn()
        return None
    
    def return_postgres_connection(self, conn):
        """歸還 PostgreSQL 連接"""
        if self.postgres_pool and conn:
            self.postgres_pool.putconn(conn)
    
    def get_redis_connection(self):
        """獲取 Redis 連接"""
        if self.redis_pool:
            return redis.Redis(connection_pool=self.redis_pool)
        return None
    
    def close_all(self):
        """關閉所有連接池"""
        if self.postgres_pool:
            self.postgres_pool.closeall()
            logger.info("PostgreSQL connection pool closed")
        
        if self.redis_pool:
            # Redis 連接池會自動管理
            logger.info("Redis connection pool closed")

# 全局連接池管理器
_pool_manager = None

def get_pool_manager():
    """獲取連接池管理器（懶加載）"""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = ConnectionPoolManager()
    return _pool_manager 