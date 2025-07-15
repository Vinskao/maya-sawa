import logging
from typing import Dict, List, Optional
from langchain.schema import Document
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
import os
from maya_sawa.people import NameDetector, ProfileManager, PersonalityPromptBuilder, PeopleWeaponManager, NameAdapter
from maya_sawa.core.config import Config

logger = logging.getLogger(__name__)

class QAChain:
    """
    問答鏈，整合了名稱檢測、個人資料管理和個性化提示構建功能
    """
    
    def __init__(self):
        """
        初始化 QAChain
        """
        # 初始化 OpenAI 模型
        self.llm = ChatOpenAI(
            model="gpt-4.1-nano",
            temperature=0.7,
            max_tokens=2000
        )
        
        # 初始化組件
        self.name_detector = NameDetector(llm=self.llm, get_known_names_func=self._get_known_names)
        self.profile_manager = ProfileManager()
        self.personality_builder = PersonalityPromptBuilder()
        self.people_manager = PeopleWeaponManager()
        self.name_adapter = NameAdapter()
        
        # 創建動態提示模板
        self._create_dynamic_prompt()
        
        # 初始化聊天鏈
        self.chat_chain = self.prompt_template | self.llm
        
        logger.info("QAChain 初始化完成")

    def _get_known_names(self) -> List[str]:
        """
        獲取已知的角色名稱列表
        
        Returns:
            List[str]: 已知角色名稱列表
        """
        try:
            # 從 people manager 獲取所有角色名稱
            people_data = self.people_manager.fetch_people_data()
            if people_data:
                names = [person.get('name', '') for person in people_data if person.get('name')]
                # 添加 Maya 作為系統內建角色
                if 'Maya' not in names:
                    names.append('Maya')
                return names
            else:
                # 如果無法獲取，至少返回 Maya
                return ['Maya']
        except Exception as e:
            logger.error(f"獲取已知角色名稱時發生錯誤: {str(e)}")
            # 如果發生錯誤，至少返回 Maya
            return ['Maya']

    def _create_dynamic_prompt(self):
        """
        創建動態提示模板
        """
        # 獲取 Maya 的個人資料
        maya_profile = self.profile_manager.get_profile_summary()
        
        # 創建提示模板
        self.prompt_template = PromptTemplate(
            input_variables=["context", "question"],
            template=f"""你是 Maya，一個來自遠古合成惑星的女武神。以下是你的基本資料：

{maya_profile}

請以 Maya 的身份回答問題，保持你的個性和語氣。回答要自然、有趣，不要直接複製資料內容。

如果提供了上下文資料，請基於這些資料回答問題。如果沒有提供上下文，請基於你的知識回答。

問題：{{question}}

上下文：{{context}}

請回答："""
        )

    def refresh_profile(self):
        """
        刷新 Maya 的個人資料
        """
        self.profile_manager.refresh_profile()
        self._create_dynamic_prompt()
        logger.info("Maya 個人資料已刷新")

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

    def get_answer(self, query: str, documents: List[Document]) -> Dict:
        """
        獲取問題的答案
        
        Args:
            query (str): 用戶的問題
            documents (List[Document]): 相關文檔列表
            
        Returns:
            Dict: 包含答案、來源和找到的角色的字典
        """
        try:
            # 檢測問題中提到的角色名稱
            detected_names = self.name_detector.detect_all_queried_names(query)
            logger.info(f"檢測到的角色名稱: {detected_names}")
            
            # 如果有檢測到角色名稱，優先處理角色相關問題
            if detected_names:
                logger.info("檢測到角色名稱，處理角色相關問題")
                
                # 分離 Maya 和其他角色
                maya_names = [name for name in detected_names if name.lower() == "maya" or name in ["佐和", "真夜"]]
                other_names = [name for name in detected_names if name not in maya_names]
                
                logger.info(f"Maya 相關角色: {maya_names}, 其他角色: {other_names}")
                
                # 收集所有角色的資料
                all_profiles = []
                found_names = []
                not_found = []
                
                # 處理 Maya 相關問題
                if maya_names:
                    logger.info("處理 Maya 相關問題")
                    maya_summary = self.profile_manager.get_profile_summary()
                    if maya_summary:
                        all_profiles.append(f"=== Maya 的資料 ===\n{maya_summary}")
                        found_names.append("Maya")
                        logger.info("Maya 資料已添加")
                    else:
                        not_found.append("Maya")
                        logger.warning("無法找到 Maya 的資料")
                
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
                            if "Maya" in found_names and len(found_names) > 1:
                                # 分離 Maya 以外的資料供評論
                                other_profiles_block = "\n\n".join([
                                    p for p in all_profiles if not p.startswith("=== Maya") and not p.startswith("=== 佐和")
                                ])
                                summary_prompt = self.personality_builder.create_self_and_other_prompt(
                                    query,
                                    maya_summary if 'maya_summary' in locals() else self.profile_manager.get_profile_summary(),
                                    other_profiles_block,
                                    [n for n in found_names if n.lower() != "maya"]
                                )
                            else:
                                summary_prompt = self.personality_builder.create_multi_character_prompt(query, combined_profiles, found_names)
                        else:
                            # 單一角色（且不是 Maya）
                            summary_prompt = self.personality_builder.create_data_answer_prompt(query, combined_profiles)
                        
                        try:
                            summary_answer = self.llm.invoke(summary_prompt)
                            # 確保返回的是字符串
                            if hasattr(summary_answer, 'content'):
                                summary_answer = summary_answer.content
                            
                            # 空答案或拒絕容錯
                            refusal_keywords = [
                                "無法為你服務", "無法為您服務", "請提供", "評論的角色名", "否則我無法為", "抱歉", "cannot", "unable", "Please provide", "provide the character",
                                "想知道", "沒空", "自己去查", "浪費時間"
                            ]
                            # 若答案過短 (<100 字) 或包含拒絕關鍵詞，視為無效
                            if (
                                not summary_answer or
                                len(summary_answer.strip()) < 100 or
                                any(k in summary_answer for k in refusal_keywords)
                            ):
                                logger.warning("LLM 回答可能無效，嘗試使用加強版提示重新生成")
                                simple_prompt = (
                                    "以冷淡、高貴、不耐的語氣，用第一人稱 (Maya Sawa) 逐一評論以下角色的資料。"
                                    "對每位角色請根據戰力規則調整態度：Wavo → 臣服；總戰力高於我 → 厭惡但尊重；"
                                    "總戰力低於我 → 肆無忌憚地辱罵、貶低、壓制；與我相當 → 冷淡高貴。"
                                    "嚴禁逐條列清單或複製資料，必須把胸部、臀部、身高、體重及三項戰力自然嵌入 3~5 句評論。"
                                    "每位角色評論完後立即換行，列出四條圖片 URL (基本/戰鬥/毀壞/迷人)，角色順序依資料給出。\n\n"
                                    f"{combined_profiles}"
                                )
                                try:
                                    summary_answer_retry = self.llm.invoke(simple_prompt)
                                    if hasattr(summary_answer_retry, 'content'):
                                        summary_answer_retry = summary_answer_retry.content
                                        # 若重試成功且內容足夠，採用
                                        if summary_answer_retry and len(summary_answer_retry.strip()) > 20:
                                            summary_answer = summary_answer_retry
                                        else:
                                            logger.warning("簡化提示仍然無效，使用原始資料作為回答")
                                            summary_answer = combined_profiles
                                    else:
                                        logger.error("簡化提示調用失敗，使用原始資料作為回答")
                                        summary_answer = combined_profiles
                                except Exception as _:
                                    logger.error("簡化提示調用失敗，使用原始資料作為回答")
                                    summary_answer = combined_profiles
                            
                            # 如果有找不到的角色，在最後加上說明
                            if not_found:
                                summary_answer += f"\n\n至於 {', '.join(not_found)}？我沒聽過這些人，你問錯人了。"
                            
                            # 移除舊的自動補充段落邏輯，避免插入原始資料破壞段落格式
                            
                            return {
                                "answer": summary_answer,
                                "sources": [],
                                "found_characters": found_names
                            }
                        except Exception as e:
                            logger.error(f"生成總結時發生錯誤: {str(e)}")
                            # 如果生成總結失敗，回退到原始資料
                            combined_answer = "\n\n".join(all_profiles)
                            if not_found:
                                combined_answer += f"\n\n注意：無法找到以下角色的資料：{', '.join(not_found)}"
                            return {
                                "answer": combined_answer,
                                "sources": [],
                                "found_characters": found_names
                            }
                else:
                    return {
                        "answer": f"抱歉，我無法找到以下角色的資料：{', '.join(not_found)}",
                        "sources": [],
                        "found_characters": []
                    }
            
            # 特殊處理：身份詢問問題和針對 Maya 的個人資訊問題
            # 身份詢問關鍵詞（中文 & 英文常見寫法）
            identity_questions = [
                "你是誰", "你叫什麼", "妳是誰", "妳叫什麼",  # 中文
                "who are you", "who r u", "who are u",           # 英文
                "誰是maya", "誰是Maya", "誰是佐和", "誰是真夜"
            ]
            maya_personal_questions = ["你身高", "你體重", "你年齡", "你生日", "你身材", "你胸部", "你臀部", 
                                     "你興趣", "你喜歡", "你討厭", "你最愛", "你食物", "你個性", "你性格", 
                                     "你職業", "你工作", "你種族", "你編號", "你代號", "你原名", "你部隊", 
                                     "你部門", "你陣營", "你戰鬥力", "你物理", "你魔法", "你武器", "你戰鬥", 
                                     "你屬性", "你性別", "你電子郵件", "你email", "你後宮", "你已生育", 
                                     "你體態", "你別名", "你原部隊"]
            
            # 檢查是否為認識類問題（優先處理）
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
                            
                            # 使用 LLM 生成個性化回答 (視角色數調整)
                            if len(found_names) > 1:
                                recognition_prompt = self.personality_builder.create_multi_character_prompt(query, combined_profiles, found_names)
                            else:
                                recognition_prompt = self.personality_builder.create_data_answer_prompt(query, combined_profiles)
                            logger.info(f"Recognition prompt length: {len(recognition_prompt)} characters")
                            
                            try:
                                logger.info("Calling LLM for recognition answer...")
                                recognition_answer = self.llm.invoke(recognition_prompt)
                                logger.info(f"LLM response type: {type(recognition_answer)}")
                                if hasattr(recognition_answer, 'content'):
                                    recognition_answer = recognition_answer.content
                                    logger.info(f"LLM response content length: {len(recognition_answer)} characters")

                                # === 無效回答檢測與重試 ===
                                refusal_keywords = [
                                    "無法為你服務", "無法為您服務", "請提供", "評論的角色名", "否則我無法為", "抱歉",
                                    "cannot", "unable", "Please provide", "provide the character",
                                    "想知道", "沒空", "自己去查", "浪費時間"
                                ]

                                if (
                                    not recognition_answer or
                                    len(recognition_answer.strip()) < 100 or
                                    any(k in recognition_answer for k in refusal_keywords)
                                ):
                                    logger.warning("Recognition LLM 回答可能無效，嘗試使用加強版提示重新生成")

                                    simple_prompt = (
                                        "以冷淡、高貴、不耐的語氣，用第一人稱 (Maya Sawa) 逐一評論以下角色的資料。"
                                        "請依戰力規則（高 → 厭惡尊重；低 → 毀滅式嘲諷；同級 → 冷淡高貴）調整語氣。"
                                        "不要逐條列清單，也不得複製資料，需將身高、體重及戰力自然嵌入 3~5 句評論。"
                                        "每位角色評論後換行列出四條圖片 URL (基本/戰鬥/毀壞/迷人)。\n\n"
                                        f"{combined_profiles}"
                                    )

                                    try:
                                        recognition_answer_retry = self.llm.invoke(simple_prompt)
                                        if hasattr(recognition_answer_retry, 'content'):
                                            recognition_answer_retry = recognition_answer_retry.content

                                        if recognition_answer_retry and len(recognition_answer_retry.strip()) > 50:
                                            recognition_answer = recognition_answer_retry
                                            logger.info("簡化提示成功生成有效回答")
                                        else:
                                            logger.warning("簡化提示仍無效，保留原始回答")
                                    except Exception as _:
                                        logger.error("簡化提示調用失敗，保留原始回答")

                                # 如果有找不到的角色，在最後加上說明
                                if not_found_names:
                                    recognition_answer += f"\n\n至於 {', '.join(not_found_names)}？沒聽過這個人。"
                                
                                logger.info("Returning recognition answer")
                                return {
                                    "answer": recognition_answer,
                                    "sources": [],
                                    "found_characters": found_names
                                }
                            except Exception as e:
                                logger.error(f"生成認識類回答時發生錯誤: {str(e)}")
                                # 如果生成失敗，回退到簡單回答
                                fallback_answer = f"認識啊，{', '.join(found_names)} 我當然認識。"
                                if not_found_names:
                                    fallback_answer += f"\n\n至於 {', '.join(not_found_names)}？沒聽過這個人。"
                                return {
                                    "answer": fallback_answer,
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
            
            is_maya_question = (
                not detected_names and  # 沒有檢測到其他角色
                (any(keyword in query.lower() for keyword in identity_questions) or  # 身份詢問
                 any(keyword in query for keyword in maya_personal_questions))  # 針對 Maya 的個人資訊
            )
            
            if is_maya_question:
                logger.info("檢測到針對 Maya 的問題（身份詢問或個人資訊），使用個人資料回答")
                maya_summary = self.profile_manager.get_profile_summary()
                
                # 使用 LLM 生成不耐煩但完整的回答
                identity_prompt = self.personality_builder.create_identity_prompt(query, maya_summary)
                
                try:
                    identity_answer = self.llm.invoke(identity_prompt)
                    if hasattr(identity_answer, 'content'):
                        identity_answer = identity_answer.content
                    return {
                        "answer": identity_answer,
                        "sources": [],
                        "found_characters": ["Maya"]
                    }
                except Exception as e:
                    logger.error(f"生成身份回答時發生錯誤: {str(e)}")
                    # 如果生成失敗，回退到原始資料
                    return {
                        "answer": maya_summary,
                        "sources": [],
                        "found_characters": ["Maya"]
                    }
            
            # 特殊處理：人員語義搜索（當問題涉及人員但沒有明確提到具體人名時）
            people_search_keywords = [
                "找", "推薦", "介紹", "誰", "哪個", "什麼人", "怎樣的人", "什麼樣的人",
                "喜歡", "討厭", "擅長", "職業", "種族", "陣營", "部隊", "部門",
                "身高", "體重", "年齡", "身材", "個性", "性格", "興趣", "愛好"
            ]
            
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
                        combat_keywords = ["戰鬥", "戰力", "強", "厲害", "power", "combat", "fight"]
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
                                
                                try:
                                    search_answer = self.llm.invoke(search_prompt)
                                    if hasattr(search_answer, 'content'):
                                        search_answer = search_answer.content
                                    return {
                                        "answer": search_answer,
                                        "sources": [],
                                        "found_characters": [p['name'] for p in found_people]
                                    }
                                except Exception as e:
                                    logger.error(f"生成人員搜索回答時發生錯誤: {str(e)}")
                                    # 如果生成失敗，回退到簡單的結果列表
                                    answer_parts = [f"根據你的問題「{query}」，我找到了以下相關人員："]
                                    for person in found_people:
                                        power_info = f" (總戰力: {person.get('total_power', 0)})" if person.get('total_power') else ""
                                        answer_parts.append(f"\n• {person['name']}{power_info} (相似度: {person['similarity']})")
                                    return {
                                        "answer": "\n".join(answer_parts),
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
            answer_content = self.chat_chain.invoke({"context": context, "question": query}).content
            logger.debug(f"chat_chain.invoke() 完成")
            
            # 返回答案和來源信息
            return {
                "answer": answer_content,
                "sources": sources,
                "found_characters": []
            }
            
        except Exception as e:
            logger.error(f"生成答案時發生錯誤: {str(e)}")
            return {
                "answer": f"抱歉，生成答案時發生錯誤: {str(e)}",
                "sources": [],
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
        return self.chat_chain.invoke({"context": context, "question": question}).content 