"""
Markdown Q&A System - 角色資料管理模組

這個模組負責角色資料API存取、快取、summary、角色名單等功能。

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import os
import logging
import httpx
from typing import Dict, List, Optional

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class ProfileManager:
    """
    負責角色資料API存取、快取、summary、角色名單
    """
    
    def __init__(self):
        """
        初始化角色資料管理器
        """
        # 初始化快取
        self._profile_cache = None
        self._profile_summary_cache = None
        self._other_profiles_cache = {}
        self._other_character_names_cache = None

    def fetch_profile(self, name: str) -> Optional[Dict]:
        """
        查詢指定角色的個人資料
        
        Args:
            name (str): 角色名稱
            
        Returns:
            Optional[Dict]: 角色個人資料，如果獲取失敗則返回 None
        """
        url = "https://peoplesystem.tatdvsonorth.com/tymb/people/get-by-name"
        payload = {"name": name}
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                logger.info(f"Successfully fetched {name}'s profile from API")
                return data
        except Exception as e:
            logger.error(f"Failed to fetch {name}'s profile: {str(e)}")
            return None

    def fetch_maya_profile(self) -> Optional[Dict]:
        """
        從 API 獲取 Maya 的個人資料
        
        Returns:
            Optional[Dict]: Maya 的個人資料，如果獲取失敗則返回 None
        """
        return self.fetch_profile("Maya")

    def create_profile_summary(self, profile: Dict, name: str = None) -> str:
        """
        將個人資料轉換為摘要格式
        
        Args:
            profile (Dict): 個人資料字典
            name (str): 角色名稱，如果為 None 則使用 profile 中的資料
            
        Returns:
            str: 格式化的個人資料摘要
        """
        # 確定角色名稱
        if name is None:
            display_name = f"{profile.get('nameOriginal', 'N/A')}（{profile.get('name', 'N/A')}）"
            character_name = profile.get('name', 'N/A')
        else:
            display_name = f"{profile.get('nameOriginal', name)}（{profile.get('name', name)}）"
            character_name = name
        
        # 構建四種圖片連結
        base_image_url = f"https://peoplesystem.tatdvsonorth.com/images/people/{character_name}.png"
        fighting_image_url = f"https://peoplesystem.tatdvsonorth.com/images/people/{character_name}Fighting.png"
        ruined_image_url = f"https://peoplesystem.tatdvsonorth.com/images/people/{character_name}Ruined.png"
        ravishing_image_url = f"https://peoplesystem.tatdvsonorth.com/images/people/Ravishing{character_name}.png"
        
        return f"""
{display_name}的個人資料：
- 編號：{profile.get('id', 'N/A')}
- 原名：{profile.get('nameOriginal', 'N/A')}
- 代號：{profile.get('codeName', 'N/A')}
- 戰鬥力：物理{profile.get('physicPower', 'N/A')}、魔法{profile.get('magicPower', 'N/A')}、武器{profile.get('utilityPower', 'N/A')}
- 出生：{profile.get('dob', 'N/A')}
- 種族：{profile.get('race', 'N/A')}
- 屬性：{profile.get('attributes', 'N/A')}
- 性別：{profile.get('gender', 'N/A')}
- 身材：胸部{profile.get('boobsSize', 'N/A')}、臀部{profile.get('assSize', 'N/A')}、身高{profile.get('heightCm', 'N/A')}cm、體重{profile.get('weightKg', 'N/A')}kg
- 職業：{profile.get('profession', 'N/A')}
- 戰鬥風格：{profile.get('combat', 'N/A')}
- 最愛食物：{profile.get('favoriteFoods', 'N/A')}
- 工作：{profile.get('job', 'N/A')}
- 體態：{profile.get('physics', 'N/A')}
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

圖片連結：
- 基本圖片：{base_image_url}
- 戰鬥圖片：{fighting_image_url}
- 毀壞圖片：{ruined_image_url}
- 迷人圖片：{ravishing_image_url}
"""

    def get_profile_summary(self, name: str = "Maya") -> str:
        """
        獲取個人資料摘要，使用緩存避免重複 API 調用
        
        Args:
            name (str): 角色名稱，預設為 "Maya"
            
        Returns:
            str: 個人資料摘要
        """
        if name.lower() == "maya":
            # Maya 使用特殊快取
            if self._profile_summary_cache is None:
                profile = self.fetch_maya_profile()
                if profile:
                    self._profile_cache = profile
                    self._profile_summary_cache = self.create_profile_summary(profile)
                else:
                    # 如果無法獲取資料，使用預設摘要
                    self._profile_summary_cache = """
佐和真夜（Maya Sawa）的個人資料：
- 無法從 API 獲取最新資料，請檢查網路連接或 API 狀態
"""
            return self._profile_summary_cache
        else:
            # 其他角色使用一般快取
            return self.get_other_profile_summary(name)

    def get_other_profile_summary(self, name: str) -> Optional[str]:
        """
        獲取其他角色的個人資料摘要，使用緩存避免重複 API 調用
        
        Args:
            name (str): 角色名稱
            
        Returns:
            Optional[str]: 個人資料摘要，如果獲取失敗則返回 None
        """
        # 檢查緩存
        if name in self._other_profiles_cache:
            return self._other_profiles_cache[name]
        
        # 從 API 獲取資料
        profile = self.fetch_profile(name)
        if profile:
            summary = self.create_profile_summary(profile, name)
            self._other_profiles_cache[name] = summary
            return summary
        else:
            return None

    def get_other_character_names(self) -> List[str]:
        """
        從 API 獲取其他角色名字列表
        
        Returns:
            List[str]: 其他角色名字列表
        """
        try:
            # 檢查緩存
            if self._other_character_names_cache is not None:
                return self._other_character_names_cache
            
            # 從環境變數獲取 API 基礎 URL
            api_base = os.getenv("PUBLIC_API_BASE_URL")
            if not api_base:
                logger.warning("PUBLIC_API_BASE_URL 未設置，返回空列表")
                return []
            
            # 構建 API URL
            url = f"{api_base}/tymb/people/names"
            logger.debug(f"正在從 API 獲取角色名字列表: {url}")
            
            # 發送 HTTP 請求
            response = httpx.get(url, timeout=10.0)
            response.raise_for_status()
            
            # 解析回應
            names = response.json()
            if isinstance(names, list):
                # 過濾掉 Maya（因為她是系統內建角色）
                filtered_names = [name for name in names if name.lower() != "maya"]
                logger.info(f"從 API 獲取到 {len(filtered_names)} 個其他角色名字")
                
                # 緩存結果
                self._other_character_names_cache = filtered_names
                return filtered_names
            else:
                logger.error(f"API 回應格式錯誤，預期 list，實際: {type(names)}")
                return []
                
        except Exception as e:
            logger.error(f"獲取角色名字列表時發生錯誤: {str(e)}")
            # 發生錯誤時返回空列表
            return []

    def refresh_profile(self, name: str = "Maya"):
        """
        刷新指定角色的個人資料緩存
        
        Args:
            name (str): 角色名稱，預設為 "Maya"
        """
        if name.lower() == "maya":
            logger.info("Refreshing Maya's profile from API")
            self._profile_cache = None
            self._profile_summary_cache = None
        else:
            logger.info(f"Refreshing {name}'s profile from API")
            if name in self._other_profiles_cache:
                del self._other_profiles_cache[name]

    def refresh_other_profile(self, name: str):
        """
        刷新指定角色的個人資料緩存
        
        Args:
            name (str): 角色名稱
        """
        logger.info(f"Refreshing {name}'s profile from API")
        if name in self._other_profiles_cache:
            del self._other_profiles_cache[name]

    def clear_all_profiles_cache(self):
        """
        清除所有角色資料緩存
        """
        logger.info("Clearing all profiles cache")
        self._profile_cache = None
        self._profile_summary_cache = None
        self._other_profiles_cache.clear()
        self._other_character_names_cache = None 