#!/usr/bin/env python3
"""
快速測試連接池配置

這個腳本用於快速驗證連接池配置是否正確。
"""

import sys
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def quick_test():
    """快速測試連接池配置"""
    try:
        from maya_sawa.core.connection_pool import get_pool_manager
        
        print("=== 快速連接池配置測試 ===")
        
        # 獲取連接池管理器
        pool_manager = get_pool_manager()
        
        # 獲取連接池狀態
        status = pool_manager.get_pool_status()
        
        print("連接池狀態:")
        print(f"  主數據庫: {status['main_postgres']['max_connections']} 個連接")
        print(f"  人員數據庫: {status['people_postgres']['max_connections']} 個連接")
        
        # 測試獲取連接
        print("\n測試獲取連接...")
        
        # 測試主數據庫
        main_conn = pool_manager.get_postgres_connection()
        if main_conn:
            print("✅ 主數據庫連接成功")
            pool_manager.return_postgres_connection(main_conn)
        else:
            print("❌ 主數據庫連接失敗")
        
        # 測試人員數據庫
        people_conn = pool_manager.get_people_postgres_connection()
        if people_conn:
            print("✅ 人員數據庫連接成功")
            pool_manager.return_people_postgres_connection(people_conn)
        else:
            print("❌ 人員數據庫連接失敗")
        
        print("\n✅ 連接池配置測試完成")
        return True
        
    except Exception as e:
        print(f"❌ 測試失敗: {str(e)}")
        return False

if __name__ == "__main__":
    success = quick_test()
    sys.exit(0 if success else 1)
