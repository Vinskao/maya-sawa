import logging
from typing import Dict, List, Optional
from maya_sawa.core.langchain_shim import Document, PromptTemplate, ChatOpenAI
from maya_sawa.people import NameDetector, ProfileManager, PersonalityPromptBuilder, PeopleWeaponManager, NameAdapter
from maya_sawa.core.config_manager import config_manager

logger = logging.getLogger(__name__)

class QAChain:
    """
    問答鏈，整合了名稱檢測、個人資料管理和個性化提示構建功能
    """
    
    def __init__(self):
        """
        初始化 QAChain
        """
        # 從配置管理器獲取 LLM 配置
        llm_config = config_manager.get_constant("LLM_CONFIG")
        self.llm = ChatOpenAI(
            model=llm_config["MODEL"],
            temperature=llm_config["TEMPERATURE"],
            max_tokens=llm_config["MAX_TOKENS"]
        )
        
        # 初始化組件
        self.self_name = "Maya"  # 預設系統主角名稱，可被外部覆寫
        self.name_detector = NameDetector(llm=self.llm, get_known_names_func=self._get_known_names, self_name=self.self_name)
        self.profile_manager = ProfileManager()
        # Personality builder 依 self_name 初始化，並共用 profile_manager
        self.personality_builder = PersonalityPromptBuilder(self.self_name, self.profile_manager)
        self.people_manager = PeopleWeaponManager()
        self.name_adapter = NameAdapter()
        
        # 添加緩存
        self._known_names_cache = None
        self._known_names_cache_timestamp = 0
        self._cache_duration = config_manager.get_constant("CACHE_DURATION")  # 從配置管理器獲取緩存時間
        
        # 創建動態提示模板
        self._create_dynamic_prompt()
        
        # 初始化聊天鏈
        self.chat_chain = self.prompt_template | self.llm
        
        logger.info("QAChain 初始化完成")

    def _get_known_names(self) -> List[str]:
        """
        獲取已知的角色名稱列表（帶緩存）
        
        Returns:
            List[str]: 已知角色名稱列表
        """
        import time
        current_time = time.time()
        
        # 檢查緩存是否有效
        if (self._known_names_cache is not None and 
            current_time - self._known_names_cache_timestamp < self._cache_duration):
            logger.debug("使用緩存的已知角色名稱列表")
            return self._known_names_cache
        
        try:
            # 從 people manager 獲取所有角色名稱
            people_data = self.people_manager.fetch_people_data()
            if people_data:
                names = [person.get('name', '') for person in people_data if person.get('name')]
                # 添加 self_name 作為系統內建角色
                if self.self_name not in names:
                    names.append(self.self_name)
                
                # 更新緩存
                self._known_names_cache = names
                self._known_names_cache_timestamp = current_time
                logger.info(f"更新已知角色名稱緩存，共 {len(names)} 個角色")
                return names
            else:
                # 如果無法獲取，至少返回當前主角名稱
                fallback_names = [self.self_name]
                self._known_names_cache = fallback_names
                self._known_names_cache_timestamp = current_time
                return fallback_names
        except Exception as e:
            logger.error(f"獲取已知角色名稱時發生錯誤: {str(e)}")
            # 如果發生錯誤，至少返回當前主角名稱
            fallback_names = [self.self_name]
            self._known_names_cache = fallback_names
            self._known_names_cache_timestamp = current_time
            return fallback_names

    def _create_dynamic_prompt(self):
        """
        創建動態提示模板
        """
        # 取得主角的個人資料摘要（依目前 self.self_name）
        self_profile = self.profile_manager.get_profile_summary(self.self_name)
        
        # 創建提示模板
        self.prompt_template = PromptTemplate(
            input_variables=["context", "question"],
            template=f"""妳/你是 {self.self_name}。以下是你的基本資料：

{self_profile}

請以 {self.self_name} 的身份回答問題，保持你的個性和語氣。回答要自然、有趣，不要直接複製資料內容。

如果提供了上下文資料，請基於這些資料回答問題。如果沒有提供上下文，請基於你的知識回答。

問題：{{question}}

上下文：{{context}}

請回答："""
        )

    def refresh_profile(self):
        """
        刷新 self_name 的個人資料
        """
        self.profile_manager.refresh_profile(self.self_name)
        self._create_dynamic_prompt()
        # 重新創建聊天鏈
        self.chat_chain = self.prompt_template | self.llm
        logger.info(f"{self.self_name} 個人資料已刷新")

    def refresh_other_profile(self, name: str):
        """
        刷新指定角色的個人資料
        
        Args:
            name (str): 角色名稱
        """
        self.profile_manager.refresh_other_profile(name)
        logger.info(f"{name} 的個人資料已刷新")

    def clear_all_profiles_cache(self):
        """
        清除所有個人資料快取
        """
        self.profile_manager.clear_all_profiles_cache()
        logger.info("所有個人資料快取已清除")

    def _fix_gender_pronouns(self, text: str, character_names: List[str]) -> str:
        """
        檢查並修正文本中的性別代詞使用
        
        Args:
            text (str): 原始文本
            character_names (List[str]): 角色名稱列表
            
        Returns:
            str: 修正後的文本
        """
        import re
        
        # 獲取每個角色的性別信息
        character_genders = {}
        for name in character_names:
            if name.lower() != self.self_name.lower():  # 跳過自己
                try:
                    profile = self.profile_manager.fetch_profile(name)
                    if profile and profile.get('gender'):
                        gender = profile['gender'].strip().upper()
                        if gender.startswith('M'):
                            character_genders[name] = 'M'
                        elif gender.startswith('F'):
                            character_genders[name] = 'F'
                        else:
                            character_genders[name] = 'F'  # 預設用「她」
                except Exception as e:
                    logger.warning(f"無法獲取 {name} 的性別信息: {e}")
                    character_genders[name] = 'F'  # 預設用「她」
        
        # 修正性別代詞
        corrected_text = text
        for name, gender in character_genders.items():
            if gender == 'M':
                # 確保男性角色用「他」
                # 使用更簡單但有效的方法：在提到該角色的段落中將「她」替換為「他」
                lines = corrected_text.split('\n')
                for i, line in enumerate(lines):
                    if name in line and '她' in line:
                        lines[i] = line.replace('她', '他')
                corrected_text = '\n'.join(lines)
            elif gender == 'F':
                # 確保女性角色用「她」
                lines = corrected_text.split('\n')
                for i, line in enumerate(lines):
                    if name in line and '他' in line:
                        lines[i] = line.replace('他', '她')
                corrected_text = '\n'.join(lines)
        
        if corrected_text != text:
            logger.info(f"已修正性別代詞使用")
        
        return corrected_text

    def _analyze_character_powers(self, character_names: List[str]) -> Dict:
        """
        分析角色戰力關係
        
        Args:
            character_names (List[str]): 角色名稱列表
            
        Returns:
            Dict: 戰力分析結果
        """
        self_power = self.personality_builder.get_character_total_power(self.self_name)
        
        stronger_characters = []
        weaker_characters = []
        equal_characters = []
        other_characters = []
        
        for name in character_names:
            if name.lower() != self.self_name.lower():
                other_characters.append(name)
                total_power = self.personality_builder.get_character_total_power(name)
                
                if total_power is not None and self_power is not None:
                    if total_power > self_power:
                        stronger_characters.append(name)
                        logger.info(f"{name} 戰力 {total_power} > {self.self_name} 戰力 {self_power}")
                    elif total_power < self_power:
                        weaker_characters.append(name)
                        logger.info(f"{name} 戰力 {total_power} < {self.self_name} 戰力 {self_power}")
                    else:
                        equal_characters.append(name)
                        logger.info(f"{name} 戰力 {total_power} = {self.self_name} 戰力 {self_power}")
                else:
                    logger.warning(f"無法獲取 {name} 或 {self.self_name} 的戰力信息")
        
        return {
            'has_others': len(other_characters) > 0,
            'has_stronger': len(stronger_characters) > 0,
            'has_weaker': len(weaker_characters) > 0,
            'has_equal': len(equal_characters) > 0,
            'stronger_characters': stronger_characters,
            'weaker_characters': weaker_characters,
            'equal_characters': equal_characters,
            'other_characters': other_characters
        }

    def _remove_self_images(self, text: str) -> str:
        """
        從文本中移除當前角色的圖片連結
        
        Args:
            text (str): 原始文本
            
        Returns:
            str: 移除圖片連結後的文本
        """
        import re
        
        # 移除當前角色的所有四種圖片連結格式
        self_name_escaped = re.escape(self.self_name)
        
        # 使用通用的圖片URL模式，不依賴具體的base URL
        patterns = [
            # 正常圖片: https://.../images/people/Name.png
            rf"https?://[^\s]+/images/people/{self_name_escaped}\.png\s*",
            # 戰鬥圖片: https://.../images/people/NameFighting.png
            rf"https?://[^\s]+/images/people/{self_name_escaped}Fighting\.png\s*",
            # 毀壞圖片: https://.../images/people/NameRuined.png
            rf"https?://[^\s]+/images/people/{self_name_escaped}Ruined\.png\s*",
            # 迷人圖片: https://.../images/people/RavishingName.png
            rf"https?://[^\s]+/images/people/Ravishing{self_name_escaped}\.png\s*"
        ]
        
        for pattern in patterns:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
        
        # 移除可能剩餘的圖片連結區塊標題（如果只剩下自己的圖片）
        # 檢查是否還有其他角色的圖片連結
        other_images_pattern = rf"https://[^\n]*/images/people/(?!{self_name_escaped})[^\n]*\n"
        if not re.search(other_images_pattern, text):
            # 如果沒有其他角色的圖片，移除整個圖片連結區塊
            image_block_patterns = [
                rf"圖片連結格式[^\n]*\n(https://[^\n]*/images/people/{self_name_escaped}[^\n]*\n)*",
                rf"圖片連結：\n(https://[^\n]*/images/people/{self_name_escaped}[^\n]*\n)*"
            ]
            for pattern in image_block_patterns:
                text = re.sub(pattern, "", text)
        
        logger.info(f"已移除 {self.self_name} 的圖片連結")
        return text

    def get_answer(self, query: str, documents: List[Document], self_name: Optional[str] = None, user_id: str = "default") -> Dict:
        """
        獲取問題的答案
        
        Args:
            query (str): 用戶的問題
            documents (List[Document]): 相關文檔列表
            self_name (Optional[str]): AI 角色名稱
            user_id (str): 用戶 ID，用於清除特定用戶的聊天記錄
            
        Returns:
            Dict: 包含答案、來源和找到的角色的字典
        """
        # 若外部傳入 self_name 與目前不同，更新內部狀態
        if self_name and self_name != self.self_name:
            logger.info(f"更新主角名稱: {self.self_name} -> {self_name}")
            
            # 清除當前用戶的對話紀錄（當 AI 換人時）
            try:
                from maya_sawa.core.chat_history import ChatHistoryManager
                chat_history = ChatHistoryManager()
                # 只清除當前用戶的對話紀錄
                success = chat_history.clear_conversation_history(user_id)
                if success:
                    logger.info(f"已清除用戶 {user_id} 的對話紀錄（AI 換人）")
                else:
                    logger.warning(f"清除用戶 {user_id} 的對話紀錄失敗")
            except Exception as e:
                logger.warning(f"清除對話紀錄時發生錯誤: {e}")
            
            self.self_name = self_name
            # 同步至 NameDetector 與 PersonalityPromptBuilder
            self.name_detector.self_name = self_name
            self.name_detector._main_lower = self_name.lower()
            self.profile_manager.refresh_profile(self_name)
            self.personality_builder.refresh_personality(self_name)
            self.personality_builder.self_name = self_name
            self.personality_builder._main_lower = self_name.lower()
            
            # 重新創建動態提示模板和聊天鏈
            self._create_dynamic_prompt()
            self.chat_chain = self.prompt_template | self.llm
        
        # 提前判斷是否為身份詢問
        lower_self = self.self_name.lower()
        identity_keywords = config_manager.get_keywords("IDENTITY_KEYWORDS")
        identity_questions = identity_keywords + [
            f"誰是{lower_self}", f"誰是{self.self_name}",
            f"who is {lower_self}", f"who is {self.self_name}"
        ]
        is_identity_question = any(keyword in query.lower() for keyword in identity_questions)

        # 檢測問題中提到的角色名稱
        detected_names = self.name_detector.detect_all_queried_names(query)
        logger.info(f"檢測到的角色名稱: {detected_names}")
        
        # 如果有檢測到角色名稱，優先處理角色相關問題
        if detected_names:
            logger.info("檢測到角色名稱，處理角色相關問題")
            
            # 分離 self 和其他角色
            self_names = [name for name in detected_names if name.lower() == self.self_name.lower()]
            other_names = [name for name in detected_names if name.lower() != self.self_name.lower()]
            
            logger.info(f"self 相關角色: {self.self_name}, 其他角色: {other_names}")
            
            # 收集所有角色的資料
            all_profiles = []
            found_names = []
            not_found = []
            
            # 處理 self 相關問題
            if self_names:
                logger.info("處理 self 相關問題")
                self_summary = self.profile_manager.get_profile_summary(self.self_name)
                if self_summary:
                    all_profiles.append(f"=== {self.self_name} 的資料 ===\n{self_summary}")
                    found_names.append(self.self_name)
                    logger.info(f"{self.self_name} 資料已添加")
                else:
                    not_found.append(self.self_name)
                    logger.warning(f"無法找到 {self.self_name} 的資料")
            
            # 處理其他角色問題
            for name in other_names:
                logger.info(f"正在處理角色: {name}")
                normalized_name = self.name_adapter.normalize_name(name)
                profile_summary = self.profile_manager.get_other_profile_summary(normalized_name)
                if profile_summary:
                    all_profiles.append(f"=== {normalized_name} 的資料 ===\n{profile_summary}")
                    found_names.append(normalized_name)
                    logger.info(f"{normalized_name} 資料已添加")
                else:
                    not_found.append(name)
                    logger.warning(f"無法找到 {name} 的資料，可能是 API 調用失敗或角色不存在")
            
            logger.info(f"處理結果 - 找到的角色: {found_names}, 找不到的角色: {not_found}")
            logger.info(f"all_profiles 數量: {len(all_profiles)}")
            
            logger.info(f"找到的資料數量: {len(all_profiles)}, 找不到的角色: {not_found}")
            
            # 組合所有找到的資料並生成總結
            if all_profiles:
                combined_profiles = "\n\n".join(all_profiles)
                
                # 檢查是否要求詳細資料
                if hasattr(self.name_detector, '_request_detailed') and self.name_detector._request_detailed:
                    # 直接返回原始資料
                    combined_answer = "\n\n".join(all_profiles)
                    if not_found:
                        combined_answer += f"\n\n至於 {', '.join(not_found)}？我沒聽過這些人，你問錯人了。"
                    return {
                        "answer": combined_answer,
                        "sources": [],
                        "found_characters": found_names
                    }
                else:
                    # === 根據角色數量選擇不同 prompt ===
                    if len(found_names) > 1:
                        # 當問題涉及多個角色時，也要包含 AI 自己的資料
                        if self.self_name not in found_names:
                            # 添加 AI 自己的資料
                            self_summary = self.profile_manager.get_profile_summary(self.self_name)
                            if self_summary:
                                all_profiles.insert(0, f"=== {self.self_name} 的資料 ===\n{self_summary}")
                                found_names.insert(0, self.self_name)
                                combined_profiles = "\n\n".join(all_profiles)
                            
                        # 統一處理戰力比較邏輯
                        power_analysis = self._analyze_character_powers(found_names)
                        
                        is_mixed_identity_question = is_identity_question and self.self_name in found_names
                        
                        # 如果是混合身份問題，優先使用 self_and_other_prompt
                        if is_mixed_identity_question:
                            logger.info("檢測到混合身份問題，優先使用 self_and_other_prompt")
                            self_summary = self.profile_manager.get_profile_summary(self.self_name)
                            other_profiles_block = "\n\n".join([
                                p for p in all_profiles if not p.startswith(f"=== {self.self_name}")
                            ])
                            summary_prompt = self.personality_builder.create_self_and_other_prompt(
                                query,
                                self_summary,
                                other_profiles_block,
                                [n for n in found_names if n.lower() != self.self_name.lower()]
                            )
                        # 如果有任何其他角色，使用 SIMPLE_RECOGNITION_PROMPT
                        elif power_analysis['has_others']:
                            if power_analysis['has_stronger']:
                                logger.info(f"檢測到有比 AI 強的角色：{power_analysis['stronger_characters']}，使用 SIMPLE_RECOGNITION_PROMPT（混合語氣）")
                            elif power_analysis['has_weaker']:
                                logger.info(f"檢測到只有比 AI 弱的角色：{power_analysis['weaker_characters']}，使用 SIMPLE_RECOGNITION_PROMPT（攻擊性版）")
                            else:
                                logger.info("檢測到其他角色，使用 SIMPLE_RECOGNITION_PROMPT（普通版）")
                            
                            # 只傳入其他角色的資料，不包含AI自己
                            other_profiles_block = "\n\n".join([
                                p for p in all_profiles if not p.startswith(f"=== {self.self_name}")
                            ])
                            summary_prompt = config_manager.get_prompt("SIMPLE_RECOGNITION_PROMPT").format(
                                other_profiles_only=other_profiles_block
                            )
                        elif self.self_name in found_names and len(found_names) > 1:
                            # 分離 self 以外的資料供評論
                            other_profiles_block = "\n\n".join([
                                p for p in all_profiles if not p.startswith(f"=== {self.self_name}")
                            ])
                            summary_prompt = self.personality_builder.create_self_and_other_prompt(
                                query,
                                self_summary if 'self_summary' in locals() else self.profile_manager.get_profile_summary(),
                                other_profiles_block,
                                [n for n in found_names if n.lower() != self.self_name.lower()]
                            )
                        else:
                            summary_prompt = self.personality_builder.create_multi_character_prompt(query, combined_profiles, found_names)
                    else:
                        # 單一角色（且不是 Maya）
                        # 取得被問角色名，若 found_names 有值則用第一個
                        target_name = found_names[0] if found_names else None
                        summary_prompt = self.personality_builder.create_data_answer_prompt(query, combined_profiles, target_name=target_name)
                    
                    # 簡化LLM調用，移除複雜的錯誤處理
                    logger.info("調用LLM生成總結回答...")
                    summary_response = self.llm.invoke(summary_prompt)
                    
                    # 簡化響應處理
                    if hasattr(summary_response, 'content'):
                        summary_answer = summary_response.content
                    else:
                        summary_answer = str(summary_response)
                    
                    # 修正性別代詞使用
                    if len(found_names) > 1:
                        summary_answer = self._fix_gender_pronouns(summary_answer, found_names)
                    
                    # 如果只找到自己一個角色，移除圖片連結
                    if len(found_names) == 1 and found_names[0].lower() == self.self_name.lower():
                        summary_answer = self._remove_self_images(summary_answer)
                    # 如果多個角色中包含自己，也要移除自己的圖片連結
                    elif len(found_names) > 1 and any(name.lower() == self.self_name.lower() for name in found_names):
                        summary_answer = self._remove_self_images(summary_answer)
                    
                    if not_found:
                        summary_answer += f"\n\n至於 {', '.join(not_found)}？我沒聽過這些人，你問錯人了。"
                    
                    return {
                        "answer": summary_answer,
                        "sources": [],
                        "found_characters": found_names
                    }
            else:
                return {
                    "answer": f"抱歉，我無法找到以下角色的資料：{', '.join(not_found)}",
                    "sources": [],
                    "found_characters": []
                }
        
        # 優先檢查是否為身份詢問問題
        if is_identity_question and not detected_names: # 純身份問題
            logger.info(f"檢測到針對 {self.self_name} 的純身份詢問，使用個人資料回答")
            self_summary = self.profile_manager.get_profile_summary(self.self_name, include_images=False)
            
            # 使用 LLM 生成不耐煩但完整的回答
            identity_prompt = self.personality_builder.create_identity_prompt(query, self_summary)
            
            # 簡化身份問題處理
            identity_answer = self.llm.invoke(identity_prompt)
            if hasattr(identity_answer, 'content'):
                identity_answer = identity_answer.content
            
            # 移除身份問題回答中的圖片連結
            identity_answer = self._remove_self_images(identity_answer)
            
            return {
                "answer": identity_answer,
                "sources": [],
                "found_characters": [self.self_name]
            }
        
        # 檢查是否為認識類問題
        is_recognition_question = self.name_adapter.is_recognition_question(query)
        if is_recognition_question:
            logger.info("檢測到認識類問題，優先處理")
            # 從認識類問題中提取名稱
            extracted_names = self.name_adapter.extract_names_from_recognition_question(query)
            if extracted_names:
                logger.info(f"從認識類問題中提取到名稱: {extracted_names}")
                # 處理提取到的名稱
                found_names = []
                not_found_names = []
                
                for name in extracted_names:
                    logger.info(f"Processing extracted name: {name}")
                    normalized_name = self.name_adapter.normalize_name(name)
                    profile_summary = self.profile_manager.get_other_profile_summary(normalized_name)
                    logger.info(f"Profile summary for {normalized_name}: {'Found' if profile_summary else 'Not found'}")
                    if profile_summary:
                        found_names.append(normalized_name)
                    else:
                        not_found_names.append(name)
                
                # 構建人物資料回答
                if found_names:
                    # 獲取找到的人物的詳細資料
                    people_profiles = []
                    for name in found_names:
                        normalized_name = self.name_adapter.normalize_name(name)
                        profile_summary = self.profile_manager.get_other_profile_summary(normalized_name)
                        if profile_summary:
                            people_profiles.append(f"=== {normalized_name} 的資料 ===\n{profile_summary}")
                    
                    if people_profiles:
                        logger.info(f"Found {len(people_profiles)} people profiles")
                        combined_profiles = "\n\n".join(people_profiles)
                        logger.info(f"Combined profiles length: {len(combined_profiles)} characters")
                        
                        # 統一處理戰力比較邏輯
                        power_analysis = self._analyze_character_powers(found_names)
                        
                        # 使用 LLM 生成個性化回答 (視角色數調整)
                        if power_analysis['has_others']:
                            if power_analysis['has_stronger']:
                                logger.info(f"認識類問題檢測到有比 AI 強的角色：{power_analysis['stronger_characters']}，使用 SIMPLE_RECOGNITION_PROMPT（混合語氣）")
                            elif power_analysis['has_weaker']:
                                logger.info(f"認識類問題檢測到只有比 AI 弱的角色：{power_analysis['weaker_characters']}，使用 SIMPLE_RECOGNITION_PROMPT（攻擊性版）")
                            else:
                                logger.info("認識類問題檢測到其他角色，使用 SIMPLE_RECOGNITION_PROMPT（普通版）")
                            
                            # 只傳入其他角色的資料，不包含AI自己
                            other_profiles_block = "\n\n".join([
                                p for p in people_profiles if not p.startswith(f"=== {self.self_name}")
                            ])
                            recognition_prompt = config_manager.get_prompt("SIMPLE_RECOGNITION_PROMPT").format(
                                other_profiles_only=other_profiles_block
                            )
                        elif len(found_names) > 1:
                            recognition_prompt = self.personality_builder.create_multi_character_prompt(query, combined_profiles, found_names)
                        else:
                            recognition_prompt = self.personality_builder.create_data_answer_prompt(query, combined_profiles)
                        logger.info(f"Recognition prompt length: {len(recognition_prompt)} characters")
                        
                        # 簡化認識類問題處理
                        logger.info("Calling LLM for recognition answer...")
                        recognition_answer = self.llm.invoke(recognition_prompt)
                        if hasattr(recognition_answer, 'content'):
                            recognition_answer = recognition_answer.content

                        # 如果有找不到的角色，在最後加上說明
                        if not_found_names:
                            recognition_answer += f"\n\n至於 {', '.join(not_found_names)}？沒聽過這個人。"
                        
                        # 修正性別代詞使用
                        if len(found_names) > 1:
                            recognition_answer = self._fix_gender_pronouns(recognition_answer, found_names)
                        
                        # 如果只找到自己一個角色，移除圖片連結
                        if len(found_names) == 1 and found_names[0].lower() == self.self_name.lower():
                            recognition_answer = self._remove_self_images(recognition_answer)
                        # 如果多個角色中包含自己，也要移除自己的圖片連結
                        elif len(found_names) > 1 and any(name.lower() == self.self_name.lower() for name in found_names):
                            recognition_answer = self._remove_self_images(recognition_answer)
                        
                        logger.info("Returning recognition answer")
                        return {
                            "answer": recognition_answer,
                            "sources": [],
                            "found_characters": found_names
                        }
                
                # 如果沒有找到任何人物資料
                if not_found_names:
                    return {
                        "answer": f"至於 {', '.join(not_found_names)}？沒聽過這些人。",
                        "sources": [],
                        "found_characters": []
                    }
                
                # 如果既沒有找到也沒有找不到的（理論上不會發生）
                return {
                    "answer": "你在問什麼？我聽不懂。",
                    "sources": [],
                    "found_characters": []
                }
        
        # 檢查是否為針對 self 的個人資訊問題（非身份詢問）
        self_personal_questions = config_manager.get_keywords("SELF_PERSONAL_QUESTIONS")
        is_self_personal_question = (
            not detected_names and  # 沒有檢測到其他角色
            any(keyword in query for keyword in self_personal_questions)  # 針對 self 的個人資訊
        )
        
        if is_self_personal_question:
            logger.info(f"檢測到針對 {self.self_name} 的個人資訊問題，使用個人資料回答")
            self_summary = self.profile_manager.get_profile_summary(self.self_name, include_images=False)
            
            # 使用 LLM 生成不耐煩但完整的回答
            identity_prompt = self.personality_builder.create_identity_prompt(query, self_summary)
            
            # 簡化個人資訊問題處理
            identity_answer = self.llm.invoke(identity_prompt)
            if hasattr(identity_answer, 'content'):
                identity_answer = identity_answer.content
            
            # 移除身份問題回答中的圖片連結
            identity_answer = self._remove_self_images(identity_answer)
            
            return {
                "answer": identity_answer,
                "sources": [],
                "found_characters": [self.self_name]
            }
        
        # 特殊處理：人員語義搜索（當問題涉及人員但沒有明確提到具體人名時）
        people_search_keywords = config_manager.get_keywords("PEOPLE_SEARCH_KEYWORDS")
        
        is_people_search_question = (
            not detected_names and  # 沒有明確提到具體人名
            any(keyword in query for keyword in people_search_keywords) and  # 包含人員搜索關鍵詞
            not any(keyword in query.lower() for keyword in ["文件", "文檔", "文章", "資料", "內容"])  # 不是文件相關問題
        )
        
        if is_people_search_question:
            logger.info("檢測到人員搜索問題，使用語義搜索")
            try:
                # 使用語義搜索找到相關人員
                query_embedding = self.people_manager.generate_embedding(query)
                if query_embedding:
                    # 檢查是否包含戰鬥相關關鍵詞，如果是則按戰鬥力排序
                    combat_keywords = config_manager.get_keywords("COMBAT_KEYWORDS")
                    sort_by_power = any(keyword in query.lower() for keyword in combat_keywords)
                    
                    search_results = self.people_manager.search_people_by_embedding(
                        query_embedding=query_embedding,
                        limit=3,
                        threshold=0.3,  # 較低的閾值以獲得更多結果
                        sort_by_power=sort_by_power
                    )
                    
                    if search_results:
                        # 獲取找到的人員的詳細資料
                        found_people = []
                        for result in search_results:
                            name = result["name"]
                            normalized_name = self.name_adapter.normalize_name(name)
                            profile_summary = self.profile_manager.get_other_profile_summary(normalized_name)
                            if profile_summary:
                                found_people.append({
                                    "name": normalized_name,
                                    "profile": profile_summary,
                                    "similarity": result["similarity"],
                                    "total_power": result.get("total_power", 0)
                                })
                        
                        if found_people:
                            # 構建搜索結果回答
                            search_prompt = self.personality_builder.create_people_search_prompt(query, found_people)
                            
                            # 簡化人員搜索處理
                            search_answer = self.llm.invoke(search_prompt)
                            if hasattr(search_answer, 'content'):
                                search_answer = search_answer.content
                            
                            # 修正性別代詞使用
                            if len(found_people) > 1:
                                search_answer = self._fix_gender_pronouns(search_answer, [p['name'] for p in found_people])
                            
                            # 如果搜索結果中包含自己，移除自己的圖片連結
                            if any(p['name'].lower() == self.self_name.lower() for p in found_people):
                                search_answer = self._remove_self_images(search_answer)
                            
                            return {
                                "answer": search_answer,
                                "sources": [],
                                "found_characters": [p['name'] for p in found_people]
                            }
                
                # 如果語義搜索失敗或沒有結果，繼續到文件搜索
                logger.info("人員語義搜索失敗或無結果，繼續到文件搜索")
                
            except Exception as e:
                logger.error(f"人員語義搜索時發生錯誤: {str(e)}")
                # 如果搜索失敗，繼續到文件搜索
        
        # 合併文檔內容
        if documents:
            context = "\n\n".join([doc.page_content for doc in documents])
            sources = [doc.metadata.get("source", "Unknown") for doc in documents]
        else:
            context = ""
            sources = []
        
        # 使用 chat_chain 生成答案
        logger.debug("開始調用 chat_chain.invoke()")
        response = self.chat_chain.invoke({"context": context, "question": query})
        
        # 安全處理響應
        if hasattr(response, 'content'):
            answer_content = response.content
        else:
            answer_content = str(response) if response else "抱歉，無法生成答案"
        
        logger.debug(f"chat_chain.invoke() 完成")
        
        # 返回答案和來源信息
        return {
            "answer": answer_content,
            "sources": sources,
            "found_characters": []
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
        response = self.chat_chain.invoke({"context": context, "question": question})
        
        # 安全處理響應
        if hasattr(response, 'content'):
            return response.content
        else:
            return str(response) if response else "抱歉，無法生成答案" 