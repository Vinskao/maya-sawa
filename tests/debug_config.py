#!/usr/bin/env python3
"""
調試配置載入腳本

這個腳本用於調試配置載入過程，檢查為什麼會出現配置警告。

作者: Maya Sawa Team
版本: 0.1.0
"""

import os
import sys
from pathlib import Path

# 添加項目根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 載入環境變數
from dotenv import load_dotenv
load_dotenv()

def debug_config_loading():
    """調試配置載入過程"""
    print("=== 配置載入調試 ===")
    
    # 檢查環境變數是否已載入
    print("\n--- 環境變數檢查 ---")
    people_db_host = os.getenv("PEOPLE_DB_HOST")
    people_db_database = os.getenv("PEOPLE_DB_DATABASE")
    people_db_username = os.getenv("PEOPLE_DB_USERNAME")
    people_db_password = os.getenv("PEOPLE_DB_PASSWORD")
    
    print(f"PEOPLE_DB_HOST: {people_db_host}")
    print(f"PEOPLE_DB_DATABASE: {people_db_database}")
    print(f"PEOPLE_DB_USERNAME: {people_db_username}")
    print(f"PEOPLE_DB_PASSWORD: {'已設置' if people_db_password else '未設置'}")
    
    # 檢查配置類
    print("\n--- 配置類檢查 ---")
    from maya_sawa.core.config import Config
    
    print(f"PEOPLE_DB_HOST: {Config.PEOPLE_DB_HOST}")
    print(f"PEOPLE_DB_DATABASE: {Config.PEOPLE_DB_DATABASE}")
    print(f"PEOPLE_DB_USERNAME: {Config.PEOPLE_DB_USERNAME}")
    print(f"PEOPLE_DB_PASSWORD: {'已設置' if Config.PEOPLE_DB_PASSWORD else '未設置'}")
    print(f"PEOPLE_DB_CONNECTION_STRING: {'已設置' if Config.PEOPLE_DB_CONNECTION_STRING else '未設置'}")
    
    # 檢查配置驗證
    print("\n--- 配置驗證檢查 ---")
    missing_config = Config.validate_required_config()
    if missing_config:
        print(f"缺少的配置: {missing_config}")
    else:
        print("所有配置都完整")
    
    # 檢查連接字符串構建
    print("\n--- 連接字符串構建檢查 ---")
    if all([Config.PEOPLE_DB_HOST, Config.PEOPLE_DB_DATABASE, Config.PEOPLE_DB_USERNAME, Config.PEOPLE_DB_PASSWORD]):
        print("✅ 所有必要的人員數據庫配置都存在")
        expected_connection_string = f"postgresql://{Config.PEOPLE_DB_USERNAME}:{Config.PEOPLE_DB_PASSWORD}@{Config.PEOPLE_DB_HOST}:{Config.PEOPLE_DB_PORT}/{Config.PEOPLE_DB_DATABASE}?sslmode={Config.PEOPLE_DB_SSLMODE}"
        print(f"預期的連接字符串: {expected_connection_string[:50]}...")
    else:
        print("❌ 人員數據庫配置不完整")
        missing_vars = []
        if not Config.PEOPLE_DB_HOST:
            missing_vars.append("PEOPLE_DB_HOST")
        if not Config.PEOPLE_DB_DATABASE:
            missing_vars.append("PEOPLE_DB_DATABASE")
        if not Config.PEOPLE_DB_USERNAME:
            missing_vars.append("PEOPLE_DB_USERNAME")
        if not Config.PEOPLE_DB_PASSWORD:
            missing_vars.append("PEOPLE_DB_PASSWORD")
        print(f"缺少的變數: {missing_vars}")

if __name__ == "__main__":
    debug_config_loading()
