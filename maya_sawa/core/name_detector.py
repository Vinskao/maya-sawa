"""
Markdown Q&A System - 人名偵測模組

這個模組負責人名偵測、AI抽名、identity問題判斷等功能。

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import logging
from typing import List, Optional

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class NameDetector:
    """
    負責人名偵測、AI抽名、identity問題判斷
    """
    
    def __init__(self, llm=None, get_known_names_func=None):
        """
        初始化人名偵測器
        
        Args:
            llm: LLM 實例，用於 AI 抽名
            get_known_names_func: 取得已知角色名單的函數
        """
        self.llm = llm
        self.get_known_names_func = get_known_names_func
        self._original_extracted_names = []
        self._request_detailed = False

    def extract_names_with_ai(self, question: str) -> List[str]:
        """
        使用 AI 從問題中提取所有可能的人名
        
        Args:
            question (str): 用戶問題
            
        Returns:
            List[str]: 提取到的所有可能人名列表
        """
        # 記錄原始提取的人名，用於後續處理
        self._original_extracted_names = []
        
        # 個人資訊相關關鍵詞 (中英雙語)
        personal_keywords = [
            # Chinese
            "身高", "體重", "年齡", "生日", "出生", "身材", "胸部", "臀部", 
            "興趣", "喜歡", "討厭", "最愛", "食物", "個性", "性格", "職業", 
            "工作", "種族", "編號", "代號", "原名", "部隊", "部門", "陣營",
            "戰鬥力", "物理", "魔法", "武器", "戰鬥", "屬性", "性別", "電子郵件",
            "後宮", "已生育", "體態", "別名", "原部隊", "是誰", 
            "誰是", "怎樣", "什麼人", "有什麼特徵", "資料", "資訊", "個人",
            "認識", "知道", "見過",

            # English
            "who is", "who are", "tell me about", "what is", "what are",
            "height", "weight", "age", "birthday", "birth", "body",
            "interests", "likes", "dislikes", "favorite", "personality",
            "occupation", "job", "race", "faction", "combat power",
            "weapon", "attributes", "gender", "email", "do you know",
            "have you met", "recognize"
        ]
        
        # 詳細資料關鍵詞
        detailed_keywords = [
            "詳細", "完整", "全部", "所有", "具體", "詳細資料", "完整資料", 
            "所有資料", "具體資料", "詳細資訊", "完整資訊", "所有資訊", "具體資訊"
        ]
        
        # 檢查是否要求詳細資料
        self._request_detailed = any(keyword in question for keyword in detailed_keywords)
        
        # 檢查是否包含個人資訊關鍵詞
        has_personal_keyword = any(keyword in question for keyword in personal_keywords)
        
        if not has_personal_keyword:
            return []  # 沒有個人資訊關鍵詞，返回空列表
        
        # 如果有個人資訊關鍵詞，就進行 AI 抽名（不管是否明確提到已知角色）
        logger.info("檢測到個人資訊關鍵詞，進行 AI 抽名")
        
        # 使用 AI 提取人名
        name_extraction_prompt = f"""
請從以下問題中精確找出所有「明確在問題文字中出現」的人名（角色名稱）。格式要求如下：

1. 僅回傳問題中出現過的人名
2. 不要加入任何未出現的人名
3. 如果完全沒有人名，就返回空字串
4. 不要進行任何猜測或補全
5. 結果請僅用英文逗號分隔人名，不要包含任何敘述或格式
6. 如果問題是身份詢問（如「你是誰？」「你叫什麼？」等），請返回 "Maya"

範例：
- 問題：「你是誰？」→ 回應：「Maya」
- 問題：「你叫什麼名字？」→ 回應：「Maya」
- 問題：「Alice的身高是多少？」→ 回應：「Alice」
- 問題：「請比較 Bob 和 Carol」→ 回應：「Bob,Carol」
- 問題：「你認識 Wavo 跟 Alice 嗎？」→ 回應：「Wavo,Alice」

問題：{question}
"""
        
        try:
            response = self.llm.invoke(name_extraction_prompt)
            if hasattr(response, 'content'):
                response = response.content
            
            # 解析 AI 返回的人名
            if response and response.strip():
                names = [name.strip() for name in response.split(',') if name.strip()]
                logger.info(f"AI 提取到的人名: {names}")
                
                # 記錄原始提取的人名
                self._original_extracted_names = names
                
                # 驗證提取的人名是否真的在問題中出現
                validated_names = []
                known_names = self.get_known_names_func() if self.get_known_names_func else []
                
                for name in names:
                    # 清理人名（移除引號等）
                    clean_name = name.strip().strip('"').strip("'")
                    
                    # 特殊處理：Maya 需額外驗證——只有在問題中出現 "maya" 或明確為對「你」的身份詢問時才自動通過
                    if clean_name.lower() == "maya":
                        identity_pronouns = ["你是", "你叫", "我是誰", "我叫什麼"]
                        # 若問題文本包含 "maya" 或任何第一人稱身份詢問關鍵詞，才視為有效
                        if "maya" in question.lower() or any(p in question for p in identity_pronouns):
                            validated_names.append(clean_name)
                            logger.info(f"驗證通過（系統內建角色）: {clean_name}")
                        else:
                            logger.warning(f"AI 提取到 'Maya' 但問題中未直接提及，也非身份詢問，已過濾")
                        continue
                    
                    # 檢查：1. 在問題中出現（主要驗證）
                    if clean_name.lower() in question.lower():
                        validated_names.append(clean_name)
                        if clean_name in known_names:
                            logger.info(f"驗證通過（已知角色）: {clean_name}")
                        else:
                            logger.info(f"驗證通過（未知角色，將嘗試獲取資料）: {clean_name}")
                    else:
                        logger.warning(f"AI 提取到的人名 '{name}' 在問題中未出現，已過濾")
                
                logger.info(f"驗證後的人名: {validated_names}")
                return validated_names
            else:
                logger.info("AI 沒有提取到任何人名")
                return []
                
        except Exception as e:
            logger.error(f"AI 提取人名時發生錯誤: {str(e)}")
            return []  # 如果 AI 提取失敗，返回空列表

    def detect_queried_name(self, question: str) -> Optional[str]:
        """
        偵測問題中是否提及某個人名（單一角色）
        
        Args:
            question (str): 用戶問題
            
        Returns:
            Optional[str]: 檢測到的角色名稱，如果是 Maya 或沒有檢測到則返回 None
        """
        detected_names = self.detect_all_queried_names(question)
        
        # 如果只檢測到一個角色，返回該角色
        if len(detected_names) == 1:
            return detected_names[0]
        
        # 如果檢測到多個角色，優先返回非 Maya 的角色
        non_maya_names = [name for name in detected_names if name.lower() != "maya"]
        if non_maya_names:
            return non_maya_names[0]  # 返回第一個非 Maya 的角色
        
        return None

    def detect_all_queried_names(self, question: str) -> List[str]:
        """
        偵測問題中是否提及多個人名（保持向後兼容）
        
        Args:
            question (str): 用戶問題
            
        Returns:
            List[str]: 檢測到的所有角色名稱列表
        """
        # 先使用 AI 提取人名
        extracted_names = self.extract_names_with_ai(question)
        
        # 檢查是否為關於 Maya 的身份詢問問題
        identity_questions = ["你是誰", "你叫什麼", "誰是maya", "誰是Maya", "誰是佐和", "誰是真夜"]
        is_maya_identity_question = any(keyword in question.lower() for keyword in identity_questions)
        
        # 只有在沒有提取到任何其他角色名稱，並且是身份詢問時，才將其視為對 Maya 的問題
        if not extracted_names and is_maya_identity_question:
            logger.info("檢測到純身份詢問問題（無其他角色），添加 Maya")
            extracted_names.append("Maya")
        
        # 如果 AI 直接返回了 "Maya"，也要處理
        if "Maya" in extracted_names:
            logger.info("AI 直接識別出身份詢問，包含 Maya")
        
        # 去重並返回
        unique_names = list(dict.fromkeys(extracted_names))  # 保持順序的去重
        logger.info(f"最終檢測到的角色名稱: {unique_names}")
        return unique_names

    def is_identity_question(self, question: str) -> bool:
        """
        判斷是否為身份詢問問題
        
        Args:
            question (str): 用戶問題
            
        Returns:
            bool: 是否為身份詢問問題
        """
        identity_questions = ["你是誰", "你叫什麼", "誰是maya", "誰是Maya", "誰是佐和", "誰是真夜"]
        return any(keyword in question.lower() for keyword in identity_questions)

    def get_original_extracted_names(self) -> List[str]:
        """
        獲取原始提取的人名（用於驗證失敗的情況）
        
        Returns:
            List[str]: 原始提取的人名列表
        """
        return self._original_extracted_names

    def is_request_detailed(self) -> bool:
        """
        檢查是否要求詳細資料
        
        Returns:
            bool: 是否要求詳細資料
        """
        return self._request_detailed 