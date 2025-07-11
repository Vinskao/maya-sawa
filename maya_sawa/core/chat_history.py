"""
Markdown Q&A System - 對話歷史管理模組

這個模組實現了基於 Redis 的對話歷史管理功能，負責：
1. 儲存用戶與 AI 的對話記錄
2. 檢索和查詢對話歷史
3. 提供對話統計信息
4. 管理多用戶對話數據
5. 支持對話記錄的過期清理

主要功能：
- Redis 數據庫集成
- 多用戶對話隔離
- 對話記錄序列化
- 統計信息收集
- 自動過期管理

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# 第三方庫導入
import redis

# 環境變數導入
import os

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class ChatHistoryManager:
    """
    對話歷史管理器
    
    負責管理用戶與 AI 系統的對話記錄，包括：
    - 對話記錄的儲存和檢索
    - 多用戶數據隔離
    - 統計信息收集
    - 過期數據清理
    """
    
    def __init__(self):
        """
        初始化對話歷史管理器
        
        設置 Redis 連接配置並測試連接
        """
        # 從環境變數獲取 Redis 配置
        self.redis_host = os.getenv("REDIS_HOST", "localhost")
        self.redis_port = int(os.getenv("REDIS_CUSTOM_PORT", 6379))
        self.redis_password = os.getenv("REDIS_PASSWORD")
        self.redis_db = 0  # 使用默認數據庫
        
        # 初始化 Redis 連接
        self.redis_client = redis.Redis(
            host=self.redis_host,
            port=self.redis_port,
            password=self.redis_password,
            db=self.redis_db,
            decode_responses=True  # 自動解碼為字符串
        )
        
        # 測試連接
        self._test_connection()

    def _test_connection(self):
        """
        測試 Redis 連接
        
        驗證 Redis 連接是否正常，確保應用程式啟動時能正常連接到 Redis
        """
        try:
            self.redis_client.ping()
            logger.info("Successfully connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            raise

    def _get_chat_key(self, user_id: str = "default") -> str:
        """
        生成聊天記錄的 Redis key
        
        為每個用戶生成唯一的 Redis key，確保多用戶數據隔離
        
        Args:
            user_id (str): 用戶 ID，默認為 "default"
            
        Returns:
            str: Redis key 字符串
        """
        return f"chat:user:{user_id}:ai:qa_system"

    def save_conversation(self, 
                         user_message: str, 
                         ai_answer: str, 
                         user_id: str = "default",
                         reference_data: List[Dict[str, Any]] = None,
                         ttl_seconds: int = 3600) -> bool:
        """
        儲存對話記錄
        
        Args:
            user_message: 用戶問題
            ai_answer: AI 回答
            user_id: 用戶 ID（預設為 "default"）
            reference_data: 參考文章信息列表
            ttl_seconds: 過期時間（秒），預設 1 小時
            
        Returns:
            bool: 是否成功儲存
        """
        try:
            chat_key = self._get_chat_key(user_id)
            timestamp = datetime.utcnow().isoformat() + "Z"
            
            # 創建對話記錄
            conversation = {
                "user_message": user_message,
                "ai_answer": ai_answer,
                "timestamp": timestamp,
                "user_id": user_id,
                "reference_data": reference_data or []  # 添加參考文章信息
            }
            
            # 推入 Redis List
            self.redis_client.rpush(chat_key, json.dumps(conversation, ensure_ascii=False))
            
            # 設置 TTL（過期時間）
            self.redis_client.expire(chat_key, ttl_seconds)
            
            logger.info(f"Saved conversation for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save conversation: {str(e)}")
            return False

    def get_conversation_history(self, 
                                user_id: str = "default", 
                                limit: int = 50) -> List[Dict[str, Any]]:
        """
        獲取對話歷史記錄
        
        Args:
            user_id: 用戶 ID
            limit: 返回記錄數量限制
            
        Returns:
            List[Dict]: 對話記錄列表
        """
        try:
            chat_key = self._get_chat_key(user_id)
            
            # 獲取所有記錄（從最早到最新）
            raw_history = self.redis_client.lrange(chat_key, 0, limit - 1)
            
            # 解析 JSON 並按時間排序
            history = []
            for record in raw_history:
                try:
                    conversation = json.loads(record)
                    history.append(conversation)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to decode conversation record: {e}")
                    continue
            
            # 按時間戳排序（最新的在前）
            history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
            
            return history
            
        except Exception as e:
            logger.error(f"Failed to get conversation history: {str(e)}")
            return []

    def get_conversation_stats(self, user_id: str = "default") -> Dict[str, Any]:
        """
        獲取對話統計資訊
        
        Args:
            user_id: 用戶 ID
            
        Returns:
            Dict: 統計資訊
        """
        try:
            chat_key = self._get_chat_key(user_id)
            
            # 獲取列表長度
            total_messages = self.redis_client.llen(chat_key)
            
            # 獲取 TTL
            ttl = self.redis_client.ttl(chat_key)
            
            return {
                "user_id": user_id,
                "total_conversations": total_messages,
                "ttl_seconds": ttl if ttl > 0 else None,
                "chat_key": chat_key
            }
            
        except Exception as e:
            logger.error(f"Failed to get conversation stats: {str(e)}")
            return {
                "user_id": user_id,
                "total_conversations": 0,
                "ttl_seconds": None,
                "chat_key": None,
                "error": str(e)
            }

    def clear_conversation_history(self, user_id: str = "default") -> bool:
        """
        清除對話歷史記錄
        
        Args:
            user_id: 用戶 ID
            
        Returns:
            bool: 是否成功清除
        """
        try:
            chat_key = self._get_chat_key(user_id)
            self.redis_client.delete(chat_key)
            logger.info(f"Cleared conversation history for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to clear conversation history: {str(e)}")
            return False

    def get_all_users(self) -> List[str]:
        """
        獲取所有有對話記錄的用戶 ID
        
        Returns:
            List[str]: 用戶 ID 列表
        """
        try:
            # 搜尋所有聊天記錄的 key
            pattern = "chat:user:*:ai:qa_system"
            keys = self.redis_client.keys(pattern)
            
            # 提取用戶 ID
            user_ids = []
            for key in keys:
                # 從 "chat:user:123:ai:qa_system" 提取 "123"
                parts = key.split(":")
                if len(parts) >= 3:
                    user_ids.append(parts[2])
            
            return list(set(user_ids))  # 去重
            
        except Exception as e:
            logger.error(f"Failed to get all users: {str(e)}")
            return [] 