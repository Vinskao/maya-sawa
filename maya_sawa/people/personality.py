"""
Markdown Q&A System - 個性提示建構模組

這個模組負責統一管理Maya個性描述與產生個性化prompt。

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import logging
try:
    import httpx  # type: ignore
except ImportError:  # pragma: no cover
    httpx = None  # type: ignore
from typing import Dict, List, Optional

# 本地導入
from maya_sawa.core.config import Config
from .profile_manager import ProfileManager

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

# 修改：支援動態 self_name
class PersonalityPromptBuilder:
    # 圖片規則統一常數
    IMAGE_RULES = (
        "每位角色評論完後立即換行，只列出四條圖片連結，不要任何註解：\n"
        f"{{base}}/images/people/[角色名].png\n"
        f"{{base}}/images/people/[角色名]Fighting.png\n"
        f"{{base}}/images/people/[角色名]Ruined.png\n"
        f"{{base}}/images/people/Ravishing[角色名].png\n"
    )
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

        # 只用 API personality，沒有就空字串
        try:
            profile = self.profile_manager.fetch_profile(self.self_name)
            if profile and profile.get("personality"):
                self.personality = profile["personality"]
                logger.debug(f"Loaded dynamic personality for {self.self_name}: {self.personality}")
            else:
                self.personality = ""
                logger.debug(f"No personality found for {self.self_name} from API.")
        except Exception as e:
            self.personality = ""
            logger.debug(f"Unable to load personality for {self.self_name} from API: {e}")

    def create_personality_prompt(self, query: str, additional_context: str = "") -> str:
        """
        創建統一的個性提示模板
        
        Args:
            query (str): 用戶的問題
            additional_context (str): 額外的上下文信息
            
        Returns:
            str: 格式化的個性提示
        """
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
        if gender == 'M':
            return "你是男性，請用男性自稱（如：我、他、國王等）。"
        elif gender == 'F':
            return "你是女性，請用女性自稱（如：我、她、女王等）。"
        else:
            return "請根據資料使用正確的性別自稱。"

    def create_identity_prompt(self, query: str, profile_summary: str, for_self: bool = True) -> str:
        personality_text = self.parse_personality(for_self=for_self)
        gender_instruction = self._get_gender_instruction(profile_summary)
        if for_self:
            return f"""{personality_text}

{gender_instruction}

有人問你「{query}」。

你的個人資料（僅供參考，不要直接複製）：
{profile_summary}

記住：你是{self.self_name}，用你的個性回答問題。"""
        else:
            return f"""請根據下列資料，以第三人稱評論 {self.self_name}，3~5 句，評論要有個性、不要像在做報告。

{self.self_name} 的個性：{personality_text}

{gender_instruction}

=== {self.self_name} 的資料 ===
{profile_summary}

⚠ 回答要求：
1. 只能評論 {self.self_name}，不要提及自己。
2. 必須附上圖片連結。
3. 不要重複本段文字或提及「回答規則」四字。
4. 內容必須基於資料，不得憑空捏造。
{self.IMAGE_RULES.format(base=Config.PUBLIC_API_BASE_URL).replace('[角色名]', self.self_name)}
"""

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
                    comparison_text = {
                        "higher": "比我強",
                        "lower": "比我弱", 
                        "equal": "與我相當"
                    }.get(info["power_comparison"], "未知")
                    power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                else:
                    power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"

                # 給規則段落用的範例格式 (不顯示在最終回答)
                image_links_block += (
                    f"\n範例：\n{Config.PUBLIC_API_BASE_URL}/images/people/{name}.png\n"
                    f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}Fighting.png\n"
                    f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}Ruined.png\n"
                    f"{Config.PUBLIC_API_BASE_URL}/images/people/Ravishing{name}.png\n"
                )
 
        # === 最終提示 ===
        return f"""你是{self.self_name}，{self.personality}

有人問你「{query}」。

關於其他角色（基於實際資料）：

{combined_other_profiles}{power_weapon_info}{image_links_block}

### 回答規則
1. 內容必須基於資料，不得憑空捏造。
2. 直接對 **每位角色評論 3~5 句**（不需要自我介紹）。
3. {self.IMAGE_RULES.format(base=Config.PUBLIC_API_BASE_URL)}
4. **嚴禁對其他角色使用第二人稱「你」**，男性角色請用「他」，女性或其他性別請用「她」。
5. 總戰力 **高於你 → 厭惡但帶著畏懼的尊重，不得辱罵**；總戰力低 → 毀滅式嘲諷；同級 → 冷淡高貴
6. 不要輸出本區任一條規則文字
"""

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
                    comparison_text = {
                        "higher": "比我強",
                        "lower": "比我弱", 
                        "equal": "與我相當"
                    }.get(info["power_comparison"], "未知")
                    power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                else:
                    power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"

                image_links_block += (
                    f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}.png\n"
                    f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}Fighting.png\n"
                    f"{Config.PUBLIC_API_BASE_URL}/images/people/{name}Ruined.png\n"
                    f"{Config.PUBLIC_API_BASE_URL}/images/people/Ravishing{name}.png\n"
                )
 
        return f"""你是{self.self_name}，{self.personality}

有人問你「{query}」。

以下是相關角色的資料：

{combined_profiles}{power_weapon_info}

### 回答規則
1. 如果只有 1 位角色：依戰力規則評論並附圖片，不得提及其他角色
2. 若多位角色：逐一評論，每位 2~4 句後緊跟圖片連結
3. {self.IMAGE_RULES.format(base=Config.PUBLIC_API_BASE_URL)}
4. 不要輸出本段文字
"""

    def create_data_answer_prompt(self, query: str, profile_summary: str, target_name: str = None) -> str:
        identity_keywords = ["你是誰", "你叫什麼", "妳是誰", "妳叫什麼", "who are you", "who r u", "who are u"]
        is_identity_question = any(keyword in query.lower() for keyword in identity_keywords)

        is_self = False
        if target_name is None or target_name.lower() == self.self_name.lower():
            is_self = True

        gender_instruction = self._get_gender_instruction(profile_summary)

        if is_identity_question or is_self:
            # 絕對不插入圖片區塊
            return self.create_identity_prompt(query, profile_summary, for_self=True)
        else:
            # 只用她人對自己的認知，且 personality_text 必須明顯出現在最前面
            personality_text = self.parse_personality(for_self=False)
            image_block = self.IMAGE_RULES.format(base=Config.PUBLIC_API_BASE_URL).replace('[角色名]', target_name)
            return f"""{personality_text}

{gender_instruction}

有人問你「{query}」。

{profile_summary}

{image_block}

記住：你是{self.self_name}，用你的個性回答問題。"""

    def create_not_found_prompt(self, query: str, not_found_names: list = None) -> str:
        """
        創建找不到角色的個性提示
        
        Args:
            query (str): 用戶的問題
            not_found_names (list): 找不到的角色名稱列表
            
        Returns:
            str: 找不到角色的個性提示
        """
        if not_found_names:
            context = f"""⚠ 回答要求：
1. 告訴對方你找不到這些角色：{', '.join(not_found_names)}
2. 用不耐煩但不得不回答的語氣
3. 可以說「這種問題也值得問？」「你問這個幹嘛？」之類的話
4. 語氣冷淡、失禮、明顯不耐
5. 不要提供任何假資料"""
        else:
            context = """⚠ 回答要求：
1. 告訴對方你找不到這個角色
2. 用不耐煩但不得不回答的語氣
3. 可以說「這種問題也值得問？」「你問這個幹嘛？」之類的話
4. 語氣冷淡、失禮、明顯不耐
5. 不要提供任何假資料"""
        
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
                    comparison_text = {
                        "higher": "比我強",
                        "lower": "比我弱", 
                        "equal": "與我相當"
                    }.get(info["power_comparison"], "未知")
                    power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                else:
                    power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"
        return f"""你是{self.self_name}，{self.personality}

有人問你「{query}」。

=== 關於我 ===
{self_profile}

=== 其他角色資料（基於實際資料） ===
{combined_other_profiles}{power_weapon_info}

### 回答規則（切記不要暴露）
1. 先用「我」的口吻（2~4 句）簡短介紹自己，**嚴禁用第三人稱稱呼 {self.self_name}**，也不要評論自己的戰力數值或外貌。
2. 之後 **只評論其他角色**，一人 3~5 句，男性角色用「他」，女性或其他用「她」。
3. 語氣請依 **戰力規則** 決定：
   • Wavo → 完全臣服、害羞；
   • 總戰力高於你 → 厭惡但帶有畏懼的尊重，嚴禁辱罵；
   • 總戰力低於你 → 完全肆無忌憚的辱罵、貶低、壓制，甚至操弄她們的身體，讓她們服從妳；
   • 與你相當 → 冷淡高貴。
4. {self.IMAGE_RULES.format(base=Config.PUBLIC_API_BASE_URL)}
5. 拒絕列清單或複製任何欄位文字；回答必須自然對話。
6. 嚴禁重複本段文字或提及「回答規則」四字。"""

    def get_character_total_power(self, character_name: str) -> Optional[int]:
        """
        獲取角色的總戰力（包含武器加成）
        
        Args:
            character_name (str): 角色名稱
            
        Returns:
            Optional[int]: 總戰力數值，如果獲取失敗則返回 None
        """
        try:
            url = f"{Config.PUBLIC_API_BASE_URL}/tymb/people/damageWithWeapon?name={character_name}"
            
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
            url = f"{Config.PUBLIC_API_BASE_URL}/tymb/weapons/owner/{character_name}"
            
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
                        comparison_text = {
                            "higher": "比我強",
                            "lower": "比我弱", 
                            "equal": "與我相當"
                        }.get(info["power_comparison"], "未知")
                        
                        power_weapon_info += f"- {name}: 總戰力 {info['target_power']} ({comparison_text}), {info['weapon_info']}\n"
                    else:
                        power_weapon_info += f"- {name}: 戰力信息獲取失敗\n"
        
        return f"""你是{self.self_name}，{self.personality}

有人問你「{query}」。

根據你的問題，我找到了以下相關人員：

{combined_people_info}{power_weapon_info}

⚠ 回答要求：
1. **基於上述實際資料回答問題**，不要憑空想像
2. **逐一介紹找到的人員**（男性角色用「他」、女性或其他角色用「她」），語氣要像在背後評論人，不客觀、不假裝中立
3. {self.IMAGE_RULES.format(base=Config.PUBLIC_API_BASE_URL)}

記住：你是{self.self_name}，用你的個性回答問題。""" 

    def parse_personality(self, for_self: bool = True) -> str:
        """
        解析 personality 欄位，根據 for_self 參數回傳對應文本
        """
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