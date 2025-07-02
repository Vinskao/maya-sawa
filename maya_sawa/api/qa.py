"""
Markdown Q&A System - API 路由模組

這個模組提供問答系統的核心 API 端點，包括：
1. 文章同步 API（從遠端 API 獲取文章）
2. 問答查詢 API（基於向量搜索的文檔問答）
3. 對話歷史管理 API（儲存和檢索用戶對話記錄）
4. 統計信息 API（文章和對話統計）

主要功能：
- 支持預計算 embedding 的文章同步
- 基於相似度搜索的文檔問答
- 多用戶對話歷史管理
- 實時統計信息查詢

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import os
import logging
import asyncio
from typing import List, Dict, Any

# 第三方庫導入
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import httpx

# LangChain 相關導入
from langchain.schema import Document

# 本地模組導入
from ..core.postgres_store import PostgresVectorStore
from ..core.qa_chain import QAChain
from ..core.chat_history import ChatHistoryManager

# ==================== 環境變數配置 ====================
# 從環境變數獲取公共 API 基礎 URL
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "")

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

# ==================== 懶加載實例管理 ====================
# 使用懶加載模式管理核心組件實例，避免啟動時的資源浪費
_vector_store = None
_qa_chain = None
_chat_history = None

def get_vector_store():
    """
    獲取向量存儲實例（懶加載模式）
    
    使用全局變數實現單例模式，確保整個應用程式使用同一個向量存儲實例
    
    Returns:
        PostgresVectorStore: 向量存儲實例
    """
    global _vector_store
    if _vector_store is None:
        _vector_store = PostgresVectorStore()
    return _vector_store

def get_qa_chain():
    """
    獲取問答鏈實例（懶加載模式）
    
    使用全局變數實現單例模式，確保整個應用程式使用同一個問答鏈實例
    
    Returns:
        QAChain: 問答鏈實例
    """
    global _qa_chain
    if _qa_chain is None:
        _qa_chain = QAChain()
    return _qa_chain

def get_chat_history():
    """
    獲取對話記錄管理實例（懶加載模式）
    
    使用全局變數實現單例模式，確保整個應用程式使用同一個對話記錄管理實例
    
    Returns:
        ChatHistoryManager: 對話記錄管理實例
    """
    global _chat_history
    if _chat_history is None:
        _chat_history = ChatHistoryManager()
    return _chat_history

# ==================== FastAPI 路由初始化 ====================
# 創建 API 路由器，設置前綴和標籤
router = APIRouter(prefix="/qa", tags=["Q&A"])

# ==================== 請求模型定義 ====================

class QueryRequest(BaseModel):
    """
    查詢請求模型
    
    定義用戶發送問答查詢時的請求格式
    """
    text: str  # 用戶的問題文本
    user_id: str = "default"  # 用戶 ID，預設為 "default"

class SyncRequest(BaseModel):
    """
    同步請求模型
    
    定義文章同步請求的格式
    """
    remote_url: str = None  # 遠端 API URL，可選

class SyncFromAPIRequest(BaseModel):
    """
    從 API 同步請求模型
    
    定義從遠端 API 同步文章的請求格式
    """
    remote_url: str = None  # 遠端 API URL，可選

# ==================== API 端點定義 ====================

@router.post("/sync-from-api")
async def sync_articles_from_api(request: SyncFromAPIRequest):
    """
    從遠端 API 同步文章並使用預計算的 embedding
    
    這個端點從指定的遠端 API 獲取文章數據，並使用預先計算好的 embedding
    進行存儲，避免在本地重新計算 embedding，提高同步效率。
    
    Args:
        request (SyncFromAPIRequest): 同步請求，包含遠端 API URL
        
    Returns:
        dict: 同步結果，包含成功狀態、消息、文章數量等
        
    Raises:
        HTTPException: 當同步失敗時拋出 HTTP 異常
    """
    try:
        # 使用預設 URL 如果沒有提供
        remote_url = request.remote_url or f"{PUBLIC_API_BASE_URL}/paprika/articles"
        
        # 從遠端 API 獲取文章數據
        async with httpx.AsyncClient() as client:
            response = await client.get(remote_url)
            response.raise_for_status()  # 檢查 HTTP 狀態碼
            data = response.json()
        
        # 檢查遠端 API 返回的狀態
        if not data.get("success"):
            raise HTTPException(status_code=400, detail="遠端 API 返回錯誤")
        
        # 提取文章列表
        articles = data.get("data", [])
        if not articles:
            return {"message": "沒有找到需要同步的文章", "count": 0}
        
        # 使用新的方法添加文章（使用預計算的 embedding）
        vector_store = get_vector_store()
        vector_store.add_articles_from_api(articles)
        
        # 返回同步結果
        return {
            "success": True,
            "message": f"成功同步 {len(articles)} 篇文章（使用預計算的 embedding）",
            "count": len(articles),
            "articles": [
                {
                    "id": article["id"],
                    "file_path": article["file_path"],
                    "content_length": len(article["content"]),
                    "has_embedding": "embedding" in article
                }
                for article in articles
            ]
        }
        
    except httpx.RequestError as e:
        # 處理網絡請求錯誤
        logger.error(f"請求遠端 API 失敗: {str(e)}")
        raise HTTPException(status_code=500, detail=f"無法連接到遠端 API: {str(e)}")
    except Exception as e:
        # 處理其他錯誤
        logger.error(f"同步文章時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失敗: {str(e)}")

@router.post("/sync-articles")
async def sync_articles_from_remote(request: SyncRequest):
    """
    從遠端 API 同步文章並生成 embedding（保留原有方法以向後兼容）
    
    這個端點從指定的遠端 API 獲取文章數據，並在本地生成 embedding。
    這是為了向後兼容而保留的方法，新版本建議使用 /sync-from-api 端點。
    
    Args:
        request (SyncRequest): 同步請求，包含遠端 API URL
        
    Returns:
        dict: 同步結果，包含成功狀態、消息、文章數量等
        
    Raises:
        HTTPException: 當同步失敗時拋出 HTTP 異常
    """
    try:
        # 使用預設 URL 如果沒有提供
        remote_url = request.remote_url or f"{PUBLIC_API_BASE_URL}/paprika/articles"
        
        # 從遠端 API 獲取文章數據
        async with httpx.AsyncClient() as client:
            response = await client.get(remote_url)
            response.raise_for_status()
            data = response.json()
        
        # 檢查遠端 API 返回的狀態
        if not data.get("success"):
            raise HTTPException(status_code=400, detail="遠端 API 返回錯誤")
        
        # 提取文章列表
        articles = data.get("data", [])
        if not articles:
            return {"message": "沒有找到需要同步的文章", "count": 0}
        
        # 轉換為 LangChain Document 對象
        documents = []
        for article in articles:
            doc = Document(
                page_content=article["content"],
                metadata={
                    "source": article["file_path"],
                    "id": article["id"],
                    "file_date": article["file_date"]
                }
            )
            documents.append(doc)
        
        # 添加到向量存儲（會自動生成 embedding）
        vector_store = get_vector_store()
        vector_store.add_documents(documents)
        
        # 返回同步結果
        return {
            "success": True,
            "message": f"成功同步 {len(articles)} 篇文章（重複的文章會被更新）",
            "count": len(articles),
            "articles": [
                {
                    "id": article["id"],
                    "file_path": article["file_path"],
                    "content_length": len(article["content"])
                }
                for article in articles
            ]
        }
        
    except httpx.RequestError as e:
        # 處理網絡請求錯誤
        logger.error(f"請求遠端 API 失敗: {str(e)}")
        raise HTTPException(status_code=500, detail=f"無法連接到遠端 API: {str(e)}")
    except Exception as e:
        # 處理其他錯誤
        logger.error(f"同步文章時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失敗: {str(e)}")

@router.get("/stats")
async def get_article_stats():
    """
    獲取文章統計資訊
    
    返回向量存儲中文章的統計信息，包括：
    - 總文章數量
    - 文件大小統計
    - 其他相關統計數據
    
    Returns:
        dict: 包含統計信息的字典
        
    Raises:
        HTTPException: 當獲取統計信息失敗時拋出 HTTP 異常
    """
    try:
        vector_store = get_vector_store()
        stats = vector_store.get_article_stats()
        return {
            "success": True,
            "stats": stats
        }
    except Exception as e:
        logger.error(f"獲取統計資訊時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"獲取統計資訊失敗: {str(e)}")

@router.post("/query")
async def query_document(request: QueryRequest):
    """
    查詢文件內容
    
    這是系統的核心問答功能，流程如下：
    1. 使用向量搜索找到相關文檔
    2. 使用 LLM 生成答案
    3. 保存對話記錄
    4. 返回答案和參考來源
    
    Args:
        request (QueryRequest): 查詢請求，包含問題文本和用戶 ID
        
    Returns:
        dict: 包含答案、參考來源和相關信息的字典
        
    Raises:
        HTTPException: 當查詢失敗時拋出 HTTP 異常
    """
    try:
        # 獲取核心組件實例
        vector_store = get_vector_store()
        qa_chain = get_qa_chain()
        chat_history_manager = get_chat_history()
        
        # 搜尋相關文件（限制數量以減少 token 使用）
        documents = vector_store.similarity_search(request.text, k=3)  # 從 4 減少到 3
        
        if not documents:
            # 即使沒有找到相關文件，也記錄對話
            chat_history_manager.save_conversation(
                user_message=request.text,
                ai_answer="抱歉，我沒有找到相關的文件內容來回答您的問題。",
                user_id=request.user_id
            )
            
            return {
                "success": False,
                "message": "抱歉，我沒有找到相關的文件內容來回答您的問題。",
                "data": []
            }

        # 獲取答案
        result = qa_chain.get_answer(request.text, documents)
        
        # 格式化返回的資料（包含完整的參考信息）
        formatted_data = []
        for doc in documents:
            # 提取內容片段（前200字符）
            content_preview = doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            
            # 構建格式化的文檔信息
            formatted_data.append({
                "id": doc.metadata.get("id"),
                "file_path": doc.metadata.get("file_path"),
                "title": doc.metadata.get("title", ""),
                "description": doc.metadata.get("description", ""),
                "tags": doc.metadata.get("tags", []),
                "similarity": round(doc.metadata.get("similarity", 0.0), 4),  # 四捨五入到4位小數
                "content_preview": content_preview,
                "content_length": len(doc.page_content),
                "file_date": doc.metadata.get("file_date", ""),
                "source": doc.metadata.get("source", "")
            })
        
        # 儲存對話記錄（包含參考文章信息）
        chat_history_manager.save_conversation(
            user_message=request.text,
            ai_answer=result["answer"],
            user_id=request.user_id,
            reference_data=formatted_data  # 添加參考文章信息
        )
        
        return {
            "success": True,
            "answer": result["answer"],
            "data": formatted_data
        }

    except Exception as e:
        logger.error(f"查詢時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查詢失敗: {str(e)}")

@router.get("/chat-history/{user_id}")
async def get_user_chat_history(user_id: str = "default", limit: int = 50):
    """
    獲取用戶的對話歷史記錄
    
    從 Redis 中檢索指定用戶的對話歷史，支持：
    - 用戶 ID 參數化
    - 結果數量限制
    - 按時間排序
    
    Args:
        user_id (str): 用戶 ID，默認為 "default"
        limit (int): 返回記錄數量限制，默認 50 條
        
    Returns:
        dict: 包含對話歷史的字典
        
    Raises:
        HTTPException: 當獲取對話歷史失敗時拋出 HTTP 異常
    """
    try:
        chat_history_manager = get_chat_history()
        history = chat_history_manager.get_conversation_history(user_id, limit)
        
        return {
            "success": True,
            "user_id": user_id,
            "history": history,
            "total_count": len(history)
        }
        
    except Exception as e:
        logger.error(f"獲取對話歷史時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"獲取對話歷史失敗: {str(e)}")

@router.get("/chat-stats/{user_id}")
async def get_chat_stats(user_id: str = "default"):
    """
    獲取用戶的對話統計資訊
    
    查詢指定用戶的對話統計信息，包括：
    - 總對話數量
    - TTL 信息
    - Redis key 信息
    
    Args:
        user_id (str): 用戶 ID，默認為 "default"
        
    Returns:
        dict: 包含統計信息的字典
        
    Raises:
        HTTPException: 當獲取統計信息失敗時拋出 HTTP 異常
    """
    try:
        chat_history_manager = get_chat_history()
        stats = chat_history_manager.get_conversation_stats(user_id)
        
        return {
            "success": True,
            "stats": stats
        }
        
    except Exception as e:
        logger.error(f"獲取對話統計時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"獲取對話統計失敗: {str(e)}")

@router.delete("/chat-history/{user_id}")
async def clear_chat_history(user_id: str = "default"):
    """
    清除用戶的對話歷史記錄
    
    刪除指定用戶的所有對話記錄，包括：
    - 用戶對話數據
    - 相關統計信息
    - Redis key 清理
    
    Args:
        user_id (str): 用戶 ID，默認為 "default"
        
    Returns:
        dict: 操作結果字典
        
    Raises:
        HTTPException: 當清除對話歷史失敗時拋出 HTTP 異常
    """
    try:
        chat_history_manager = get_chat_history()
        success = chat_history_manager.clear_conversation_history(user_id)
        
        if success:
            return {
                "success": True,
                "message": f"已清除用戶 {user_id} 的對話歷史記錄"
            }
        else:
            raise HTTPException(status_code=500, detail="清除對話歷史失敗")
        
    except Exception as e:
        logger.error(f"清除對話歷史時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除對話歷史失敗: {str(e)}")

@router.get("/chat-users")
async def get_all_chat_users():
    """
    獲取所有有對話記錄的用戶列表
    
    掃描 Redis 中所有聊天記錄的 key，提取用戶 ID 列表，
    用於管理員查看系統中的活躍用戶
    
    Returns:
        dict: 包含用戶列表的字典
        
    Raises:
        HTTPException: 當獲取用戶列表失敗時拋出 HTTP 異常
    """
    try:
        chat_history_manager = get_chat_history()
        users = chat_history_manager.get_all_users()
        
        return {
            "success": True,
            "users": users,
            "total_users": len(users)
        }
        
    except Exception as e:
        logger.error(f"獲取用戶列表時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"獲取用戶列表失敗: {str(e)}") 