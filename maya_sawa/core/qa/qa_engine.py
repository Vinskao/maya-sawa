"""
Markdown Q&A System - 問答引擎模組

這個模組是問答系統的核心引擎，負責：
1. 整合 QAChain 作為底層問答邏輯
2. 提供統一的異步問答接口
3. 管理問答流程和錯誤處理
4. 支持文檔檢索和答案生成

主要功能：
- QAChain 集成
- 異步問答處理
- 文檔檢索支持
- 錯誤處理和日誌記錄

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
from typing import List, Dict, Optional
import logging

# LangChain 相關導入
from ..processing.langchain_shim import Document

# 本地模組導入
from .qa_chain import QAChain

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class QAEngine:
    """
    問答引擎類：封裝 QAChain，提供統一的異步問答接口
    
    這個類作為 QAChain 的異步封裝，提供：
    - 統一的異步問答接口
    - 文檔檢索支持
    - 錯誤處理和日誌記錄
    - 與現有 API 的兼容性
    """
    
    def __init__(self):
        """
        初始化問答引擎
        
        創建 QAChain 實例作為底層問答邏輯
        """
        logger.info("初始化 QAEngine")
        self.chain = QAChain()
        logger.info("QAEngine 初始化完成")

    async def get_answer(self, question: str, documents: List[Document] = None, user_id: str = "default") -> Dict:
        """
        異步問答方法，直接調用 QAChain
        
        Args:
            question (str): 用戶的問題
            documents (List[Document], optional): 相關文檔列表，如果為 None 則使用空列表
            user_id (str): 用戶 ID，用於清除特定用戶的聊天記錄
            
        Returns:
            Dict: 包含答案和來源信息的字典，格式為 {"answer": str, "sources": List[str]}
        """
        try:
            logger.debug(f"QAEngine.get_answer 被調用，問題: {question[:50]}...")
            
            # 確保 documents 不為 None
            if documents is None:
                documents = []
            
            # 調用 QAChain 的 get_answer 方法
            result = self.chain.get_answer(question, documents, user_id=user_id)
            
            logger.debug(f"QAEngine.get_answer 完成，答案長度: {len(result.get('answer', ''))}")
            return result
            
        except Exception as e:
            logger.error(f"QAEngine.get_answer 發生錯誤: {str(e)}")
            return {
                "answer": f"抱歉，生成答案時發生錯誤: {str(e)}",
                "sources": []
            }

    async def get_answer_from_file(self, question: str, context: str) -> str:
        """
        從文件內容獲取問題的答案（異步方法）
        
        Args:
            question (str): 用戶的問題
            context (str): 文件內容
            
        Returns:
            str: AI 生成的答案
        """
        try:
            logger.debug(f"QAEngine.get_answer_from_file 被調用，問題: {question[:50]}...")
            
            # 調用 QAChain 的 get_answer_from_file 方法
            result = self.chain.get_answer_from_file(question, context)
            
            logger.debug(f"QAEngine.get_answer_from_file 完成")
            return result
            
        except Exception as e:
            logger.error(f"QAEngine.get_answer_from_file 發生錯誤: {str(e)}")
            return f"抱歉，生成答案時發生錯誤: {str(e)}"

    def refresh_profile(self):
        """
        刷新個人資料緩存
        
        委託給 QAChain 的 refresh_profile 方法
        """
        logger.info("QAEngine 刷新個人資料緩存")
        self.chain.refresh_profile()

    def refresh_other_profile(self, name: str):
        """
        刷新指定角色的個人資料緩存
        
        Args:
            name (str): 角色名稱
        """
        logger.info(f"QAEngine 刷新角色 {name} 的個人資料緩存")
        self.chain.refresh_other_profile(name)

    def clear_all_profiles_cache(self):
        """
        清除所有角色資料緩存
        
        委託給 QAChain 的 clear_all_profiles_cache 方法
        """
        logger.info("QAEngine 清除所有角色資料緩存")
        self.chain.clear_all_profiles_cache() 