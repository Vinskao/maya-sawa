import logging
from typing import Dict, List, Optional
from langchain.schema import Document
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
import os
from .name_detector import NameDetector
from .profile_manager import ProfileManager
from .personality import PersonalityPromptBuilder
from .people import PeopleWeaponManager

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
            model="gpt-4o-mini",
            temperature=0.7,
            max_tokens=2000
        )
        
        # 初始化組件
        self.name_detector = NameDetector()
        self.profile_manager = ProfileManager()
        self.personality_builder = PersonalityPromptBuilder()
        self.people_manager = PeopleWeaponManager()
        
        # 創建動態提示模板
        self._create_dynamic_prompt()
        
        # 初始化聊天鏈
        self.chat_chain = LLMChain(
            llm=self.llm,
            prompt=self.prompt_template
        )
        
        logger.info("QAChain 初始化完成")

    def _create_dynamic_prompt(self):
        """
        創建動態提示模板
        """
        # 獲取 Maya 的個人資料
        maya_profile = self.profile_manager.get_profile_summary()
        
        # 創建提示模板
        self.prompt_template = PromptTemplate(
            input_variables=["context", "question"],
            template=f"""你是 Maya，一個來自《Maya Sawa》世界的角色。以下是你的基本資料：

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
        self.profile_manager.clear_all_cache()
        logger.info("所有個人資料快取已清除")

    def get_answer(self, query: str, documents: List[Document]) -> Dict:
        """
        獲取問題的答案
        
        Args:
            query (str): 用戶的問題
            documents (List[Document]): 相關文檔列表
            
        Returns:
            Dict: 包含答案和來源的字典
        """
        try:
            # 檢測問題中提到的角色名稱
            detected_names = self.name_detector.detect_all_queried_names(query)
            logger.info(f"檢測到的角色名稱: {detected_names}")
            
            # 如果有檢測到角色名稱，優先處理角色相關問題
            if detected_names:
                logger.info("檢測到角色名稱，處理角色相關問題")
                
                # 檢查是否詢問 Maya 自己
                if "maya" in [name.lower() for name in detected_names] or "佐和" in detected_names or "真夜" in detected_names:
                    logger.info("檢測到詢問 Maya 的問題")
                    maya_summary = self.profile_manager.get_profile_summary()
                    
                    # 使用 LLM 生成自然回答
                    identity_prompt = self.personality_builder.create_identity_prompt(query, maya_summary)
                    
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
                
                # 處理其他角色的問題
                else:
                    logger.info("檢測到詢問其他角色的問題")
                    profiles = []
                    found_names = []
                    not_found = []
                    
                    for name in detected_names:
                        logger.info(f"正在處理角色: {name}")
                        profile_summary = self.profile_manager.get_other_profile_summary(name)
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
                        if hasattr(self.name_detector, '_request_detailed') and self.name_detector._request_detailed:
                            # 直接返回原始資料
                            combined_answer = "\n\n".join(profiles)
                            if not_found:
                                combined_answer += f"\n\n至於 {', '.join(not_found)}？我沒聽過這些人，你問錯人了。"
                            return {
                                "answer": combined_answer,
                                "sources": []
                            }
                        else:
                            # 使用 LLM 生成總結
                            summary_prompt = self.personality_builder.create_summary_prompt(query, combined_profiles)
                            
                            try:
                                summary_answer = self.llm.invoke(summary_prompt)
                                # 確保返回的是字符串
                                if hasattr(summary_answer, 'content'):
                                    summary_answer = summary_answer.content
                                
                                # 如果有找不到的角色，在最後加上說明
                                if not_found:
                                    summary_answer += f"\n\n至於 {', '.join(not_found)}？我沒聽過這些人，你問錯人了。"
                                
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
                maya_summary = self.profile_manager.get_profile_summary()
                
                # 使用 LLM 生成不耐煩但完整的回答
                identity_prompt = self.personality_builder.create_identity_prompt(query, maya_summary)
                
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
                                profile_summary = self.profile_manager.get_other_profile_summary(name)
                                if profile_summary:
                                    found_people.append({
                                        "name": name,
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
                                        "sources": []
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
                                        "sources": []
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