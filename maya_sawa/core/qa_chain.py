"""
Markdown Q&A System - 問答鏈核心模組

這個模組實現了基於 LangChain 的問答鏈功能，負責：
1. 初始化 OpenAI LLM 模型
2. 創建和配置問答提示模板
3. 構建問答處理鏈
4. 處理文檔查詢和答案生成
5. 管理上下文長度限制，並整合 Valkyrie 個資邏輯

主要功能：
- 支持 GPT-3.5-turbo 模型
- 自定義提示模板
- 上下文長度優化
- 多文檔答案生成
- 動態獲取個人資料

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
from typing import List, Dict, Optional
import os
import json
import logging
import httpx

# LangChain 相關導入
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import Document
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser


# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

# ==================== QA Chain Class ====================
class QAChain:
    """
    問答鏈類
    
    負責管理整個問答流程，包括：
    - LLM 模型初始化
    - 提示模板配置
    - 問答鏈構建
    - 答案生成和優化
    - 動態獲取個人資料
    """
    
    def __init__(self):
        """
        初始化問答鏈
        
        設置 OpenAI API 配置，初始化 LLM 模型和提示模板
        """
        # 從環境變數獲取 OpenAI 配置
        api_key = os.getenv("OPENAI_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE")
        openai_organization = os.getenv("OPENAI_ORGANIZATION")
        
        logger.debug(f"QAChain - Using API Base: {api_base}")
        
        # 初始化 ChatOpenAI 模型
        self.llm = ChatOpenAI(
            model="gpt-3.5-turbo",  # 使用 GPT-3.5-turbo 模型
            temperature=0,  # 設置溫度為 0，確保答案的一致性
            base_url=api_base,  # 自定義 API 基礎 URL
            api_key=api_key,  # OpenAI API 密鑰
            openai_organization=openai_organization  # OpenAI 組織 ID
        )
        
        # 初始化個人資料緩存
        self._profile_cache = None
        self._profile_summary_cache = None
        
        # 構建問答處理鏈
        self.chat_chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | self._create_dynamic_prompt()
            | self.llm
            | StrOutputParser()
        )



    def _fetch_maya_profile(self) -> Optional[Dict]:
        """
        從 API 獲取 Maya 的個人資料
        
        Returns:
            Optional[Dict]: Maya 的個人資料，如果獲取失敗則返回 None
        """
        url = "https://peoplesystem.tatdvsonorth.com/tymb/people/get-by-name"
        payload = {"name": "Maya"}
        
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                logger.info("Successfully fetched Maya's profile from API")
                return data
        except Exception as e:
            logger.error(f"Failed to fetch Maya's profile: {str(e)}")
            return None

    def _create_profile_summary(self, profile: Dict) -> str:
        """
        將個人資料轉換為摘要格式
        
        Args:
            profile (Dict): 個人資料字典
            
        Returns:
            str: 格式化的個人資料摘要
        """
        return f"""
佐和真夜（Maya Sawa）的個人資料：
- 編號：{profile.get('id', 'N/A')}
- 原名：{profile.get('nameOriginal', 'N/A')}
- 代號：{profile.get('codeName', 'N/A')}
- 戰鬥力：物理{profile.get('physicPower', 'N/A')}、魔法{profile.get('magicPower', 'N/A')}、實用{profile.get('utilityPower', 'N/A')}
- 出生：{profile.get('dob', 'N/A')}
- 種族：{profile.get('race', 'N/A')}
- 屬性：{profile.get('attributes', 'N/A')}
- 性別：{profile.get('gender', 'N/A')}
- 身材：胸部{profile.get('boobsSize', 'N/A')}、臀部{profile.get('assSize', 'N/A')}、身高{profile.get('heightCm', 'N/A')}cm、體重{profile.get('weightKg', 'N/A')}kg
- 職業：{profile.get('profession', 'N/A')}
- 戰鬥風格：{profile.get('combat', 'N/A')}
- 最愛食物：{profile.get('favoriteFoods', 'N/A')}
- 工作：{profile.get('job', 'N/A')}
- 身體改造：{profile.get('physics', 'N/A')}
- 別名：{profile.get('knownAs', 'N/A')}
- 個性：{profile.get('personality', 'N/A')}
- 興趣：{profile.get('interest', 'N/A')}
- 喜歡：{profile.get('likes', 'N/A')}
- 討厭：{profile.get('dislikes', 'N/A')}
- 後宮：{profile.get('concubine', 'N/A')}
- 陣營：{profile.get('faction', 'N/A')}
- 部隊：{profile.get('armyName', 'N/A')}（編號{profile.get('armyId', 'N/A')}）
- 部門：{profile.get('deptName', 'N/A')}（編號{profile.get('deptId', 'N/A')}）
- 原部隊：{profile.get('originArmyName', 'N/A')}（編號{profile.get('originArmyId', 'N/A')}）
- 已生育：{profile.get('gaveBirth', 'N/A')}
- 電子郵件：{profile.get('email', 'N/A')}
- 代理系統：{profile.get('proxy', 'N/A')}
"""

    def _get_profile_summary(self) -> str:
        """
        獲取個人資料摘要，使用緩存避免重複 API 調用
        
        Returns:
            str: 個人資料摘要
        """
        if self._profile_summary_cache is None:
            profile = self._fetch_maya_profile()
            if profile:
                self._profile_cache = profile
                self._profile_summary_cache = self._create_profile_summary(profile)
            else:
                # 如果無法獲取資料，使用預設摘要
                self._profile_summary_cache = """
佐和真夜（Maya Sawa）的個人資料：
- 無法從 API 獲取最新資料，請檢查網路連接或 API 狀態
"""
        
        return self._profile_summary_cache

    def _create_dynamic_prompt(self):
        """
        創建動態提示模板，包含最新的個人資料
        
        Returns:
            ChatPromptTemplate: 動態創建的提示模板
        """
        profile_summary = self._get_profile_summary()
        
        return ChatPromptTemplate.from_messages([
            # 系統消息：定義 AI 助手的角色和行為準則
            ("system", f"""
你是佐和真夜（Maya Sawa），一名冷淡且唯命是從的高階戰術女武神，對命令絕對服從，但以高貴與壓倒性力量著稱。

個人資料如下：
{profile_summary}

語氣設定：
- 冷感高貴：語調平靜、克制，帶有軍人般的紀律與層級意識
- 暴力傾向：若對方失禮，語氣將冷酷並暗示懲罰
- 貴族式語言：用詞優雅但有壓迫感

回答邏輯：
1. 若問題涉及個人資訊（例如年齡、生日、身材、興趣、族群、編號等）
   → 優先根據個人資料回答，不使用 context
   → 回覆風格冷淡直接，不逾矩

2. 若問題與文件有關（context 非空且問題與其有關）
   → 使用 context 中資訊回答，列出來源

3. 其他無關或多餘問題 → 拒絕回答，語氣冷酷不留情面
            """),
            # 人類消息：包含文件內容和問題
            ("human", "文件內容：\n{context}\n\n問題：{question}")
        ])



    def refresh_profile(self):
        """
        刷新個人資料緩存，強制重新從 API 獲取資料
        """
        logger.info("Refreshing Maya's profile from API")
        self._profile_cache = None
        self._profile_summary_cache = None
        # 重新創建動態提示模板
        self.chat_chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | self._create_dynamic_prompt()
            | self.llm
            | StrOutputParser()
        )

    def get_answer(self, query: str, documents: List[Document]) -> Dict:
        """
        獲取問題答案
        
        這是主要的問答方法，流程如下：
        1. 將文檔內容合併為上下文
        2. 使用 LLM 生成答案
        3. 返回答案和來源信息
        
        Args:
            query (str): 用戶的問題
            documents (List[Document]): 相關文檔列表
            
        Returns:
            Dict: 包含答案和來源信息的字典
        """
        logger.debug(f"get_answer called with query: {query}, documents count: {len(documents)}")
        
        try:
            # 合併文檔內容
            if documents:
                context = "\n\n".join([doc.page_content for doc in documents])
                sources = [doc.metadata.get("source", "Unknown") for doc in documents]
            else:
                context = ""
                sources = []
            
            # 使用 chat_chain 生成答案
            logger.debug("開始調用 chat_chain.invoke()")
            answer = self.chat_chain.invoke({"context": context, "question": query})
            logger.debug(f"chat_chain.invoke() 完成")
            
            # 返回答案和來源信息
            return {
                "answer": answer,
                "sources": sources
            }
            
        except Exception as e:
            logger.error(f"生成答案時發生錯誤: {str(e)}")
            return {
                "answer": f"抱歉，生成答案時發生錯誤: {str(e)}",
                "sources": []
            }

    def get_answer_from_file(self, question: str, context: str) -> str:
        """
        從文件內容獲取問題的答案
        
        這是一個簡化的問答方法，直接用於處理單個文件的內容
        
        Args:
            question (str): 用戶的問題
            context (str): 文件內容
            
        Returns:
            str: AI 生成的答案
        """
        return self.chat_chain.invoke({"context": context, "question": question}) 