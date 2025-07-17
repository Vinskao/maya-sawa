"""
Markdown Q&A System - 個性提示建構模組

這個模組負責統一管理Maya個性描述與產生個性化prompt。

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import logging
import os
import json
try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore
from typing import Dict, List, Optional

# 本地導入
from maya_sawa.core.config import Config
from maya_sawa.core.config_manager import config_manager
from .profile_manager import ProfileManager

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

# 修改：支援動態 self_name
class PersonalityPromptBuilder:
    """
    統一管理self_name個性描述與產生個性化prompt
    """
    
    def __init__(self, self_name: str = "Maya", profile_manager: Optional[ProfileManager] = None):
        """
        初始化個性提示建構器
        """
        # 主角名稱（可由外部注入）
        self.self_name = self_name
        self._main_lower = self_name.lower()

        # 角色資料管理器（可由外部注入，便於重用）
        self.profile_manager = profile_manager or ProfileManager()

        # 添加戰力和武器信息緩存
        self._power_weapon_cache = {}
        self._cache_duration = 300  # 5分鐘緩存

        # 初始化時不載入 personality，避免顯示錯誤角色的個性
        self.personality = ""

        # 使用配置管理器載入規則
        self.rules = config_manager.rules

    def create_personality_prompt(self, query: str, additional_context: str = "") -> str:
        """
        創建統一的個性提示模板
        
        Args:
            query (str): 用戶的問題
            additional_context (str): 額外的上下文信息
            
        Returns:
            str: 格式化的個性提示
        """
        # 確保 personality 已載入
        if not self.personality:
            self.refresh_personality()
        
        return f"""{self.personality}

有人問你「{query}」。

{additional_context}

記住：你是{self.self_name}，用你的個性回答問題。"""

    def create_dynamic_prompt(self, profile_summary: str):
        """
        創建動態提示模板，包含最新的個人資料
        
        Args:
            profile_summary (str): 個人資料摘要
            
        Returns:
            str: 動態創建的提示模板
        """
        # 確保 personality 已載入
        if not self.personality:
            self.refresh_personality()
        
        return f"""{self.personality}

個人資料如下：
{profile_summary}
"""

    def _get_gender_instruction(self, profile_summary: str) -> str:
        """
        根據 profile_summary 內容自動判斷性別，回傳性別說明
        """
        gender = None
        # 嘗試從 profile_summary 直接抓性別
        if '性別：' in profile_summary:
            idx = profile_summary.find('性別：')
            gender_str = profile_summary[idx+3:idx+5]
            if '男' in gender_str:
                gender = 'M'
            elif '女' in gender_str:
                gender = 'F'
        # fallback: 嘗試從英文 Gender
        elif 'Gender:' in profile_summary:
            idx = profile_summary.find('Gender:')
            gender_str = profile_summary[idx+7:idx+10].strip().lower()
            if 'm' in gender_str:
                gender = 'M'
            elif 'f' in gender_str:
                gender = 'F'
        # fallback: 直接抓 profile_manager
        if not gender and hasattr(self.profile_manager, 'fetch_profile'):
            profile = self.profile_manager.fetch_profile(self.self_name)
            if profile and profile.get('gender'):
                g = profile['gender'].strip().upper()
                if g.startswith('M'):
                    gender = 'M'
                elif g.startswith('F'):
                    gender = 'F'
        
        # 使用配置管理器獲取性別說明
        return config_manager.get_gender_instruction(gender or 'DEFAULT')

    def create_identity_prompt(self, query: str, profile_summary: str, for_self: bool = True) -> str:
        # 確保 personality 已載入
        if not self.personality:
            self.refresh_personality()
        
        # 身份問題只使用自己對自己的認知
        personality_text = self.parse_personality(for_self=True)
        gender_instruction = self._get_gender_instruction(profile_summary)
        
        if for_self:
            # 使用配置管理器獲取提示模板
            template = config_manager.get_prompt("IDENTITY_PROMPT_TEMPLATE")["FOR_SELF"]
            return template.format(
                personality_text=personality_text,
                gender_instruction=gender_instruction,
                query=query,
                profile_summary=profile_summary,
                self_name=self.self_name
            )
        else:
            # 使用配置管理器獲取提示模板
            template = config_manager.get_prompt("IDENTITY_PROMPT_TEMPLATE")["FOR_OTHER"]
            image_rules = self.rules['IMAGE_RULES'].format(base=Config.PUBLIC_API_BASE_URL).replace('[角色名]', self.self_name)
            return template.format(
                target_name=self.self_name,
                personality_text=personality_text,
                gender_instruction=gender_instruction,
                profile_summary=profile_summary,
                image_rules=image_rules
            )

    def create_other_identity_prompt(self, query: str, profile_summary: str, target_name: str) -> str:
        personality_text = self.parse_personality(for_self=False)
        return f"""請根據下列資料，以第三人稱評論 {target_name}，3~5 句，評論要有個性、不要像在做報告。

{target_name} 的個性：{personality_text}

=== {target_name} 的資料 ===
{profile_summary}

⚠ 回答要求：
1. 只能評論 {target_name}，不要提及自己。
2. 必須附上圖片連結。
3. 不要重複本段文字或提及「回答規則」四字。
4. 內容必須基於資料，不得憑空捏造。
"""

    def create_multi_character_prompt(self, query: str, combined_other_profiles: str, character_names: List[str] = None) -> str:
        """
        創建多角色評論的個性提示
        
        Args:
            query (str): 用戶的問題
            combined_other_profiles (str): 其他角色的資料摘要
            character_names (List[str]): 角色名稱列表，用於獲取戰力和武器信息
            
        Returns:
            str: 多角色評論的個性提示
        """
        # === 戰力與武器資訊區塊 ===
        power_weapon_info = ""
        image_links_block = ""
        if character_names:
            power_weapon_info = "\n\n戰力與武器信息：\n"
            image_links_block = "\n\n圖片連結：\n"
            for name in character_names:
                if name.lower() == self._main_lower:
                    continue

                # 動態取得戰力與武器
                info = self.compare_power_and_get_weapons(name)
                if info["power_comparison"]:
                    comparison_text = config_manager.get_power_comparison_text(info["power_comparison"])
                    power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                else:
                    power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"

                # 使用配置管理器獲取圖片 URL 模板
                image_links_block += (
                    f"\n範例：\n{config_manager.get_image_url('NORMAL', Config.PUBLIC_API_BASE_URL, name)}\n"
                    f"{config_manager.get_image_url('FIGHTING', Config.PUBLIC_API_BASE_URL, name)}\n"
                    f"{config_manager.get_image_url('RUINED', Config.PUBLIC_API_BASE_URL, name)}\n"
                    f"{config_manager.get_image_url('RAVISHING', Config.PUBLIC_API_BASE_URL, name)}\n"
                )
 
        # === 最終提示 ===
        # 確保 personality 已載入
        if not self.personality:
            self.refresh_personality()
        
        return """你是{self_name}，{personality}

有人問你「{query}」。

關於所有相關角色（包括自己，基於實際資料）：

{combined_other_profiles}{power_weapon_info}{image_links_block}

### 回答規則
1. {data_based_rules}
2. **逐一表達你對每位角色的看法**（每位3~5句），包括對自己的看法，不要描述角色之間的互動。必須回答所有提到的角色。
3. {image_rules}
4. **嚴禁對其他角色使用第二人稱「你」**，{gender_rules}
5. {power_rules}
6. {no_output_rules}

**重要提醒**：戰力比較已在資料中明確標示，必須嚴格按照戰力規則調整語氣！
""".format(
            self_name=self.self_name,
            personality=self.personality,
            query=query,
            combined_other_profiles=combined_other_profiles,
            power_weapon_info=power_weapon_info,
            image_links_block=image_links_block,
            data_based_rules=self.rules['DATA_BASED_RULES'],
            image_rules=self.rules['IMAGE_RULES'].format(base=Config.PUBLIC_API_BASE_URL),
            gender_rules=self.rules['GENDER_RULES'],
            power_rules=self.rules['POWER_RULES'],
            no_output_rules=self.rules['NO_OUTPUT_RULES']
        )

    def create_summary_prompt(self, query: str, combined_profiles: str, character_names: List[str] = None) -> str:
        """
        創建總結評論的個性提示
        
        Args:
            query (str): 用戶的問題
            combined_profiles (str): 角色資料摘要
            character_names (List[str]): 角色名稱列表，用於獲取戰力和武器信息
            
        Returns:
            str: 總結評論的個性提示
        """
        # === 戰力與武器資訊 + 圖片連結 ===
        power_weapon_info = ""
        image_links_block = ""
        if character_names:
            power_weapon_info = "\n\n戰力與武器信息：\n"
            image_links_block = "\n\n圖片連結：\n"
            for name in character_names:
                if name.lower() == self._main_lower:
                    continue
                info = self.compare_power_and_get_weapons(name)
                if info["power_comparison"]:
                    comparison_text = config_manager.get_power_comparison_text(info["power_comparison"])
                    power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                else:
                    power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"

                # 使用配置管理器獲取圖片 URL 模板
                image_links_block += (
                    f"{config_manager.get_image_url('NORMAL', Config.PUBLIC_API_BASE_URL, name)}\n"
                    f"{config_manager.get_image_url('FIGHTING', Config.PUBLIC_API_BASE_URL, name)}\n"
                    f"{config_manager.get_image_url('RUINED', Config.PUBLIC_API_BASE_URL, name)}\n"
                    f"{config_manager.get_image_url('RAVISHING', Config.PUBLIC_API_BASE_URL, name)}\n"
                )
 
        return ("""你是{self_name}，{personality}

有人問你「{query}」。

以下是相關角色的資料：

{combined_profiles}{power_weapon_info}

### 回答規則1. 如果只有1位角色：依戰力規則評論並附圖片，不得提及其他角色2 若多位角色：逐一表達你對每位角色的看法，每位2句後緊跟圖片連結
3. {image_rules}
4. {gender_rules}
5. {power_rules}
6. {no_output_rules}
""").format(
            self_name=self.self_name,
            personality=self.personality,
            query=query,
            combined_profiles=combined_profiles,
            power_weapon_info=power_weapon_info,
            image_rules=self.rules['IMAGE_RULES'].format(base=Config.PUBLIC_API_BASE_URL),
            gender_rules=self.rules['GENDER_RULES'],
            power_rules=self.rules['POWER_RULES'],
            no_output_rules=self.rules['NO_OUTPUT_RULES']
        )

    def create_data_answer_prompt(self, query: str, profile_summary: str, target_name: str = None) -> str:
        identity_keywords = ["你是誰", "你叫什麼", "妳是誰", "妳叫什麼", "who are you, who r u", "who are u"]
        is_identity_question = any(keyword in query.lower() for keyword in identity_keywords)

        is_self = False
        if target_name is None or target_name.lower() == self.self_name.lower():
            is_self = True

        gender_instruction = self._get_gender_instruction(profile_summary)

        if is_identity_question or is_self:
            # 身份問題或關於自己的問題，絕對不插入圖片區塊
            personality_text = self.parse_personality(for_self=True)
            return f"""{personality_text}

{gender_instruction}

有人問你「{query}」。

{profile_summary}

記住：你是{self.self_name}，用你的個性回答問題。直接回答，不要說「有人問我...時，我會...說：」之類的開場白。"""
        else:
            # 只用她人對自己的認知，且 personality_text 必須明顯出現在最前面
            personality_text = self.parse_personality(for_self=False)
            image_block = self.rules['IMAGE_RULES'].format(base=Config.PUBLIC_API_BASE_URL).replace('[角色名]', target_name)
            
            # 獲取戰力比較信息
            power_info = ""
            if target_name:
                info = self.compare_power_and_get_weapons(target_name)
                if info["power_comparison"]:
                    comparison_text = config_manager.get_power_comparison_text(info["power_comparison"])
                    power_info = f"\n\n戰力信息：{target_name} 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
            
            return (f"""{personality_text}

{gender_instruction}

有人問你「{query}」。

{profile_summary}{power_info}

### 回答規則
1. {self.rules['DATA_BASED_RULES']}
2. {self.rules['GENDER_RULES']}
3. {self.rules['POWER_RULES']}
4. {self.rules['NATURAL_DIALOGUE_RULES']}
5. {self.rules['NO_OUTPUT_RULES']}

**重要提醒**：戰力比較已在資料中明確標示，必須嚴格按照戰力規則調整語氣！

""" + image_block + f"""

記住：你是{self.self_name}，用你的個性回答問題。""")

    def create_not_found_prompt(self, query: str, not_found_names: list = None) -> str:
        """
        創建找不到角色的個性提示
        
        Args:
            query (str): 用戶的問題
            not_found_names (list): 找不到的角色名稱列表
            
        Returns:
            str: 找不到角色的個性提示
        """
        # 使用配置管理器獲取提示模板
        if not_found_names:
            context = config_manager.get_prompt("NOT_FOUND_PROMPT")["WITH_NAMES"].format(names=', '.join(not_found_names))
        else:
            context = config_manager.get_prompt("NOT_FOUND_PROMPT")["WITHOUT_NAMES"]
        
        return self.create_personality_prompt(query, context)

    def create_self_and_other_prompt(self, query: str, self_profile: str, combined_other_profiles: str, other_names: List[str]):
        """
        自我 + 其他角色介紹提示
        當問題同時詢問「你以及其他角色時使用。
        
        Args:
            query (str): 使用者問題
            self_profile (str): Maya 個人資料摘要
            combined_other_profiles (str): 其他角色資料摘要
            other_names (List[str]): 其他角色名稱
        Returns:
            str: 完整 prompt
        """
        # 構建戰力與武器資訊區塊（針對其他角色）
        power_weapon_info = ""
        if other_names:
            power_weapon_info = "\n\n戰力與武器信息：\n"
            for name in other_names:
                if name.lower() == self._main_lower:
                    continue
                info = self.compare_power_and_get_weapons(name)
                if info["power_comparison"]:
                    comparison_text = config_manager.get_power_comparison_text(info["power_comparison"])
                    power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                else:
                    power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"

        # 確保 personality 已載入
        if not self.personality:
            self.refresh_personality()

        # 為每個其他角色生成具體的圖片規則
        specific_image_rules = ""
        for name in other_names:
            specific_image_rules += f"\n{name} 的圖片連結：\n"
            specific_image_rules += f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}.png\n"
            specific_image_rules += f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}Fighting.png\n"
            specific_image_rules += f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}Ruined.png\n"
            specific_image_rules += f"{Config.PUBLIC_API_BASE_URL}/images/people/Ravishing{name}.png\n"

        # 使用配置管理器獲取提示模板
        template = config_manager.get_prompt("SELF_AND_OTHER_PROMPT_TEMPLATE")
        return template.format(
            self_name=self.self_name,
            personality=self.personality,
            query=query,
            self_profile=self_profile,
            combined_other_profiles=combined_other_profiles,
            power_weapon_info=power_weapon_info,
            gender_rules=self.rules['GENDER_RULES'],
            image_rules=specific_image_rules,
            natural_dialogue_rules=self.rules['NATURAL_DIALOGUE_RULES'],
            power_rules=self.rules['POWER_RULES'],
            no_output_rules=self.rules['NO_OUTPUT_RULES']
        ) 

    def get_character_total_power(self, character_name: str) -> Optional[int]:
        """
        獲取角色的總戰力（包含武器加成）
        
        Args:
            character_name (str): 角色名稱
            
        Returns:
            Optional[int]: 總戰力數值，如果獲取失敗則返回 None
        """
        try:
            endpoint = config_manager.get_constant("API_ENDPOINTS")["PEOPLE_DAMAGE_WITH_WEAPON"]
            url = f"{Config.PUBLIC_API_BASE_URL}{endpoint}?name={character_name}"
            
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url)
                response.raise_for_status()
                # Some endpoints may return int directly or wrapped in JSON
                try:
                    total_power = int(response.text)
                except ValueError:
                    total_power = response.json()
                
                if isinstance(total_power, int):
                    logger.debug(f"獲取到 {character_name} 的總戰力: {total_power}")
                    return total_power
                else:
                    logger.warning(f"API 返回的戰力格式不正確: {total_power}")
                    return None
                    
        except Exception as e:
            logger.error(f"獲取 {character_name} 的總戰力失敗: {str(e)}")
            return None

    def get_character_weapons(self, character_name: str) -> List[Dict]:
        """
        獲取角色擁有的武器列表
        
        Args:
            character_name (str): 角色名稱
            
        Returns:
            List[Dict]: 武器列表，如果獲取失敗則返回空列表
        """
        try:
            endpoint = config_manager.get_constant("API_ENDPOINTS")["WEAPONS_BY_OWNER"]
            url = f"{Config.PUBLIC_API_BASE_URL}{endpoint}/{character_name}"
            
            with httpx.Client(timeout=10.0) as client:
                response = client.get(url)
                response.raise_for_status()
                weapons = response.json()
                
                if isinstance(weapons, list):
                    logger.debug(f"獲取到 {character_name} 的武器: {len(weapons)} 件")
                    return weapons
                else:
                    logger.warning(f"API 返回的武器格式不正確: {weapons}")
                    return []
                    
        except Exception as e:
            logger.error(f"獲取 {character_name} 的武器失敗: {str(e)}")
            return []

    def compare_power_and_get_weapons(self, character_name: str) -> Dict:
        """
        比較戰力並獲取武器信息
        
        Args:
            character_name (str): 角色名稱
            
        Returns:
            Dict: 包含戰力比較和武器信息的字典
        """
        # 獲取 self_name 的總戰力
        self_power = self.get_character_total_power(self.self_name)
        
        # 獲取目標角色的總戰力
        target_power = self.get_character_total_power(character_name)
        
        # 獲取目標角色的武器
        weapons = self.get_character_weapons(character_name)
        
        result = {
            "self_power": self_power,
            "target_power": target_power,
            "target_weapons": weapons,
            "power_comparison": None,
            "weapon_info": ""
        }
        
        # 計算戰力比較
        if self_power is not None and target_power is not None:
            if target_power > self_power:
                result["power_comparison"] = "higher"
            elif target_power < self_power:
                result["power_comparison"] = "lower"
            else:
                result["power_comparison"] = "equal"
        
        # 構建武器信息
        if weapons:
            weapon_names = [weapon.get('weapon', '未知武器') for weapon in weapons]
            result["weapon_info"] = f"擁有武器: {', '.join(weapon_names)}"
        else:
            result["weapon_info"] = "沒有武器"
        
        return result

    def create_people_search_prompt(self, query: str, found_people: list) -> str:
        """
        創建人員搜索結果的個性提示
        
        Args:
            query (str): 用戶的搜索問題
            found_people (list): 找到的人員列表，每個元素包含 name, profile, similarity
            
        Returns:
            str: 人員搜索結果的個性提示
        """
        # 構建找到的人員資料
        people_info = []
        character_names = []
        for person in found_people:
            people_info.append(f"""
{person['name']} (相似度: {person['similarity']}):
{person['profile']}
""")
            character_names.append(person['name'])
        
        combined_people_info = "\n".join(people_info)
        
        # 獲取戰力和武器信息
        power_weapon_info = ""
        if character_names:
            power_weapon_info = "\n\n戰力與武器信息：\n"
            for name in character_names:
                if name.lower() != self._main_lower:  # 跳過主角自己
                    info = self.compare_power_and_get_weapons(name)
                    if info["power_comparison"]:
                        comparison_text = config_manager.get_power_comparison_text(info["power_comparison"])
                        power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                    else:
                        power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"
        
        # 確保 personality 已載入
        if not self.personality:
            self.refresh_personality()
        
        # 使用配置管理器獲取提示模板
        template = config_manager.get_prompt("PEOPLE_SEARCH_PROMPT_TEMPLATE")
        return template.format(
            self_name=self.self_name,
            personality=self.personality,
            query=query,
            combined_people_info=combined_people_info,
            power_weapon_info=power_weapon_info,
            gender_rules=self.rules['GENDER_RULES'],
            power_rules=self.rules['POWER_RULES'],
            image_rules=self.rules['IMAGE_RULES'].format(base=Config.PUBLIC_API_BASE_URL),
            natural_dialogue_rules=self.rules['NATURAL_DIALOGUE_RULES'],
            no_output_rules=self.rules['NO_OUTPUT_RULES']
        ) 

    def parse_personality(self, for_self: bool = True) -> str:
        """
        解析 personality 欄位，根據 for_self 參數回傳對應文本
        """
        # 確保 personality 已載入
        if not self.personality:
            self.refresh_personality()
        
        if not self.personality:
            return ""
        parts = self.personality.split(";")
        other = ""
        self_ = ""
        for part in parts:
            if "她人對自己的認知" in part:
                other = part.replace("她人對自己的認知：", "").strip()
            elif "自己對自己的認知" in part:
                self_ = part.replace("自己對自己的認知：", "").strip()
        return self_ if for_self else other 

    def refresh_personality(self, self_name: str = None):
        """
        重新根據 self_name 取得 personality，並同步 self_name, _main_lower
        """
        if self_name:
            self.self_name = self_name
            self._main_lower = self_name.lower()
        try:
            profile = self.profile_manager.fetch_profile(self.self_name)
            if profile and profile.get("personality"):
                self.personality = profile["personality"]
                logger.info(f"[refresh] Loaded dynamic personality for {self.self_name}: {self.personality}")
            else:
                self.personality = ""
                logger.warning(f"[refresh] No personality found for {self.self_name} from API.")
        except Exception as e:
            self.personality = ""
            logger.warning(f"[refresh] Unable to load personality for {self.self_name} from API: {e}") 