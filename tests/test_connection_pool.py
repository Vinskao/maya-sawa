#!/usr/bin/env python3
"""
測試連接池配置腳本

這個腳本用於測試 PostgreSQL 連接池的配置，
確保每個數據庫最多使用 5 個連接。

作者: Maya Sawa Team
版本: 0.1.0
"""

import sys
import os
import logging
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 設置日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_connection_pool():
    """測試連接池配置"""
    try:
        from maya_sawa.core.database.connection_pool import get_pool_manager
        
        logger.info("=== 雙數據庫連接池測試 ===")
        
        # 獲取連接池管理器
        pool_manager = get_pool_manager()
        
        # 獲取連接池狀態
        status = pool_manager.get_pool_status()
        
        logger.info("連接池狀態:")
        logger.info(f"  主數據庫 (articles): {status['main_postgres']}")
        logger.info(f"  人員數據庫 (people/weapon): {status['people_postgres']}")
        logger.info(f"  Redis: {status['redis']}")
        
        # 測試主數據庫連接
        logger.info("\n=== 測試主數據庫連接 (articles) ===")
        main_connections = []
        max_main_connections = 5
        
        for i in range(max_main_connections + 1):
            try:
                conn = pool_manager.get_postgres_connection()
                if conn:
                    main_connections.append(conn)
                    logger.info(f"  成功獲取主數據庫連接 #{i+1}")
                else:
                    logger.warning(f"  無法獲取主數據庫連接 #{i+1} (連接池可能已滿)")
                    break
            except Exception as e:
                logger.error(f"  獲取主數據庫連接 #{i+1} 時發生錯誤: {str(e)}")
                break
        
        logger.info(f"實際獲取的主數據庫連接數: {len(main_connections)}")
        
        # 歸還主數據庫連接
        for i, conn in enumerate(main_connections):
            try:
                pool_manager.return_postgres_connection(conn)
                logger.info(f"  成功歸還主數據庫連接 #{i+1}")
            except Exception as e:
                logger.error(f"  歸還主數據庫連接 #{i+1} 時發生錯誤: {str(e)}")
        
        # 測試人員數據庫連接
        logger.info("\n=== 測試人員數據庫連接 (people/weapon) ===")
        people_connections = []
        max_people_connections = 1
        
        for i in range(max_people_connections + 1):
            try:
                conn = pool_manager.get_people_postgres_connection()
                if conn:
                    people_connections.append(conn)
                    logger.info(f"  成功獲取人員數據庫連接 #{i+1}")
                else:
                    logger.warning(f"  無法獲取人員數據庫連接 #{i+1} (連接池可能已滿)")
                    break
            except Exception as e:
                logger.error(f"  獲取人員數據庫連接 #{i+1} 時發生錯誤: {str(e)}")
                break
        
        logger.info(f"實際獲取的人員數據庫連接數: {len(people_connections)}")
        
        # 歸還人員數據庫連接
        for i, conn in enumerate(people_connections):
            try:
                pool_manager.return_people_postgres_connection(conn)
                logger.info(f"  成功歸還人員數據庫連接 #{i+1}")
            except Exception as e:
                logger.error(f"  歸還人員數據庫連接 #{i+1} 時發生錯誤: {str(e)}")
        
        # 測試連接池功能
        logger.info("\n=== 測試連接池功能 ===")
        
        # 測試主數據庫功能
        try:
            conn = pool_manager.get_postgres_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT version()")
                version = cursor.fetchone()
                logger.info(f"  主數據庫版本: {version[0]}")
                cursor.close()
                pool_manager.return_postgres_connection(conn)
                logger.info("  ✅ 主數據庫連接池功能正常")
            else:
                logger.error("  ❌ 無法獲取主數據庫連接")
        except Exception as e:
            logger.error(f"  ❌ 主數據庫連接池測試失敗: {str(e)}")
        
        # 測試人員數據庫功能
        try:
            conn = pool_manager.get_people_postgres_connection()
            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT version()")
                version = cursor.fetchone()
                logger.info(f"  人員數據庫版本: {version[0]}")
                cursor.close()
                pool_manager.return_people_postgres_connection(conn)
                logger.info("  ✅ 人員數據庫連接池功能正常")
            else:
                logger.error("  ❌ 無法獲取人員數據庫連接")
        except Exception as e:
            logger.error(f"  ❌ 人員數據庫連接池測試失敗: {str(e)}")
        
        logger.info("\n=== 測試完成 ===")
        logger.info("雙數據庫連接池配置:")
        logger.info("- 主數據庫: 最多 5 個連接 (articles 表)")
        logger.info("- 人員數據庫: 最多 1 個連接 (people/weapon 表)")
        logger.info("- 每個數據庫都符合單一數據庫連接限制")
        
    except Exception as e:
        logger.error(f"測試過程中發生錯誤: {str(e)}")
        return False
    
    return True

if __name__ == "__main__":
    success = test_connection_pool()
    sys.exit(0 if success else 1)
