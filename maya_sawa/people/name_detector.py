"""
Markdown Q&A System - 人名偵測模組

這個模組負責人名偵測、AI抽名、identity問題判斷等功能。

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import logging
from typing import List, Optional
import re

# 本地導入
from maya_sawa.core.config_manager import config_manager

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class NameDetector:
    """
    負責人名偵測、AI抽名、identity問題判斷
    """
    
    def __init__(self, llm=None, get_known_names_func=None, self_name: str = "Maya"):
        """
        初始化人名偵測器
        
        Args:
            llm: LLM 實例，用於 AI 抽名
            get_known_names_func: 取得已知角色名單的函數
        """
        self.llm = llm
        # 主角名稱（例如 Maya），可由外部注入
        self.self_name = self_name
        self._main_lower = self_name.lower()
        self.get_known_names_func = get_known_names_func
        self._original_extracted_names = []
        self._request_detailed = False

    def extract_names_with_ai(self, question: str) -> List[str]:
        """
        使用 AI 從問題中提取所有可能的人名
        """
        self._original_extracted_names = []
        
        # 從配置管理器獲取關鍵詞
        personal_keywords_chinese = config_manager.get_keywords("PERSONAL_KEYWORDS")["CHINESE"]
        personal_keywords_english = config_manager.get_keywords("PERSONAL_KEYWORDS")["ENGLISH"]
        personal_keywords = personal_keywords_chinese + personal_keywords_english
        
        detailed_keywords = config_manager.get_keywords("DETAILED_KEYWORDS")
        identity_keywords = config_manager.get_keywords("IDENTITY_KEYWORDS")
        
        self._request_detailed = any(keyword in question for keyword in detailed_keywords)
        has_personal_keyword = any(keyword in question for keyword in personal_keywords)
        if not has_personal_keyword:
            return []
        
        is_identity_question = any(keyword in question.lower() for keyword in identity_keywords)
        
        # 從配置管理器獲取提示模板
        name_extraction_prompt = config_manager.get_prompt("NAME_EXTRACTION_PROMPT").format(
            self_name=self.self_name,
            question=question
        )
        try:
            response = self.llm.invoke(name_extraction_prompt)
            if hasattr(response, 'content'):
                response = response.content
            validated_names = []
            if response and response.strip():
                names = [name.strip() for name in response.split(',') if name.strip()]
                logger.info(f"AI 提取到的人名: {names}")
                self._original_extracted_names = names
                known_names = self.get_known_names_func() if self.get_known_names_func else []
                for name in names:
                    clean_name = name.strip().strip('"').strip("'")
                    if clean_name.lower() == self._main_lower:
                        identity_pronouns = ["你是", "你叫", "我是誰", "我叫什麼"]
                        if self._main_lower in question.lower() or any(p in question for p in identity_pronouns):
                            validated_names.append(self.self_name)
                            logger.info(f"驗證通過（系統內建角色）: {self.self_name}")
                        else:
                            logger.warning(f"AI 提取到 '{self.self_name}' 但問題中未直接提及，也非身份詢問，已過濾")
                        continue
                    if clean_name.lower() in question.lower():
                        validated_names.append(clean_name)
                        if clean_name in known_names:
                            logger.info(f"驗證通過（已知角色）: {clean_name}")
                        else:
                            logger.info(f"驗證通過（未知角色，將嘗試獲取資料）: {clean_name}")
                    else:
                        logger.warning(f"AI 提取到的人名 '{name}' 在問題中未出現，已過濾")
            else:
                logger.info("AI 沒有提取到任何人名")
            # --- 強化補抓所有「誰是X」和「who is X」 ---
            pattern_tw = re.findall(r"誰是\s*([A-Za-z\u4e00-\u9fa5_\-0-9]+)", question)
            pattern_en = re.findall(r"who is\s*([A-Za-z\u4e00-\u9fa5_\-0-9]+)", question, re.IGNORECASE)
            pattern_tw2 = re.findall(r"誰是\s*([A-Za-z\u4e00-\u9fa5_\-0-9]+)[？?\s,，。!！]?", question)
            pattern_en2 = re.findall(r"who is\s*([A-Za-z\u4e00-\u9fa5_\-0-9]+)[?？\s,，。!！]?", question, re.IGNORECASE)
            all_patterns = pattern_tw + pattern_en + pattern_tw2 + pattern_en2
            for n in all_patterns:
                n_clean = n.strip().strip('"').strip("'")
                n_clean = re.sub(r'[，。！？、；：?？!！""\'\'（）【】,\s]', '', n_clean)
                if n_clean and n_clean not in validated_names and n_clean not in [self.self_name, "你", "妳", "you", "You"]:
                    validated_names.append(n_clean)
            # 如果有 identity question 關鍵詞，補上 self_name
            if is_identity_question and self.self_name not in validated_names:
                validated_names.insert(0, self.self_name)
            validated_names = list(dict.fromkeys(validated_names))  # 去重保順序
            logger.info(f"最終補抓後人名: {validated_names}")
            return validated_names
        except Exception as e:
            logger.error(f"AI 提取人名時發生錯誤: {str(e)}")
            return []

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
        non_self_names = [name for name in detected_names if name.lower() != self._main_lower]
        if non_self_names:
            return non_self_names[0]  # 返回第一個非 Maya 的角色
        
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

        # === NEW FALLBACK: 若 AI 未成功提取，嘗試從已知角色名單中直接掃描 ===
        if not extracted_names:
            # 1) 特殊處理 '誰是 X、Y' / 'who is X, Y' 這類列表式問題
            pattern_tw = re.search(r"誰是([A-Za-z\u4e00-\u9fa5、,，\s]+)", question)
            pattern_en = re.search(r"who is ([A-Za-z\u4e00-\u9fa5,\s]+)", question, re.IGNORECASE)
            names_str = None
            if pattern_tw:
                names_str = pattern_tw.group(1)
            elif pattern_en:
                names_str = pattern_en.group(1)
            if names_str:
                # 使用常見分隔符切分
                possible_names = re.split(r"[、,，和及與&\s]+", names_str)
                for n in possible_names:
                    n_clean = n.strip()
                    if not n_clean:
                        continue
                    # 將第二人稱代詞映射為 name
                    if n_clean in ["你", "妳", "you", "You"]:
                        extracted_names.append(self.self_name)
                        continue
                    if n_clean not in ["你", "妳"]:
                        extracted_names.append(n_clean)
                logger.info(f"透過 '誰是/Who is' 解析捕捉到人名: {extracted_names}")

        # 2) 若仍無結果且 get_known_names_func 可用，掃描已知人名
        if not extracted_names and self.get_known_names_func:
            known_names = self.get_known_names_func()
            # 依照在問題中出現的順序保留順序
            lowered_question = question.lower()
            matched_names = []
            for name in known_names:
                if name and name.lower() != self._main_lower and name.lower() in lowered_question:
                    matched_names.append(name)
            if matched_names:
                extracted_names.extend(matched_names)
                logger.info(f"透過字面掃描補捉到人名: {matched_names}")

        # 檢查是否為關於 name 的身份詢問問題
        lower_self = self._main_lower
        identity_questions = [
            "你是誰", "你叫什麼",
            f"誰是{lower_self}", f"誰是{self.self_name}",  # 中文自我名稱
            f"who is {lower_self}", f"who is {self.self_name}",
            "誰是ai", "誰是AI", "ai是誰", "AI是誰", "who is ai", "who is AI"
        ]
        is_maya_identity_question = any(keyword in question.lower() for keyword in identity_questions)

        # 只有在沒有提取到任何其他角色名稱，並且是身份詢問時，才將其視為對 name 的問題
        if not extracted_names and is_maya_identity_question:
            extracted_names.append(self.self_name)

        if self.self_name in extracted_names:
            logger.info(f"AI 直接識別出身份詢問，包含 {self.self_name}")

        # === 若問題中直接以第二人稱提及，補上 name ===
        pronouns = ["你", "妳", "you", "You", "u", "U"]
        if any(p in question for p in pronouns) and self.self_name not in extracted_names:
            logger.info("問題中包含第二人稱，補充主角至角色名單")
            extracted_names.insert(0, self.self_name)

        # 去重並返回
        unique_names = list(dict.fromkeys(extracted_names))
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
        lower_self = self._main_lower
        identity_questions = [
            "你是誰", "你叫什麼",
            f"誰是{lower_self}", f"誰是{self.self_name}",
            f"who is {lower_self}", f"who is {self.self_name}",
            "誰是ai", "誰是AI", "ai是誰", "AI是誰", "who is ai", "who is AI"
        ]
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