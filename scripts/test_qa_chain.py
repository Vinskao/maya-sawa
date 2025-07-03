#!/usr/bin/env python3
"""
測試 QA Chain 問答功能

這個腳本用於測試：
1. QA Chain 的問答功能
2. 個人資料動態獲取
3. 不同類型問題的回答

作者: Maya Sawa Team
版本: 0.1.0
"""

import sys
import os
from typing import List

# 添加項目根目錄到 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maya_sawa.core.qa_chain import QAChain
from langchain.schema import Document

def test_qa_chain_questions():
    """
    測試 QA Chain 的問答功能
    """
    print("=== 測試 QA Chain 問答功能 ===")
    
    try:
        # 創建 QA Chain 實例
        qa_chain = QAChain()
        print("✅ QA Chain 實例創建成功")
        
        # 測試問題列表
        test_questions = [
            "你的名字是什麼？",
            "你的戰鬥力如何？",
            "你的身高和體重是多少？",
            "你喜歡什麼食物？",
            "你的部隊是什麼？",
            "你的個性如何？",
            "你今年幾歲？",
            "什麼是量子物理學？",  # 無關問題
            "今天天氣如何？",      # 無關問題
        ]
        
        # 創建一些測試文檔
        test_documents = [
            Document(
                page_content="這是一個測試文檔，包含一些技術信息。",
                metadata={"source": "test_doc_1.txt"}
            ),
            Document(
                page_content="另一個測試文檔，關於系統架構。",
                metadata={"source": "test_doc_2.txt"}
            )
        ]
        
        print(f"\n開始測試 {len(test_questions)} 個問題...")
        
        for i, question in enumerate(test_questions, 1):
            print(f"\n--- 問題 {i}: {question} ---")
            
            try:
                # 使用 get_answer 方法
                result = qa_chain.get_answer(question, test_documents)
                answer = result.get("answer", "無答案")
                sources = result.get("sources", [])
                
                print(f"回答: {answer}")
                if sources:
                    print(f"來源: {sources}")
                    
            except Exception as e:
                print(f"❌ 回答失敗: {str(e)}")
        
        print("\n✅ 所有問題測試完成")
        return True
        
    except Exception as e:
        print(f"❌ QA Chain 測試失敗: {str(e)}")
        return False

def test_profile_refresh():
    """
    測試個人資料刷新功能
    """
    print("\n=== 測試個人資料刷新功能 ===")
    
    try:
        qa_chain = QAChain()
        
        # 獲取初始個人資料
        print("獲取初始個人資料...")
        initial_summary = qa_chain._get_profile_summary()
        print(f"初始摘要長度: {len(initial_summary)} 字符")
        
        # 刷新個人資料
        print("刷新個人資料...")
        qa_chain.refresh_profile()
        
        # 獲取刷新後的個人資料
        print("獲取刷新後的個人資料...")
        refreshed_summary = qa_chain._get_profile_summary()
        print(f"刷新後摘要長度: {len(refreshed_summary)} 字符")
        
        # 檢查是否成功刷新
        if initial_summary != refreshed_summary:
            print("✅ 個人資料成功刷新")
        else:
            print("⚠️  個人資料未變化（可能是相同的資料）")
        
        return True
        
    except Exception as e:
        print(f"❌ 個人資料刷新測試失敗: {str(e)}")
        return False

def test_simple_qa():
    """
    測試簡單的問答功能
    """
    print("\n=== 測試簡單問答功能 ===")
    
    try:
        qa_chain = QAChain()
        
        # 測試簡單問題
        question = "你的代號是什麼？"
        context = "這是一個測試上下文。"
        
        print(f"問題: {question}")
        print(f"上下文: {context}")
        
        answer = qa_chain.get_answer_from_file(question, context)
        print(f"回答: {answer}")
        
        print("✅ 簡單問答測試成功")
        return True
        
    except Exception as e:
        print(f"❌ 簡單問答測試失敗: {str(e)}")
        return False

def main():
    """
    主函數
    """
    print("QA Chain 問答功能測試")
    print("=" * 50)
    
    # 測試問答功能
    qa_success = test_qa_chain_questions()
    
    # 測試個人資料刷新
    refresh_success = test_profile_refresh()
    
    # 測試簡單問答
    simple_success = test_simple_qa()
    
    print("\n" + "=" * 50)
    print("測試完成！")
    
    if qa_success and refresh_success and simple_success:
        print("✅ 所有測試通過")
    else:
        print("⚠️  部分測試失敗，請檢查錯誤信息")

if __name__ == "__main__":
    main() 