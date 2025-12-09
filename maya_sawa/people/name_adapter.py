"""
Markdown Q&A System - 名稱格式適配器

這個模組負責名稱格式轉換、大小寫處理、API查詢格式適配等功能。

作者: Maya Sawa Team
版本: 0.1.0
"""

import logging
import re
from typing import List

# 本地導入
from maya_sawa.core.config.config_manager import config_manager

logger = logging.getLogger(__name__)

class NameAdapter:
    """
    名稱格式適配器，處理名稱大小寫轉換和API查詢格式
    """
    
    def __init__(self):
        """
        初始化名稱適配器
        """
        # 從配置管理器獲取識別模式
        self.recognition_patterns = config_manager.get_keywords("RECOGNITION_PATTERNS")
    
    def normalize_name(self, name: str) -> str:
        """
        標準化名稱格式，將名稱轉換為API查詢格式（首字母大寫）
        
        Args:
            name (str): 原始名稱
            
        Returns:
            str: 標準化後的名稱
        """
        if not name:
            return name
            
        # 清理名稱
        clean_name = name.strip()

        # 移除常見標點符號（包括中英文）
        clean_name = re.sub(r"[\s,，。!！?？;；:：'\"\(\)\[\]{}]+", "", clean_name)
        
        # 不再使用特殊名稱映射，直接首字大寫
        if len(clean_name) > 0:
            return clean_name[0].upper() + clean_name[1:].lower()
        
        return clean_name
    
    def normalize_names(self, names: List[str]) -> List[str]:
        """
        批量標準化名稱列表
        
        Args:
            names (List[str]): 原始名稱列表
            
        Returns:
            List[str]: 標準化後的名稱列表
        """
        normalized = []
        for name in names:
            normalized_name = self.normalize_name(name)
            if normalized_name and normalized_name not in normalized:
                normalized.append(normalized_name)
        return normalized
    
    def extract_names_from_recognition_question(self, question: str) -> List[str]:
        """
        從認識類問題中提取名稱
        
        Args:
            question (str): 問題文本
            
        Returns:
            List[str]: 提取到的名稱列表
        """
        extracted_names = []
        
        for pattern in self.recognition_patterns:
            matches = re.findall(pattern, question, re.IGNORECASE)
            for match in matches:
                # 清理匹配到的名稱
                name = match.strip()
                if name:
                    # 移除可能的標點符號
                    name = re.sub(r'[，。！？、；：?？!！""\'\'（）【】,]', '', name)
                    if name:
                        # 過濾非角色詞
                        if name in ["你", "妳"]:
                            continue
                        extracted_names.append(name)
        
        # 標準化提取到的名稱
        normalized_names = self.normalize_names(extracted_names)
        logger.info(f"從認識類問題中提取到名稱: {extracted_names} -> {normalized_names}")
        
        return normalized_names
    
    def is_recognition_question(self, question: str) -> bool:
        """
        判斷是否為認識類問題
        
        Args:
            question (str): 問題文本
            
        Returns:
            bool: 是否為認識類問題
        """
        for pattern in self.recognition_patterns:
            if re.search(pattern, question, re.IGNORECASE):
                return True
        return False
    
    def create_recognition_response(self, names: List[str], found_names: List[str], not_found_names: List[str]) -> str:
        """
        創建認識類問題的回答
        
        Args:
            names (List[str]): 詢問的所有名稱
            found_names (List[str]): 找到的名稱
            not_found_names (List[str]): 未找到的名稱
            
        Returns:
            str: 認識類問題的回答
        """
        if not names:
            return "你在問什麼？我聽不懂。"
        
        response_parts = []
        
        # 處理找到的名稱
        if found_names:
            if len(found_names) == 1:
                response_parts.append(f"認識啊，{found_names[0]} 我當然認識。")
            else:
                response_parts.append(f"認識啊，{', '.join(found_names)} 我都認識。")
        
        # 處理未找到的名稱
        if not_found_names:
            if len(not_found_names) == 1:
                response_parts.append(f"至於 {not_found_names[0]}？沒聽過這個人。")
            else:
                response_parts.append(f"至於 {', '.join(not_found_names)}？這些人都沒聽過。")
        
        return " ".join(response_parts)
    
    def adapt_query_for_api(self, query: str) -> str:
        """
        適配查詢文本，將其中的名稱轉換為API查詢格式
        
        Args:
            query (str): 原始查詢文本
            
        Returns:
            str: 適配後的查詢文本
        """
        # 這裡可以實現更複雜的文本替換邏輯
        # 目前先返回原始文本，具體的適配邏輯可以在使用時實現
        return query 