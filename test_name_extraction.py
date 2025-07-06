#!/usr/bin/env python3
"""
測試腳本：驗證人名提取的修復

這個腳本測試 QAChain 是否能正確提取人名，不會發明或猜測
"""

import sys
import os

# 添加項目根目錄到 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maya_sawa.core.qa_chain import QAChain

def test_name_extraction():
    """測試人名提取功能"""
    print("=== 測試人名提取功能 ===")
    
    # 創建 QAChain 實例
    qa_chain = QAChain()
    
    # 測試問題
    test_questions = [
        "你是誰? 誰是Sorane",
        "你叫什麼名字？Sorane是誰？",
        "誰是Maya？誰是Chiaki？",
        "你是誰？Yuki的身高是多少？",
        "Sorane的身高是多少？",
        "Yuki的生日是什麼時候？",
        "你是誰？",
        "沒有提到任何人名",
        "Chiaki喜歡什麼？"
    ]
    
    for question in test_questions:
        print(f"\n問題: {question}")
        
        # 檢測角色名稱
        detected_names = qa_chain._detect_all_queried_names(question)
        print(f"最終檢測到的角色: {detected_names}")
        
        # 檢查是否包含 Maya
        has_maya = any(name.lower() == "maya" for name in detected_names)
        other_names = [name for name in detected_names if name.lower() != "maya"]
        
        print(f"包含 Maya: {has_maya}")
        print(f"其他角色: {other_names}")

if __name__ == "__main__":
    print("開始測試人名提取修復...")
    
    try:
        test_name_extraction()
        print("\n=== 測試完成 ===")
    except Exception as e:
        print(f"測試過程中發生錯誤: {str(e)}")
        import traceback
        traceback.print_exc() 