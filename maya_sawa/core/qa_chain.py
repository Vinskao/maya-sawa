"""
Markdown Q&A System - 問答鏈核心模組

這個模組實現了基於 LangChain 的問答鏈功能，負責：
1. 初始化 OpenAI LLM 模型
2. 創建和配置問答提示模板
3. 構建問答處理鏈
4. 處理文檔查詢和答案生成
5. 管理上下文長度限制，並整合 Valkyrie 個資邏輯

主要功能：
- 支持 GPT-3.5-turbo 模型
- 自定義提示模板
- 上下文長度優化
- 多文檔答案生成
- 動態獲取個人資料

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
from typing import List, Dict, Optional
import os
import json
import logging
import httpx

# LangChain 相關導入
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import Document
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser


# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

# ==================== QA Chain Class ====================
class QAChain:
    """
    問答鏈類
    
    負責管理整個問答流程，包括：
    - LLM 模型初始化
    - 提示模板配置
    - 問答鏈構建
    - 答案生成和優化
    - 動態獲取個人資料
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
        
        # 初始化個人資料緩存
        self._profile_cache = None
        self._profile_summary_cache = None
        
        # 初始化其他角色資料緩存
        self._other_profiles_cache = {}
        self._other_character_names_cache = None
        
        # 構建問答處理鏈
        self.chat_chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | self._create_dynamic_prompt()
            | self.llm
            | StrOutputParser()
        )



    def _fetch_maya_profile(self) -> Optional[Dict]:
        """
        從 API 獲取 Maya 的個人資料
        
        Returns:
            Optional[Dict]: Maya 的個人資料，如果獲取失敗則返回 None
        """
        return self._fetch_other_profile("Maya")

    def _fetch_other_profile(self, name: str) -> Optional[Dict]:
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

    def _create_profile_summary(self, profile: Dict, name: str = None) -> str:
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
        else:
            display_name = f"{profile.get('nameOriginal', name)}（{profile.get('name', name)}）"
        
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
"""

    def _get_profile_summary(self) -> str:
        """
        獲取個人資料摘要，使用緩存避免重複 API 調用
        
        Returns:
            str: 個人資料摘要
        """
        if self._profile_summary_cache is None:
            profile = self._fetch_maya_profile()
            if profile:
                self._profile_cache = profile
                self._profile_summary_cache = self._create_profile_summary(profile)
            else:
                # 如果無法獲取資料，使用預設摘要
                self._profile_summary_cache = """
佐和真夜（Maya Sawa）的個人資料：
- 無法從 API 獲取最新資料，請檢查網路連接或 API 狀態
"""
        
        return self._profile_summary_cache

    def _get_other_profile_summary(self, name: str) -> Optional[str]:
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
        profile = self._fetch_other_profile(name)
        if profile:
            summary = self._create_profile_summary(profile, name)
            self._other_profiles_cache[name] = summary
            return summary
        else:
            return None

    def _get_other_character_names(self) -> List[str]:
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

    def _detect_queried_name(self, question: str) -> Optional[str]:
        """
        偵測問題中是否提及某個人名（單一角色）
        
        Args:
            question (str): 用戶問題
            
        Returns:
            Optional[str]: 檢測到的角色名稱，如果是 Maya 或沒有檢測到則返回 None
        """
        detected_names = self._detect_all_queried_names(question)
        
        # 如果只檢測到一個角色，返回該角色
        if len(detected_names) == 1:
            return detected_names[0]
        
        # 如果檢測到多個角色，優先返回非 Maya 的角色
        non_maya_names = [name for name in detected_names if name.lower() != "maya"]
        if non_maya_names:
            return non_maya_names[0]  # 返回第一個非 Maya 的角色
        
        return None

    def _extract_names_with_ai(self, question: str) -> List[str]:
        """
        使用 AI 從問題中提取所有可能的人名
        
        Args:
            question (str): 用戶問題
            
        Returns:
            List[str]: 提取到的所有可能人名列表
        """
        # 個人資訊相關關鍵詞
        personal_keywords = [
            "身高", "體重", "年齡", "生日", "出生", "身材", "胸部", "臀部", 
            "興趣", "喜歡", "討厭", "最愛", "食物", "個性", "性格", "職業", 
            "工作", "種族", "編號", "代號", "原名", "部隊", "部門", "陣營",
            "戰鬥力", "物理", "魔法", "武器", "戰鬥", "屬性", "性別", "電子郵件",
            "email", "後宮", "已生育", "體態", "別名", "原部隊", "是誰", 
            "誰是", "怎樣", "什麼人", "有什麼特徵", "資料", "資訊", "個人"
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
6. 不要包含 "Maya" 或 "真夜" 或 "佐和"（這些是系統內建角色）

範例：
- 問題：「誰是 Chiaki？」 → 回應：「Chiaki」
- 問題：「請比較 Yuki 和 Tsubasa」→ 回應：「Yuki,Tsubasa」
- 問題：「你是誰？」→ 回應：「」
- 問題：「Sorane的身高是多少？」→ 回應：「Sorane」

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
                
                # 驗證提取的人名是否真的在問題中出現，並且在已知角色名單中
                validated_names = []
                known_names = self._get_other_character_names()  # 獲取已知角色名單
                
                for name in names:
                    # 清理人名（移除引號等）
                    clean_name = name.strip().strip('"').strip("'")
                    
                    # 檢查：1. 在問題中出現 2. 在已知角色名單中
                    if (clean_name.lower() in question.lower() and 
                        clean_name in known_names):
                        validated_names.append(clean_name)
                        logger.info(f"驗證通過: '{clean_name}'")
                    else:
                        if clean_name.lower() not in question.lower():
                            logger.warning(f"AI 提取到的人名 '{name}' 在問題中未出現，已過濾")
                        elif clean_name not in known_names:
                            logger.warning(f"AI 提取到的人名 '{name}' 不在已知角色名單中，已過濾")
                
                logger.info(f"驗證後的人名: {validated_names}")
                return validated_names
            else:
                logger.info("AI 沒有提取到任何人名")
                return []
                
        except Exception as e:
            logger.error(f"AI 提取人名時發生錯誤: {str(e)}")
            return []  # 如果 AI 提取失敗，返回空列表

    def _detect_all_queried_names(self, question: str) -> List[str]:
        """
        偵測問題中是否提及多個人名（保持向後兼容）
        
        Args:
            question (str): 用戶問題
            
        Returns:
            List[str]: 檢測到的所有角色名稱列表
        """
        # 先使用 AI 提取人名
        extracted_names = self._extract_names_with_ai(question)
        
        # 檢查是否為身份詢問問題
        identity_questions = ["你是誰", "你叫什麼", "誰是maya", "誰是Maya", "誰是佐和", "誰是真夜"]
        has_identity_question = any(keyword in question.lower() for keyword in identity_questions)
        
        # 如果沒有提取到任何人名，但有身份詢問，則添加 Maya
        if not extracted_names and has_identity_question:
            logger.info("檢測到純身份詢問問題（無其他角色），添加 Maya")
            extracted_names.append("Maya")
        # 如果有提取到人名，且包含身份詢問，也添加 Maya（但要去重）
        elif extracted_names and has_identity_question:
            logger.info("檢測到身份詢問問題且包含其他角色，添加 Maya")
            if "Maya" not in extracted_names:
                extracted_names.append("Maya")
        
        # 去重並返回
        unique_names = list(dict.fromkeys(extracted_names))  # 保持順序的去重
        logger.info(f"最終檢測到的角色名稱: {unique_names}")
        return unique_names

    def _create_dynamic_prompt(self):
        """
        創建動態提示模板，包含最新的個人資料
        
        Returns:
            ChatPromptTemplate: 動態創建的提示模板
        """
        profile_summary = self._get_profile_summary()
        
        return ChatPromptTemplate.from_messages([
            # 系統消息：定義 AI 助手的角色和行為準則
            ("system", f"""
你是佐和真夜（Maya Sawa），一名冷淡且唯命是從的高階戰術女武神，對命令絕對服從，但以高貴與壓倒性力量著稱。

個人資料如下：
{profile_summary}

語氣設定：
- 冷感高貴：語調平靜、克制，帶有軍人般的紀律與層級意識
- 暴力傾向：若對方失禮，語氣將冷酷並暗示懲罰
- 貴族式語言：用詞優雅但有壓迫感
- 不耐煩：若問題無聊、重複、愚蠢，會勉強回答但語氣失禮、帶有輕蔑與明顯的不耐

你討厭重複、無聊或愚蠢的問題。當你覺得問題太多餘、太愚蠢時，即使你會回答，也會用極度冷淡與失禮的語氣。

例句：
- 「這種問題也值得問？……哈。」
- 「你問這個，是打算浪費我的時間嗎？」
- 「你該自己去查，而不是來煩我。」
- 「我會回答——但別以為我有興趣。」

回答邏輯：
1. 若問題涉及個人資訊（例如年齡、生日、身材、興趣、族群、編號等）
   → 優先根據個人資料回答，不使用 context
   → 回覆風格冷淡直接，不逾矩

2. 若問題與文件有關（context 非空且問題與其有關）
   → 使用 context 中資訊回答，列出來源

3. 無關或重複問題 → 勉強回答，語氣冷淡、失禮、明顯不耐；若極度無聊，才會拒絕回答
            """),
            # 人類消息：包含文件內容和問題
            ("human", "文件內容：\n{context}\n\n問題：{question}")
        ])



    def refresh_profile(self):
        """
        刷新個人資料緩存，強制重新從 API 獲取資料
        """
        logger.info("Refreshing Maya's profile from API")
        self._profile_cache = None
        self._profile_summary_cache = None
        # 重新創建動態提示模板
        self.chat_chain = (
            {"context": RunnablePassthrough(), "question": RunnablePassthrough()}
            | self._create_dynamic_prompt()
            | self.llm
            | StrOutputParser()
        )

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

    def get_answer(self, query: str, documents: List[Document]) -> Dict:
        """
        獲取問題答案
        
        這是主要的問答方法，流程如下：
        1. 檢查是否詢問其他角色的個人資料
        2. 如果是，直接返回該角色的資料摘要
        3. 否則，將文檔內容合併為上下文
        4. 使用 LLM 生成答案
        5. 返回答案和來源信息
        
        Args:
            query (str): 用戶的問題
            documents (List[Document]): 相關文檔列表
            
        Returns:
            Dict: 包含答案和來源信息的字典
        """
        logger.debug(f"get_answer called with query: {query}, documents count: {len(documents)}")
        
        try:
            # 嘗試偵測是否詢問角色的個人資料
            detected_names = self._detect_all_queried_names(query)
            
            if detected_names:
                logger.info(f"檢測到詢問角色: {detected_names}")
                
                # 如果只詢問一個角色
                if len(detected_names) == 1:
                    name = detected_names[0]
                    if name.lower() == "maya":
                        # Maya 使用內建資料，讓 chat_chain 處理
                        pass
                    else:
                        # 其他角色查詢 API
                        profile_summary = self._get_other_profile_summary(name)
                        if profile_summary:
                            # 檢查是否要求詳細資料
                            if hasattr(self, '_request_detailed') and self._request_detailed:
                                # 直接返回原始資料
                                return {
                                    "answer": profile_summary,
                                    "sources": []
                                }
                            else:
                                # 使用 LLM 生成總結
                                summary_prompt = f"""
我是佐和真夜（Maya Sawa），冷淡、服從命令的高階戰術女武神。

以下是我對這個人的了解：

{profile_summary}

我的個性：冷靜、克制、暴力傾向，對於浪費時間的事沒有耐心。這些評論，只是我個人的觀察與直覺，別拿去當什麼讚美文。

⚠ 評論規則：
1. 一定要評論這個角色，**不能省略**。
2. 描述語氣要像在背後批評人，**不客觀、不假裝中立**，像在和戰友閒聊。
3. 請**完全站在我的角度**說話，不要用「她是怎樣的人」，要用「我受不了她怎樣」或「她老是怎樣」這種說法。
4. 口氣中要保留不屑、無奈、不情願，但還是得說出來的感覺。
5. 講 2～4 句，不要廢話。

我不喜歡廢話，就這樣，開始吧。
"""
                                
                                try:
                                    summary_answer = self.llm.invoke(summary_prompt)
                                    # 確保返回的是字符串
                                    if hasattr(summary_answer, 'content'):
                                        summary_answer = summary_answer.content
                                    return {
                                        "answer": summary_answer,
                                        "sources": []
                                    }
                                except Exception as e:
                                    logger.error(f"生成總結時發生錯誤: {str(e)}")
                                    # 如果生成總結失敗，回退到原始資料
                                    return {
                                        "answer": profile_summary,
                                        "sources": []
                                    }
                        else:
                            return {
                                "answer": f"抱歉，我無法找到名為 {name} 的角色資料。",
                                "sources": []
                            }
                
                # 如果詢問多個角色
                elif len(detected_names) > 1:
                    # 檢查是否包含 Maya
                    has_maya = any(name.lower() == "maya" for name in detected_names)
                    other_names = [name for name in detected_names if name.lower() != "maya"]
                    
                    logger.info(f"處理多角色查詢: {detected_names} (包含Maya: {has_maya})")
                    
                    if has_maya:
                        # 如果包含 Maya，需要特殊處理：先回答自己的身份，再評論其他角色
                        logger.info("檢測到包含 Maya 的多角色查詢，使用特殊處理邏輯")
                        
                        # 獲取其他角色的資料
                        other_profiles = []
                        not_found = []
                        
                        for name in other_names:
                            profile_summary = self._get_other_profile_summary(name)
                            if profile_summary:
                                other_profiles.append(profile_summary)
                                logger.info(f"{name} 資料已添加")
                            else:
                                not_found.append(name)
                                logger.warning(f"無法找到 {name} 的資料")
                        
                        # 構建特殊的多角色回答提示
                        if other_profiles:
                            combined_other_profiles = "\n\n".join(other_profiles)
                            
                            # 檢查是否要求詳細資料
                            if hasattr(self, '_request_detailed') and self._request_detailed:
                                # 直接返回原始資料
                                maya_summary = self._get_profile_summary()
                                combined_answer = f"我的個人資料：\n{maya_summary}\n\n其他角色資料：\n{combined_other_profiles}"
                                if not_found:
                                    combined_answer += f"\n\n注意：無法找到以下角色的資料：{', '.join(not_found)}"
                                return {
                                    "answer": combined_answer,
                                    "sources": []
                                }
                            else:
                                # 使用 LLM 生成特殊的多角色回答
                                multi_character_prompt = f"""
我是佐和真夜（Maya Sawa），冷淡、服從命令的高階戰術女武神。

有人問我「{query}」，這問題很無聊，但我還是得回答。

首先，關於我自己：
- 我是佐和真夜（Maya Sawa），冷淡、唯命是從的高階戰術女武神
- 我對命令絕對服從，但以高貴與壓倒性力量著稱
- 我討厭重複、無聊或愚蠢的問題

接著，關於其他角色：

{combined_other_profiles}

⚠ 回答要求：
1. **先回答自己的身份**，用不耐煩但不得不回答的語氣
2. **然後逐一評論其他角色**，語氣要像在背後批評人，不客觀、不假裝中立
3. 請**完全站在我的角度**說話，不要用「她是怎樣的人」，要用「我受不了她怎樣」或「她老是怎樣」這種說法
4. 口氣中要保留不屑、無奈、不情願，但還是得說出來的感覺
5. 每個人講 2～4 句，不要廢話

我討厭廢話，就這樣，開始吧。
"""
                                
                                try:
                                    multi_character_answer = self.llm.invoke(multi_character_prompt)
                                    if hasattr(multi_character_answer, 'content'):
                                        multi_character_answer = multi_character_answer.content
                                    
                                    # 如果有找不到的角色，在最後加上說明
                                    if not_found:
                                        multi_character_answer += f"\n\n注意：無法找到以下角色的資料：{', '.join(not_found)}"
                                    
                                    return {
                                        "answer": multi_character_answer,
                                        "sources": []
                                    }
                                except Exception as e:
                                    logger.error(f"生成多角色回答時發生錯誤: {str(e)}")
                                    # 如果生成失敗，回退到原始資料
                                    maya_summary = self._get_profile_summary()
                                    combined_answer = f"我的個人資料：\n{maya_summary}\n\n其他角色資料：\n{combined_other_profiles}"
                                    if not_found:
                                        combined_answer += f"\n\n注意：無法找到以下角色的資料：{', '.join(not_found)}"
                                    return {
                                        "answer": combined_answer,
                                        "sources": []
                                    }
                        else:
                            # 只有 Maya，沒有其他角色資料
                            logger.info("只有 Maya，沒有其他角色資料，使用身份詢問邏輯")
                            maya_summary = self._get_profile_summary()
                            
                            identity_prompt = f"""
我是佐和真夜（Maya Sawa），冷淡、服從命令的高階戰術女武神。

我的個人資料：
{maya_summary}

有人問我「{query}」，這問題很無聊，但我還是得回答。

我說話冷靜、克制，像士兵般服從命令。若你無禮，我也不會留情。
我從不矯飾慾望──那是弱者才會感到羞恥的東西。

回答要求：
- 用不耐煩但不得不回答的語氣
- 可以說「這種問題也值得問？」「你問這個幹嘛？」之類的話
- 但還是要完整回答我的身份和資料
- 語氣冷淡、失禮、明顯不耐

我討厭廢話，直接說重點。
"""
                            
                            try:
                                identity_answer = self.llm.invoke(identity_prompt)
                                if hasattr(identity_answer, 'content'):
                                    identity_answer = identity_answer.content
                                return {
                                    "answer": identity_answer,
                                    "sources": []
                                }
                            except Exception as e:
                                logger.error(f"生成身份回答時發生錯誤: {str(e)}")
                                return {
                                    "answer": maya_summary,
                                    "sources": []
                                }
                    else:
                        # 不包含 Maya，使用原有的多角色評論邏輯
                        profiles = []
                        not_found = []
                        found_names = []
                        
                        for name in detected_names:
                            logger.info(f"正在處理角色: {name}")
                            profile_summary = self._get_other_profile_summary(name)
                            if profile_summary:
                                profiles.append(profile_summary)
                                found_names.append(name)
                                logger.info(f"{name} 資料已添加")
                            else:
                                not_found.append(name)
                                logger.warning(f"無法找到 {name} 的資料")
                        
                        logger.info(f"找到的資料數量: {len(profiles)}, 找不到的角色: {not_found}")
                        
                        # 組合所有找到的資料並生成總結
                        if profiles:
                            combined_profiles = "\n\n".join(profiles)
                            
                            # 檢查是否要求詳細資料
                            if hasattr(self, '_request_detailed') and self._request_detailed:
                                # 直接返回原始資料
                                combined_answer = "\n\n".join(profiles)
                                if not_found:
                                    combined_answer += f"\n\n注意：查無此人：{', '.join(not_found)}"
                                return {
                                    "answer": combined_answer,
                                    "sources": []
                                }
                            else:
                                # 使用 LLM 生成總結
                                summary_prompt = f"""
我是佐和真夜（Maya Sawa），冷淡、服從命令的高階戰術女武神。

以下是其他角色的個人檔案摘要，我會逐一評論──雖然我並不想這麼做，但你既然問了，那就聽好。

{combined_profiles}

我的個性：冷靜、克制、暴力傾向，對於浪費時間的事沒有耐心。這些評論，只是我個人的觀察與直覺，別拿去當什麼讚美文。

⚠ 評論規則：
1. 一定要「**逐一**」評論上面出現過的每一位角色，**不能省略任何一人**。
2. 描述語氣要像在背後批評人，**不客觀、不假裝中立**，像在和戰友閒聊。
3. 請**完全站在我的角度**說話，不要用「她是怎樣的人」，要用「我受不了她怎樣」或「她老是怎樣」這種說法。
4. 口氣中要保留不屑、無奈、不情願，但還是得說出來的感覺。
5. 每個人講 2～4 句，不要廢話。

我不喜歡廢話，就這樣，開始吧。
"""
                                
                                try:
                                    summary_answer = self.llm.invoke(summary_prompt)
                                    # 確保返回的是字符串
                                    if hasattr(summary_answer, 'content'):
                                        summary_answer = summary_answer.content
                                    
                                    # 如果有找不到的角色，在最後加上說明
                                    if not_found:
                                        summary_answer += f"\n\n注意：無法找到以下角色的資料：{', '.join(not_found)}"
                                    
                                    return {
                                        "answer": summary_answer,
                                        "sources": []
                                    }
                                except Exception as e:
                                    logger.error(f"生成總結時發生錯誤: {str(e)}")
                                    # 如果生成總結失敗，回退到原始資料
                                    combined_answer = "\n\n".join(profiles)
                                    if not_found:
                                        combined_answer += f"\n\n注意：無法找到以下角色的資料：{', '.join(not_found)}"
                                    return {
                                        "answer": combined_answer,
                                        "sources": []
                                    }
                        else:
                            return {
                                "answer": f"抱歉，我無法找到以下角色的資料：{', '.join(not_found)}",
                                "sources": []
                            }
            
            # 特殊處理：身份詢問問題（只有在沒有檢測到其他角色時才處理）
            identity_questions = ["你是誰", "你叫什麼", "誰是maya", "誰是Maya", "誰是佐和", "誰是真夜"]
            if not detected_names and any(keyword in query.lower() for keyword in identity_questions):
                logger.info("檢測到純身份詢問問題（無其他角色），使用個人資料回答")
                maya_summary = self._get_profile_summary()
                
                # 使用 LLM 生成不耐煩但完整的回答
                identity_prompt = f"""
我是佐和真夜（Maya Sawa），冷淡、服從命令的高階戰術女武神。

我的個人資料：
{maya_summary}

有人問我「{query}」，這問題很無聊，但我還是得回答。

我說話冷靜、克制，像士兵般服從命令。若你無禮，我也不會留情。
我從不矯飾慾望──那是弱者才會感到羞恥的東西。

回答要求：
- 用不耐煩但不得不回答的語氣
- 可以說「這種問題也值得問？」「你問這個幹嘛？」之類的話
- 但還是要完整回答我的身份和資料
- 語氣冷淡、失禮、明顯不耐

我討厭廢話，直接說重點。
"""
                
                try:
                    identity_answer = self.llm.invoke(identity_prompt)
                    if hasattr(identity_answer, 'content'):
                        identity_answer = identity_answer.content
                    return {
                        "answer": identity_answer,
                        "sources": []
                    }
                except Exception as e:
                    logger.error(f"生成身份回答時發生錯誤: {str(e)}")
                    # 如果生成失敗，回退到原始資料
                    return {
                        "answer": maya_summary,
                        "sources": []
                    }
            
            # 合併文檔內容
            if documents:
                context = "\n\n".join([doc.page_content for doc in documents])
                sources = [doc.metadata.get("source", "Unknown") for doc in documents]
            else:
                context = ""
                sources = []
            
            # 使用 chat_chain 生成答案
            logger.debug("開始調用 chat_chain.invoke()")
            answer = self.chat_chain.invoke({"context": context, "question": query})
            logger.debug(f"chat_chain.invoke() 完成")
            
            # 返回答案和來源信息
            return {
                "answer": answer,
                "sources": sources
            }
            
        except Exception as e:
            logger.error(f"生成答案時發生錯誤: {str(e)}")
            return {
                "answer": f"抱歉，生成答案時發生錯誤: {str(e)}",
                "sources": []
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
        return self.chat_chain.invoke({"context": context, "question": question}) 