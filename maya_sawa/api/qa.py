import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import logging
import httpx
import asyncio
from ..core.postgres_store import PostgresVectorStore
from ..core.qa_chain import QAChain
from ..core.loader import DocumentLoader
from ..core.chat_history import ChatHistoryManager
from langchain.schema import Document
from typing import List, Dict, Any

# 從環境變數獲取 API base URL
PUBLIC_API_BASE_URL = os.getenv("PUBLIC_API_BASE_URL", "https://peoplesystem.tatdvsonorth.com")

logger = logging.getLogger(__name__)

# 使用 lazy initialization
_vector_store = None
_qa_chain = None
_chat_history = None

def get_vector_store():
    """獲取向量存儲實例（懶加載）"""
    global _vector_store
    if _vector_store is None:
        _vector_store = PostgresVectorStore()
    return _vector_store

def get_qa_chain():
    """獲取問答鏈實例（懶加載）"""
    global _qa_chain
    if _qa_chain is None:
        _qa_chain = QAChain()
    return _qa_chain

def get_chat_history():
    """獲取對話記錄管理實例（懶加載）"""
    global _chat_history
    if _chat_history is None:
        _chat_history = ChatHistoryManager()
    return _chat_history

router = APIRouter(prefix="/qa", tags=["Q&A"])

class QueryRequest(BaseModel):
    text: str
    user_id: str = "default"  # 新增用戶 ID 欄位

class SyncRequest(BaseModel):
    remote_url: str = f"{PUBLIC_API_BASE_URL}/paprika/articles"

class SyncFromAPIRequest(BaseModel):
    remote_url: str = f"{PUBLIC_API_BASE_URL}/paprika/articles"

@router.post("/sync-from-api")
async def sync_articles_from_api(request: SyncFromAPIRequest):
    """從遠端 API 同步文章並使用預計算的 embedding"""
    try:
        # 從遠端 API 獲取文章
        async with httpx.AsyncClient() as client:
            response = await client.get(request.remote_url)
            response.raise_for_status()
            data = response.json()
        
        if not data.get("success"):
            raise HTTPException(status_code=400, detail="遠端 API 返回錯誤")
        
        articles = data.get("data", [])
        if not articles:
            return {"message": "沒有找到需要同步的文章", "count": 0}
        
        # 使用新的方法添加文章（使用預計算的 embedding）
        vector_store = get_vector_store()
        vector_store.add_articles_from_api(articles)
        
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
        logger.error(f"請求遠端 API 失敗: {str(e)}")
        raise HTTPException(status_code=500, detail=f"無法連接到遠端 API: {str(e)}")
    except Exception as e:
        logger.error(f"同步文章時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失敗: {str(e)}")

@router.post("/sync-articles")
async def sync_articles_from_remote(request: SyncRequest):
    """從遠端 API 同步文章並生成 embedding（保留原有方法以向後兼容）"""
    try:
        # 從遠端 API 獲取文章
        async with httpx.AsyncClient() as client:
            response = await client.get(request.remote_url)
            response.raise_for_status()
            data = response.json()
        
        if not data.get("success"):
            raise HTTPException(status_code=400, detail="遠端 API 返回錯誤")
        
        articles = data.get("data", [])
        if not articles:
            return {"message": "沒有找到需要同步的文章", "count": 0}
        
        # 轉換為 Document 對象
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
        
        # 添加到向量存儲
        vector_store = get_vector_store()
        vector_store.add_documents(documents)
        
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
        logger.error(f"請求遠端 API 失敗: {str(e)}")
        raise HTTPException(status_code=500, detail=f"無法連接到遠端 API: {str(e)}")
    except Exception as e:
        logger.error(f"同步文章時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失敗: {str(e)}")

@router.get("/stats")
async def get_article_stats():
    """獲取文章統計資訊"""
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
    """查詢文件內容"""
    try:
        # 獲取實例
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
        
        # 儲存對話記錄
        chat_history_manager.save_conversation(
            user_message=request.text,
            ai_answer=result["answer"],
            user_id=request.user_id
        )
        
        # 格式化返回的資料（移除 content 欄位，前端可以自己查看）
        formatted_data = []
        for doc in documents:
            formatted_data.append({
                "id": doc.metadata.get("id"),
                "file_path": doc.metadata.get("file_path"),
                "title": doc.metadata.get("title", ""),
                "description": doc.metadata.get("description", ""),
                "tags": doc.metadata.get("tags", []),
                "similarity": doc.metadata.get("similarity", 0.0)
            })
        
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
    """獲取用戶的對話歷史記錄"""
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
    """獲取用戶的對話統計資訊"""
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
    """清除用戶的對話歷史記錄"""
    try:
        chat_history_manager = get_chat_history()
        success = chat_history_manager.clear_conversation_history(user_id)
        
        if success:
            return {
                "success": True,
                "message": f"成功清除用戶 {user_id} 的對話歷史記錄"
            }
        else:
            raise HTTPException(status_code=500, detail="清除對話歷史記錄失敗")
            
    except Exception as e:
        logger.error(f"清除對話歷史時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"清除對話歷史失敗: {str(e)}")

@router.get("/chat-users")
async def get_all_chat_users():
    """獲取所有有對話記錄的用戶列表"""
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