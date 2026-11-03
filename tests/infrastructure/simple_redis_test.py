#!/usr/bin/env python3
"""
簡單的 Redis 連接測試
"""

import os
import redis
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

def test_redis():
    """測試 Redis 連接"""
    try:
        # 從環境變數獲取 Redis 配置
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_CUSTOM_PORT", 6379))
        redis_password = os.getenv("REDIS_PASSWORD")
        
        print(f"嘗試連接到 Redis: {redis_host}:{redis_port}")
        
        # 創建 Redis 連接
        r = redis.Redis(
            host=redis_host,
            port=redis_port,
            password=redis_password,
            decode_responses=True
        )
        
        # 測試連接
        response = r.ping()
        print(f"Redis ping 回應: {response}")
        
        if response:
            print("✅ Redis 連接成功！")
            
            # 測試基本操作
            test_key = "test:maya_sawa"
            test_value = "Hello Redis!"
            
            # 設置值
            r.set(test_key, test_value)
            print(f"設置: {test_key} = {test_value}")
            
            # 獲取值
            retrieved = r.get(test_key)
            print(f"獲取: {test_key} = {retrieved}")
            
            # 刪除測試鍵
            r.delete(test_key)
            print(f"刪除測試鍵: {test_key}")
            
            print("✅ Redis 基本操作測試完成")
            return True
        else:
            print("❌ Redis ping 失敗")
            return False
            
    except Exception as e:
        print(f"❌ Redis 連接失敗: {str(e)}")
        return False

if __name__ == "__main__":
    print("=== Redis 連接測試 ===")
    success = test_redis()
    
    if success:
        print("\n🎉 Redis 測試通過！")
    else:
        print("\n❌ Redis 測試失敗")
