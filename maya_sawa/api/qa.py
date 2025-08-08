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
# 可能可用的翻譯備援
# 移除 googletrans 依賴，只使用 LLM 翻譯
_google_translator_available = False

# LangChain 相關導入
from maya_sawa.core.langchain_shim import Document

# 本地模組導入
from ..core.postgres_store import PostgresVectorStore
from ..core.qa_chain import QAChain
from ..core.chat_history import ChatHistoryManager
from ..core.config import Config
from ..people import PeopleWeaponManager
from ..people import sync_data

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
2. 如果是 self_name 的回答，保持她冷淡高貴的語氣
3. 如果是角色描述，保持生動的描述風格
4. 確保翻譯準確且自然

只返回翻譯結果，不要添加任何解釋。
"""
        
        translated = qa_chain.llm.invoke(translation_prompt)
        if hasattr(translated, 'content'):
            translated = translated.content

        # ------------------  檢查翻譯質量 ------------------
        def _is_translation_valid(src: str, tgt: str) -> bool:
            """簡單檢查目標語句是否包含大量中文或常見拒絕語句"""
            if not tgt:
                return False
            chinese_ratio = sum(1 for ch in tgt if '\u4e00' <= ch <= '\u9fff') / max(len(tgt), 1)
            refusal_keywords = [
                "Please provide", "provide the character", "Please input", "I'm sorry", "抱歉", "對不起"
            ]
            if chinese_ratio > 0.3:
                return False
            if any(k.lower() in tgt.lower() for k in refusal_keywords):
                return False
            return True

        if not _is_translation_valid(text, translated):
            # 若主要翻譯失敗且可用 Google 翻譯，作為備援
            if _google_translator_available:
                try:
                    # translator = GoogleTranslator(service_urls=["translate.googleapis.com"])
                    # translated_google = translator.translate(text, src="zh-CN", dest="en").text
                    # if _is_translation_valid(text, translated_google):
                    #     translated = translated_google
                    pass # 移除 googletrans 依賴，這裡不再有備援翻譯
                except Exception as e:
                    logger.warning(f"Google translate fallback failed: {str(e)}")

        # 如果依舊無效，最終退回原文
        if not _is_translation_valid(text, translated):
            logger.warning("Translation still invalid after fallback, returning original text")
            translated = text
 
        # ---- 確保圖片/連結行保留 ----
        try:
            src_link_lines = [ln.strip() for ln in text.splitlines() if "http" in ln]
            for ln in src_link_lines:
                if ln and ln not in translated:
                    translated += "\n" + ln
        except Exception as _:
            pass

        # 確保 translated 是字符串
        if not isinstance(translated, str):
            logger.warning(f"翻譯結果不是字符串: {type(translated)}")
            return text
        
        # 安全地進行字符串切片
        text_preview = text[:50] + "..." if len(text) > 50 else text
        translated_preview = translated[:50] + "..." if len(translated) > 50 else translated
        
        logger.info(f"翻譯完成: {text_preview} -> {translated_preview}")
        return translated
        
    except Exception as e:
        logger.error(f"翻譯失敗: {str(e)}")
        # 如果翻譯失敗，返回原文
        return text

# ==================== 環境變數配置 ====================
# 從環境變數獲取公共 API 基礎 URL
def get_public_api_base_url():
    """獲取公共 API 基礎 URL"""
    from ..core.config import Config
    return Config.PUBLIC_API_BASE_URL

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

# 新增 self 角色名字，讓前端可動態指定
class QueryRequest(BaseModel):
    """
    查詢請求模型
    
    定義用戶發送問答查詢時的請求格式
    """
    text: str  # 用戶的問題文本
    user_id: str = "default"  # 用戶 ID，預設為 "default"
    language: str = "chinese"  # 語言參數，預設為 "chinese"
    name: Optional[str] = "Maya"   # 角色名稱，預設 Maya，可由前端覆寫
    frontend_source: Optional[str] = None  # 前端來源，用於控制文章QA功能
    analysis_type: Optional[str] = None    # 分析類型 (如 "page_summary")
    page_url: Optional[str] = None         # 分析頁面的 URL (可選)
    content_length: Optional[int] = None   # 客戶端傳來的內容長度 (可選)

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
    1. 檢索相關文件
    2. 調用 QAChain 獲取答案（QAChain內部會判斷是角色問題還是文件問題）
    3. 根據 QAChain 的返回結果，格式化 `data` 欄位
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
    # ==================== 頁面分析請求專用 ====================
    from ..core.page_analyzer import PageAnalyzer
    if request.analysis_type and request.analysis_type.startswith("page_"):
        logger.info(f"收到頁面分析請求: {request.analysis_type}")
        page_analyzer = PageAnalyzer()
        page_result = page_analyzer.analyze_page_content(
            content=request.text,
            analysis_type=request.analysis_type.replace("page_", ""),
            language=request.language
        )
        if page_result.get("success"):
            return {
                "success": True,
                "answer": page_result["answer"],
                "data": [{
                    "source": "PageAnalyzer",
                    "analysis_type": page_result["analysis_type"],
                    "content_length": page_result["content_length"],
                    "language": page_result.get("language", "chinese")
                }]
            }
        else:
            raise HTTPException(status_code=500, detail=page_result.get("error", "Page analysis failed"))
    # === DEBUG: 印出前端傳入的原始 JSON ===
    logger.info(f"/qa/query payload: {request.dict()}")
    
    # 檢查前端來源，決定是否啟用文章QA功能
    enable_article_qa = True
    if request.frontend_source:
        # 只有當前端來源是 https://peoplesystem.tatdvsonorth.com/tymultiverse 開頭時才啟用文章QA
        expected_source = get_public_api_base_url() + "/tymultiverse"
        if not request.frontend_source.startswith(expected_source):
            enable_article_qa = False
            logger.info(f"前端來源 {request.frontend_source} 不符合要求，禁用文章QA功能")
        else:
            logger.info(f"前端來源 {request.frontend_source} 符合要求，啟用文章QA功能")
    else:
        logger.info("未提供前端來源，預設啟用文章QA功能")
    
    # 獲取核心組件實例
    vector_store = get_vector_store()
    qa_chain = get_qa_chain()
    chat_history_manager = get_chat_history()
    
    # 根據前端來源決定是否搜索文件
    if enable_article_qa:
        # 統一流程：始終先搜索文件，由 QAChain 決定是否使用
        # 使用環境變數設定的檢索數量，預設 3
        documents = vector_store.similarity_search(request.text, k=Config.ARTICLE_MATCH_COUNT)
        logger.info(f"啟用文章QA功能，搜索到 {len(documents)} 個相關文檔")
    else:
        # 禁用文章QA功能，不搜索文件
        documents = []
        logger.info("禁用文章QA功能，不進行文件搜索")
    
    # 獲取答案和分析結果
    # 將前端傳入的 name 轉給 QAChain，若未提供則沿用預設 "Maya"
    result = qa_chain.get_answer(request.text, documents, self_name=(request.name or "Maya"), user_id=request.user_id)
    
    # 如果語言為英語，翻譯答案
    if request.language.lower() == "english":
        translated_answer = await translate_to_english(result["answer"])
        final_answer = translated_answer
    else:
        final_answer = result["answer"]
        
    # 根據 QAChain 的結果格式化返回的 `data`
    formatted_data = []
    found_characters = result.get("found_characters", [])
    
    if found_characters:
        # 如果是角色問題，來源設定為 PeopleSystem
        for char_name in found_characters:
            formatted_data.append({
                "source": "PeopleSystem",
                "character_name": char_name
            })
    elif documents:
        # 如果是文件問答，來源為文件本身
        for doc in documents:
            content_preview = doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            formatted_data.append({
                "id": doc.metadata.get("id"),
                "file_path": doc.metadata.get("file_path"),
                "title": doc.metadata.get("title", ""),
                "description": doc.metadata.get("description", ""),
                "tags": doc.metadata.get("tags", []),
                "similarity": round(doc.metadata.get("similarity", 0.0), 4),
                "content_preview": content_preview,
                "content_length": len(doc.page_content),
                "file_date": doc.metadata.get("file_date", ""),
                "source": doc.metadata.get("source", "")
            })
    else:
        # 如果沒有找到任何文件或角色，返回適當的消息
        if not final_answer: # 如果 QAChain 也沒有給出答案
            if not enable_article_qa:
                # 當禁用文章QA時，提示用戶只能詢問角色相關問題
                error_message = "抱歉，我只能回答角色相關的問題。請詢問關於特定角色的問題。"
            else:
                # 當啟用文章QA時，提示用戶沒有找到相關內容
                error_message = "抱歉，我沒有找到相關的內容來回答您的問題。"
            
            if request.language.lower() == "english":
                final_answer = await translate_to_english(error_message)
            else:
                final_answer = error_message

    # 儲存對話記錄
    chat_history_manager.save_conversation(
        user_message=request.text,
        ai_answer=final_answer,
        user_id=request.user_id,
        reference_data=formatted_data
    )
    
    return {
        "success": True,
        "answer": final_answer,
        "data": formatted_data
    }

    # 移除錯誤處理，直接返回結果

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