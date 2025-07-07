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
from typing import List, Dict, Any, Optional

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
from ..core.people import sync_data
from ..core.config import Config

# ==================== 翻譯功能 ====================
async def translate_to_english(text: str) -> str:
    """
    將中文文本翻譯為英語
    
    Args:
        text (str): 要翻譯的中文文本
        
    Returns:
        str: 翻譯後的英語文本
    """
    try:
        # 使用 QAChain 的 LLM 進行翻譯
        qa_chain = get_qa_chain()
        
        translation_prompt = f"""
請將以下中文文本翻譯為英語，保持原有的語氣和風格：

{text}

翻譯要求：
1. 保持原文的語氣和風格
2. 如果是 Maya 的回答，保持她冷淡高貴的語氣
3. 如果是角色描述，保持生動的描述風格
4. 確保翻譯準確且自然

只返回翻譯結果，不要添加任何解釋。
"""
        
        translated = qa_chain.llm.invoke(translation_prompt)
        if hasattr(translated, 'content'):
            translated = translated.content
        
        logger.info(f"翻譯完成: {text[:50]}... -> {translated[:50]}...")
        return translated
        
    except Exception as e:
        logger.error(f"翻譯失敗: {str(e)}")
        # 如果翻譯失敗，返回原文
        return text

# ==================== 環境變數配置 ====================
# 從環境變數獲取公共 API 基礎 URL
def get_public_api_base_url():
    """獲取公共 API 基礎 URL"""
    return os.getenv("PUBLIC_API_BASE_URL", "")

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)
logger.debug(f"PUBLIC_API_BASE_URL loaded: {get_public_api_base_url()}")

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
    language: str = "chinese"  # 語言參數，預設為 "chinese"

class SyncRequest(BaseModel):
    """
    同步請求模型
    
    定義文章同步請求的格式
    """
    remote_url: Optional[str] = None  # 遠端 API URL，可選

class SyncFromAPIRequest(BaseModel):
    """
    從 API 同步請求模型
    
    定義從遠端 API 同步文章的請求格式
    """
    remote_url: Optional[str] = None  # 遠端 API URL，可選

class PeopleWeaponsSyncRequest(BaseModel):
    """
    人員和武器同步請求模型
    
    定義人員和武器數據同步的請求格式
    """
    max_time_seconds: Optional[int] = 60  # 最大處理時間（秒）

class PeopleSearchRequest(BaseModel):
    """
    人員語義搜索請求模型
    
    定義人員語義搜索的請求格式
    """
    query: str  # 搜索查詢文本
    limit: int = 5  # 返回結果數量限制
    threshold: float = 0.5  # 相似度閾值
    sort_by_power: bool = False  # 是否按戰鬥力排序

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
        remote_url = request.remote_url or f"{get_public_api_base_url()}/paprika/articles"
        
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
        remote_url = request.remote_url or f"{get_public_api_base_url()}/paprika/articles"
        
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
    1. 檢查是否為個人資訊問題，如果是則直接回答
    2. 使用向量搜索找到相關文檔
    3. 使用 LLM 生成答案
    4. 如果語言為英語，翻譯答案
    5. 保存對話記錄
    6. 返回答案和參考來源
    
    Args:
        request (QueryRequest): 查詢請求，包含問題文本、用戶 ID 和語言參數
        
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
        
        # 檢查是否為個人資訊問題（包含 Maya 和其他角色）
        personal_info_keywords = [
            "身高", "體重", "年齡", "生日", "出生", "身材", "胸部", "臀部", 
            "興趣", "喜歡", "討厭", "最愛", "食物", "個性", "性格", "職業", 
            "工作", "種族", "編號", "代號", "原名", "部隊", "部門", "陣營",
            "戰鬥力", "物理", "魔法", "武器", "戰鬥", "屬性", "性別", "電子郵件",
            "email", "後宮", "已生育", "體態", "別名", "原部隊", "是誰", 
            "誰是", "怎樣", "什麼人", "有什麼特徵", "資料", "資訊", "個人"
        ]
        
        is_personal_question = any(keyword in request.text for keyword in personal_info_keywords)
        
        if is_personal_question:
            # 個人資訊問題：直接使用個人資料回答，不搜索文件
            result = qa_chain.get_answer(request.text, [])  # 傳入空文件列表
            
            # 如果語言為英語，翻譯答案
            if request.language.lower() == "english":
                translated_answer = await translate_to_english(result["answer"])
                final_answer = translated_answer
            else:
                final_answer = result["answer"]
            
            # 儲存對話記錄（個人資訊問題不包含參考文件）
            chat_history_manager.save_conversation(
                user_message=request.text,
                ai_answer=final_answer,
                user_id=request.user_id
            )
            
            return {
                "success": True,
                "answer": final_answer,
                "data": []  # 個人資訊問題不返回文件資料
            }
        
        # 非個人資訊問題：搜索相關文件
        documents = vector_store.similarity_search(request.text, k=3)
        
        if not documents:
            # 即使沒有找到相關文件，也記錄對話
            error_message = "抱歉，我沒有找到相關的文件內容來回答您的問題。"
            if request.language.lower() == "english":
                error_message = await translate_to_english(error_message)
            
            chat_history_manager.save_conversation(
                user_message=request.text,
                ai_answer=error_message,
                user_id=request.user_id
            )
            
            return {
                "success": False,
                "message": error_message,
                "data": []
            }

        # 獲取答案
        result = qa_chain.get_answer(request.text, documents)
        
        # 如果語言為英語，翻譯答案
        if request.language.lower() == "english":
            translated_answer = await translate_to_english(result["answer"])
            final_answer = translated_answer
        else:
            final_answer = result["answer"]
        
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
            ai_answer=final_answer,
            user_id=request.user_id,
            reference_data=formatted_data  # 添加參考文章信息
        )
        
        return {
            "success": True,
            "answer": final_answer,
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

@router.post("/sync-people-weapons")
async def sync_people_weapons_data(request: PeopleWeaponsSyncRequest = PeopleWeaponsSyncRequest()):
    """
    同步人員和武器數據
    
    從外部 API 獲取人員和武器數據，並更新 PostgreSQL 表格，
    同時生成 embedding 用於語義搜索。
    
    Args:
        request (PeopleWeaponsSyncRequest): 同步請求，包含時間限制
        
    Returns:
        dict: 同步結果，包含成功狀態、消息、更新記錄數量等
        
    Raises:
        HTTPException: 當同步失敗時拋出 HTTP 異常
    """
    try:
        logger.info(f"開始同步人員和武器數據 (最大時間: {request.max_time_seconds}s)...")
        
        # 執行數據同步
        result = sync_data(max_time_seconds=request.max_time_seconds)
        
        return {
            "success": True,
            "message": f"人員和武器數據同步完成 (耗時: {result.get('total_time_seconds', 0)}s)",
            "data": {
                "people_updated": result["people_updated"],
                "weapons_updated": result["weapons_updated"],
                "total_updated": result["total_updated"],
                "total_time_seconds": result.get("total_time_seconds", 0),
                "people_data_count": result.get("people_data_count", 0),
                "weapons_data_count": result.get("weapons_data_count", 0)
            }
        }
        
    except Exception as e:
        logger.error(f"同步人員和武器數據時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"同步失敗: {str(e)}")

@router.get("/sync-config")
async def get_sync_configuration():
    """
    獲取同步配置信息
    
    返回當前系統的同步配置設置，包括：
    - 自動同步開關
    - 定期同步設置
    - 人員武器同步設置
    
    Returns:
        dict: 包含同步配置信息的字典
    """
    try:
        config_summary = Config.get_sync_config_summary()
        missing_config = Config.validate_required_config()
        
        return {
            "success": True,
            "config": config_summary,
            "missing_config": missing_config,
            "has_required_config": len(missing_config) == 0
        }
        
    except Exception as e:
        logger.error(f"獲取同步配置時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"獲取配置失敗: {str(e)}")

@router.post("/stop-sync")
async def stop_sync_tasks():
    """
    停止所有同步任務
    
    停止正在運行的定期同步任務，包括：
    - 文章同步任務
    - 人員武器同步任務
    
    Returns:
        dict: 操作結果字典
    """
    try:
        from ..core.scheduler import scheduler
        
        # 停止定期同步任務
        await scheduler.stop_periodic_sync()
        
        return {
            "success": True,
            "message": "所有同步任務已停止"
        }
        
    except Exception as e:
        logger.error(f"停止同步任務時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"停止同步失敗: {str(e)}")

@router.post("/search-people")
async def search_people_by_semantics(request: PeopleSearchRequest):
    """
    基於語義搜索人員資料
    
    使用 embedding 進行語義搜索，找到與查詢最相關的人員記錄。
    只返回 name 和 embedding 欄位，其他資料可通過 tymb API 獲取。
    
    Args:
        request (PeopleSearchRequest): 搜索請求，包含查詢文本、結果數量限制和相似度閾值
        
    Returns:
        dict: 搜索結果，包含相關人員列表和相似度分數
        
    Raises:
        HTTPException: 當搜索失敗時拋出 HTTP 異常
    """
    try:
        from ..core.people import PeopleWeaponManager
        
        # 初始化人員管理器
        manager = PeopleWeaponManager()
        
        # 檢查 OpenAI client 是否可用
        if not manager.openai_client:
            raise HTTPException(status_code=500, detail="OpenAI client 不可用，無法生成 embedding")
        
        # 生成查詢的 embedding
        query_embedding = manager.generate_embedding(request.query)
        if not query_embedding:
            raise HTTPException(status_code=500, detail="無法生成查詢的 embedding")
        
        # 執行語義搜索
        results = manager.search_people_by_embedding(
            query_embedding=query_embedding,
            limit=request.limit,
            threshold=request.threshold,
            sort_by_power=request.sort_by_power
        )
        
        return {
            "success": True,
            "query": request.query,
            "results": results,
            "total_found": len(results)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"人員語義搜索時發生錯誤: {str(e)}")
        raise HTTPException(status_code=500, detail=f"搜索失敗: {str(e)}")

 