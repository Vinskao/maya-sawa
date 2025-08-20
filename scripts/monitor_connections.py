#!/usr/bin/env python3
"""
PostgreSQL 連接監控腳本

這個腳本用於監控 PostgreSQL 數據庫的連接使用情況，
確保不超過 Aiven Free Tier 的 20 連接限制。

作者: Maya Sawa Team
版本: 0.1.0
"""

import sys
import os
import logging
import psycopg2
from pathlib import Path
from datetime import datetime

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 設置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_connection_info():
    """獲取數據庫連接信息"""
    try:
        from maya_sawa.core.config import Config
        return Config.DB_CONNECTION_STRING
    except Exception as e:
        logger.error(f"無法獲取數據庫連接信息: {str(e)}")
        return None

def monitor_connections():
    """監控數據庫連接"""
    try:
        from maya_sawa.core.config import Config
        
        logger.info("=== 雙數據庫連接監控 ===")
        logger.info(f"監控時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 監控主數據庫
        if Config.DB_CONNECTION_STRING:
            logger.info("\n--- 主數據庫 (articles 表) ---")
            monitor_single_database(Config.DB_CONNECTION_STRING, "主數據庫")
        else:
            logger.warning("主數據庫連接字符串未配置")
        
        # 監控人員數據庫
        if Config.PEOPLE_DB_CONNECTION_STRING:
            logger.info("\n--- 人員數據庫 (people/weapon 表) ---")
            monitor_single_database(Config.PEOPLE_DB_CONNECTION_STRING, "人員數據庫")
        else:
            logger.warning("人員數據庫連接字符串未配置")
        
        return True
        
    except Exception as e:
        logger.error(f"監控過程中發生錯誤: {str(e)}")
        return False

def monitor_single_database(connection_string: str, db_name: str):
    """監控單個數據庫的連接"""
    try:
        # 連接到數據庫
        conn = psycopg2.connect(connection_string)
        cursor = conn.cursor()
        
        # 查詢當前連接數
        cursor.execute("""
            SELECT 
                count(*) as total_connections,
                count(*) FILTER (WHERE state = 'active') as active_connections,
                count(*) FILTER (WHERE state = 'idle') as idle_connections,
                count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
            FROM pg_stat_activity 
            WHERE datname = current_database()
        """)
        
        stats = cursor.fetchone()
        total, active, idle, idle_in_transaction = stats
        
        logger.info(f"{db_name}連接統計:")
        logger.info(f"  總連接數: {total}")
        logger.info(f"  活躍連接: {active}")
        logger.info(f"  空閒連接: {idle}")
        logger.info(f"  事務中空閒: {idle_in_transaction}")
        
        # 檢查是否超過限制
        max_connections = 20  # Aiven Free Tier 限制
        if total >= max_connections:
            logger.warning(f"⚠️  {db_name}連接數 ({total}) 已接近或達到限制 ({max_connections})")
        elif total >= max_connections * 0.8:
            logger.warning(f"⚠️  {db_name}連接數 ({total}) 已達到限制的 80% ({max_connections * 0.8})")
        else:
            logger.info(f"✅ {db_name}連接數 ({total}) 在安全範圍內")
        
        # 查詢詳細連接信息
        cursor.execute("""
            SELECT 
                pid,
                usename,
                application_name,
                client_addr,
                state,
                query_start,
                state_change
            FROM pg_stat_activity 
            WHERE datname = current_database()
            ORDER BY state, query_start DESC
        """)
        
        connections = cursor.fetchall()
        
        logger.info(f"{db_name}詳細連接信息 ({len(connections)} 個連接):")
        for conn_info in connections:
            pid, user, app, client, state, query_start, state_change = conn_info
            logger.info(f"  PID: {pid}, 用戶: {user}, 應用: {app}, 狀態: {state}")
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        logger.error(f"監控 {db_name} 時發生錯誤: {str(e)}")

if __name__ == "__main__":
    success = monitor_connections()
    sys.exit(0 if success else 1)
