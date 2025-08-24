#!/usr/bin/env python3
"""
測試 Redis 連接腳本

這個腳本用於測試本地 Redis 連接是否正常。
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

def test_redis_connection():
    """測試 Redis 連接"""
    try:
        from maya_sawa.core.connection_pool import get_pool_manager
        
        logger.info("=== Redis 連接測試 ===")
        
        # 獲取連接池管理器
        pool_manager = get_pool_manager()
        
        # 獲取 Redis 連接
        redis_client = redis.Redis(connection_pool=pool_manager.redis_pool)
        
        # 測試連接
        logger.info("測試 Redis ping...")
        response = redis_client.ping()
        logger.info(f"Redis ping 回應: {response}")
        
        if response:
            logger.info("✅ Redis 連接成功！")
            
            # 測試基本操作
            logger.info("測試基本 Redis 操作...")
            
            # 設置測試鍵值
            test_key = "test:maya_sawa:connection"
            test_value = "Hello Redis!"
            redis_client.set(test_key, test_value)
            logger.info(f"設置鍵值: {test_key} = {test_value}")
            
            # 獲取測試鍵值
            retrieved_value = redis_client.get(test_key)
            logger.info(f"獲取鍵值: {test_key} = {retrieved_value}")
            
            # 刪除測試鍵值
            redis_client.delete(test_key)
            logger.info(f"刪除測試鍵值: {test_key}")
            
            # 檢查連接池狀態
            status = pool_manager.get_pool_status()
            logger.info(f"Redis 連接池狀態: {status['redis']}")
            
            logger.info("✅ Redis 基本操作測試完成")
            return True
        else:
            logger.error("❌ Redis ping 失敗")
            return False
            
    except Exception as e:
        logger.error(f"❌ Redis 連接測試失敗: {str(e)}")
        return False

def test_chat_history_manager():
    """測試 ChatHistoryManager"""
    try:
        from maya_sawa.core.chat_history import ChatHistoryManager
        
        logger.info("\n=== ChatHistoryManager 測試 ===")
        
        # 創建 ChatHistoryManager 實例
        chat_manager = ChatHistoryManager()
        logger.info("✅ ChatHistoryManager 初始化成功")
        
        # 測試保存對話
        test_user_id = "test_user"
        test_message = "Hello, this is a test message"
        test_answer = "Hello! This is a test response"
        
        success = chat_manager.save_conversation(
            user_message=test_message,
            ai_answer=test_answer,
            user_id=test_user_id
        )
        
        if success:
            logger.info("✅ 對話保存成功")
            
            # 測試獲取對話歷史
            history = chat_manager.get_conversation_history(test_user_id)
            logger.info(f"對話歷史記錄數: {len(history)}")
            
            if history:
                latest_conversation = history[-1]
                logger.info(f"最新對話: {latest_conversation['user_message']} -> {latest_conversation['ai_answer']}")
            
            logger.info("✅ ChatHistoryManager 測試完成")
            return True
        else:
            logger.error("❌ 對話保存失敗")
            return False
            
    except Exception as e:
        logger.error(f"❌ ChatHistoryManager 測試失敗: {str(e)}")
        return False

if __name__ == "__main__":
    import redis
    
    logger.info("開始 Redis 連接測試...")
    
    # 測試基本 Redis 連接
    redis_success = test_redis_connection()
    
    # 測試 ChatHistoryManager
    chat_success = test_chat_history_manager()
    
    if redis_success and chat_success:
        logger.info("\n🎉 所有 Redis 測試通過！")
        sys.exit(0)
    else:
        logger.error("\n❌ 部分 Redis 測試失敗")
        sys.exit(1)
