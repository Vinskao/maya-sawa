"""
Markdown Q&A System - 配置管理器

這個模組負責統一管理所有 JSON 配置文件，包括：
1. 規則配置 (rules.json)
2. 關鍵詞配置 (keywords.json)
3. 提示模板配置 (prompts.json)
4. 常量配置 (constants.json)

作者: Maya Sawa Team
版本: 0.1.0
"""

import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    配置管理器，統一管理所有 JSON 配置文件
    """
    
    def __init__(self):
        """
        初始化配置管理器
        """
        self.config_dir = os.path.dirname(__file__)
        self.data_dir = os.path.join(os.path.dirname(self.config_dir), 'data')
        self._rules = None
        self._keywords = None
        self._prompts = None
        self._constants = None
    
    def _load_json_file(self, filename: str) -> Dict[str, Any]:
        """
        載入 JSON 配置文件
        
        Args:
            filename (str): 文件名
            
        Returns:
            Dict[str, Any]: 配置數據
        """
        file_path = os.path.join(self.data_dir, filename)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                logger.debug(f"成功載入配置文件: {filename}")
                return data
        except Exception as e:
            logger.error(f"載入配置文件 {filename} 失敗: {e} at {file_path}")
            return {}
    
    @property
    def rules(self) -> Dict[str, Any]:
        """
        獲取規則配置
        
        Returns:
            Dict[str, Any]: 規則配置
        """
        if self._rules is None:
            self._rules = self._load_json_file('rules.json')
        return self._rules
    
    @property
    def keywords(self) -> Dict[str, Any]:
        """
        獲取關鍵詞配置
        
        Returns:
            Dict[str, Any]: 關鍵詞配置
        """
        if self._keywords is None:
            self._keywords = self._load_json_file('keywords.json')
        return self._keywords
    
    @property
    def prompts(self) -> Dict[str, Any]:
        """
        獲取提示模板配置
        
        Returns:
            Dict[str, Any]: 提示模板配置
        """
        if self._prompts is None:
            self._prompts = self._load_json_file('prompts.json')
        return self._prompts
    
    @property
    def constants(self) -> Dict[str, Any]:
        """
        獲取常量配置
        
        Returns:
            Dict[str, Any]: 常量配置
        """
        if self._constants is None:
            self._constants = self._load_json_file('constants.json')
        return self._constants
    
    def get_rule(self, key: str) -> str:
        """
        獲取特定規則
        
        Args:
            key (str): 規則鍵名
            
        Returns:
            str: 規則內容
        """
        return self.rules.get(key, "")
    
    def get_keywords(self, category: str) -> list:
        """
        獲取特定類別的關鍵詞
        
        Args:
            category (str): 關鍵詞類別
            
        Returns:
            list: 關鍵詞列表
        """
        return self.keywords.get(category, [])
    
    def get_prompt(self, key: str) -> str:
        """
        獲取特定提示模板
        
        Args:
            key (str): 提示模板鍵名
            
        Returns:
            str: 提示模板內容
        """
        return self.prompts.get(key, "")
    
    def get_constant(self, key: str) -> Any:
        """
        獲取特定常量
        
        Args:
            key (str): 常量鍵名
            
        Returns:
            Any: 常量值
        """
        return self.constants.get(key)
    
    def get_power_comparison_text(self, comparison: str) -> str:
        """
        獲取戰力比較文本
        
        Args:
            comparison (str): 比較結果 ("higher", "lower", "equal")
            
        Returns:
            str: 比較文本
        """
        mapping = self.constants.get("POWER_COMPARISON_MAPPING", {})
        return mapping.get(comparison, "未知")
    
    def get_gender_instruction(self, gender: str) -> str:
        """
        獲取性別說明
        
        Args:
            gender (str): 性別 ("M", "F")
            
        Returns:
            str: 性別說明
        """
        mapping = self.constants.get("GENDER_MAPPING", {})
        return mapping.get(gender, mapping.get("DEFAULT", ""))
    
    def get_image_url(self, template_key: str, base_url: str, name: str) -> str:
        """
        獲取圖片 URL
        
        Args:
            template_key (str): 模板鍵名
            base_url (str): 基礎 URL
            name (str): 角色名稱
            
        Returns:
            str: 圖片 URL
        """
        templates = self.constants.get("IMAGE_URL_TEMPLATES", {})
        template = templates.get(template_key, "")
        return template.format(base=base_url, name=name)
    
    def get_global_rules(self, self_name: str = None) -> str:
        """
        獲取全局規則文本
        
        Args:
            self_name (str): 角色名稱，用於替換規則中的佔位符
            
        Returns:
            str: 全局規則文本
        """
        global_rules = self.prompts.get("GLOBAL_RULES", {})
        if not global_rules:
            return ""
        
        rules_text = []
        for rule_key, rule_content in global_rules.items():
            if self_name and "{self_name}" in rule_content:
                rule_content = rule_content.format(self_name=self_name)
            rules_text.append(f"• {rule_content}")
        
        return "\n".join(rules_text)
    
    def reload_configs(self):
        """
        重新載入所有配置文件
        """
        logger.info("重新載入所有配置文件")
        self._rules = None
        self._keywords = None
        self._prompts = None
        self._constants = None

# 全局配置管理器實例
config_manager = ConfigManager() 