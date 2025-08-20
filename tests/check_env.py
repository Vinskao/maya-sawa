#!/usr/bin/env python3
"""
檢查環境變數配置腳本

這個腳本用於檢查雙數據庫的環境變數配置是否正確。

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

def check_environment_variables():
    """檢查環境變數配置"""
    print("=== 環境變數配置檢查 ===")
    
    # 主數據庫配置
    print("\n--- 主數據庫配置 (articles 表) ---")
    main_db_vars = {
        "DB_HOST": os.getenv("DB_HOST"),
        "DB_PORT": os.getenv("DB_PORT"),
        "DB_DATABASE": os.getenv("DB_DATABASE"),
        "DB_USERNAME": os.getenv("DB_USERNAME"),
        "DB_PASSWORD": os.getenv("DB_PASSWORD"),
        "DB_SSLMODE": os.getenv("DB_SSLMODE")
    }
    
    for var_name, var_value in main_db_vars.items():
        if var_value:
            print(f"✅ {var_name}: {var_value[:10]}..." if len(str(var_value)) > 10 else f"✅ {var_name}: {var_value}")
        else:
            print(f"❌ {var_name}: 未設置")
    
    # 人員數據庫配置
    print("\n--- 人員數據庫配置 (people/weapon 表) ---")
    people_db_vars = {
        "PEOPLE_DB_HOST": os.getenv("PEOPLE_DB_HOST"),
        "PEOPLE_DB_PORT": os.getenv("PEOPLE_DB_PORT"),
        "PEOPLE_DB_DATABASE": os.getenv("PEOPLE_DB_DATABASE"),
        "PEOPLE_DB_USERNAME": os.getenv("PEOPLE_DB_USERNAME"),
        "PEOPLE_DB_PASSWORD": os.getenv("PEOPLE_DB_PASSWORD"),
        "PEOPLE_DB_SSLMODE": os.getenv("PEOPLE_DB_SSLMODE")
    }
    
    for var_name, var_value in people_db_vars.items():
        if var_value:
            print(f"✅ {var_name}: {var_value[:10]}..." if len(str(var_value)) > 10 else f"✅ {var_name}: {var_value}")
        else:
            print(f"❌ {var_name}: 未設置")
    
    # 檢查配置完整性
    print("\n--- 配置完整性檢查 ---")
    
    # 檢查主數據庫
    main_db_complete = all([main_db_vars["DB_HOST"], main_db_vars["DB_DATABASE"], 
                           main_db_vars["DB_USERNAME"], main_db_vars["DB_PASSWORD"]])
    if main_db_complete:
        print("✅ 主數據庫配置完整")
    else:
        print("❌ 主數據庫配置不完整")
    
    # 檢查人員數據庫
    people_db_complete = all([people_db_vars["PEOPLE_DB_HOST"], people_db_vars["PEOPLE_DB_DATABASE"], 
                             people_db_vars["PEOPLE_DB_USERNAME"], people_db_vars["PEOPLE_DB_PASSWORD"]])
    if people_db_complete:
        print("✅ 人員數據庫配置完整")
    else:
        print("❌ 人員數據庫配置不完整")
    
    # 檢查 OpenAI 配置
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        print("✅ OpenAI API Key 已設置")
    else:
        print("❌ OpenAI API Key 未設置")
    
    return main_db_complete and people_db_complete and openai_key is not None

if __name__ == "__main__":
    success = check_environment_variables()
    sys.exit(0 if success else 1)
