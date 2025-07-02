"""
Markdown Q&A System - 問答鏈核心模組

這個模組實現了基於 LangChain 的問答鏈功能，負責：
1. 初始化 OpenAI LLM 模型
2. 創建和配置問答提示模板
3. 構建問答處理鏈
4. 處理文檔查詢和答案生成
5. 管理上下文長度限制

主要功能：
- 支持 GPT-3.5-turbo 模型
- 自定義提示模板
- 上下文長度優化
- 多文檔答案生成

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
from typing import List, Dict
import os
import logging

# LangChain 相關導入
from langchain_openai import ChatOpenAI
from langchain.chains import RetrievalQAWithSourcesChain
from langchain.prompts import PromptTemplate, ChatPromptTemplate
from langchain.schema import Document
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class QAChain:
    """
    問答鏈類
    
    負責管理整個問答流程，包括：
    - LLM 模型初始化
    - 提示模板配置
    - 問答鏈構建
    - 答案生成和優化
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
        
        # 創建聊天提示模板
        self.prompt = ChatPromptTemplate.from_messages([
            # 系統消息：定義 AI 助手的角色和行為準則
            ("system", """你是一個專業的助手，負責回答關於上傳文件的問題。
            請根據提供的文件內容來回答問題。如果問題與文件內容無關，請禮貌地說明。
            回答時請：
            1. 保持專業和準確
            2. 使用清晰的語言
            3. 如果可能，提供具體的例子或引用
            4. 如果不確定，請誠實說明"""),
            # 人類消息：包含文件內容和問題
            ("human", "文件內容：\n{context}\n\n問題：{question}")
        ])
        
        # 構建問答處理鏈
        self.chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | self.prompt
            | self.llm
            | StrOutputParser()
        )

    def _create_chain(self, retriever):
        """
        創建問答鏈（內部方法）
        
        使用 RetrievalQAWithSourcesChain 創建帶有來源的問答鏈
        
        Args:
            retriever: 文檔檢索器，用於獲取相關文檔
        """
        # 定義問答提示模板
        template = """使用以下上下文來回答問題。如果你不知道答案，就說你不知道，不要試圖編造答案。

上下文:
{context}

問題: {question}

請用中文回答，並列出參考來源。"""

        # 創建提示模板
        PROMPT = PromptTemplate(
            template=template,
            input_variables=["context", "question"]
        )

        # 創建帶有來源的問答鏈
        self.chain = RetrievalQAWithSourcesChain.from_chain_type(
            llm=self.llm,
            chain_type="stuff",  # 使用 stuff 方法處理文檔
            retriever=retriever,
            return_source_documents=True,  # 返回源文檔
            chain_type_kwargs={"prompt": PROMPT}
        )

    def get_answer(self, query: str, documents: List[Document]) -> Dict:
        """
        獲取問題答案
        
        這是主要的問答方法，流程如下：
        1. 檢查問答鏈是否已初始化
        2. 限制上下文長度以避免 token 限制
        3. 使用 LLM 生成答案
        4. 返回答案和來源信息
        
        Args:
            query (str): 用戶的問題
            documents (List[Document]): 相關文檔列表
            
        Returns:
            Dict: 包含答案和來源信息的字典
        """
        # 如果問答鏈未初始化，創建一個簡單的檢索器
        if not self.chain:
            from langchain.schema.retriever import BaseRetriever
            
            # 創建簡單的文檔檢索器
            class SimpleRetriever(BaseRetriever):
                def __init__(self, docs):
                    self.docs = docs
                def get_relevant_documents(self, query):
                    return self.docs
            
            retriever = SimpleRetriever(documents)
            self._create_chain(retriever)

        # 限制 context 長度，避免超過 token 限制
        max_context_length = 8000  # 預留空間給 prompt 和問題
        context_parts = []
        current_length = 0
        
        # 遍歷文檔，控制總長度
        for doc in documents:
            doc_content = doc.page_content
            if current_length + len(doc_content) > max_context_length:
                # 如果加上這個文件會超過限制，就截斷
                remaining_length = max_context_length - current_length
                if remaining_length > 100:  # 至少保留 100 字符
                    doc_content = doc_content[:remaining_length] + "..."
                else:
                    break
            
            context_parts.append(doc_content)
            current_length += len(doc_content)
        
        # 合併 context
        context = "\n\n".join(context_parts)
        
        logger.debug(f"Context length: {len(context)} characters")
        
        # 使用鏈式調用生成答案
        result = self.chain.invoke({"context": context, "question": query})
        
        # 返回答案和來源信息
        return {
            "answer": result,
            "sources": [doc.metadata.get("source", "Unknown") for doc in documents]
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
        return self.chain.invoke({"context": context, "question": question}) 