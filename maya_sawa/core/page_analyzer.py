import logging
from typing import Dict

from maya_sawa.core.qa_chain import QAChain

logger = logging.getLogger(__name__)


class PageAnalyzer:
    """簡易頁面文字分析器，重用現有 QAChain"""

    def __init__(self):
        self.qa_chain = QAChain()

    def analyze_page_content(self, content: str, analysis_type: str = "summary", language: str = "chinese") -> Dict:
        """分析頁面文字內容並回傳結果字典

        Args:
            content: 頁面純文字內容
            analysis_type: summary | key_points | technical | qa
            language: chinese | english
        """
        ALLOWED = {"summary", "key_points", "technical", "qa"}
        if analysis_type not in ALLOWED:
            analysis_type = "summary"

        # 避免內容過長導致 token 超限
        MAX_LEN = 3000
        content = (content[:MAX_LEN] + "...") if len(content) > MAX_LEN else content

        # 根據語言選擇 prompt
        if language.lower() == "english":
            prompts = {
                "summary": f"Please provide a summary of no more than 200 words for the following web page content:\n\n{content}",
                "key_points": f"Please extract the key points from the following web page content in a bulleted format:\n\n{content}",
                "technical": f"Please analyze the technical concepts or specialized terms in the following web page content:\n\n{content}",
                "qa": f"Based on the following web page content, generate 3 related questions:\n\n{content}",
            }
        else:
            # 中文模式（預設）
            prompts = {
                "summary": f"請為以下網頁內容提供不超過 200 字的摘要：\n\n{content}",
                "key_points": f"請以條列方式提取以下網頁內容的重點：\n\n{content}",
                "technical": f"請分析以下網頁內容中的技術概念或專有名詞：\n\n{content}",
                "qa": f"基於以下網頁內容，生成 3 個相關問題：\n\n{content}",
            }
        
        prompt = prompts[analysis_type]

        logger.info("PageAnalyzer 開始分析：type=%s len=%s language=%s", analysis_type, len(content), language)
        try:
            # 直接呼叫底層 LLM，避免注入角色個人檔案
            response = self.qa_chain.llm.invoke(prompt)
            answer = response.content if hasattr(response, "content") else str(response)
            return {
                "success": True,
                "analysis_type": analysis_type,
                "answer": answer,
                "content_length": len(content),
                "language": language,
            }
        except Exception as e:
            logger.error("PageAnalyzer 失敗: %s", e)
            return {"success": False, "error": str(e)}
