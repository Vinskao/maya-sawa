#!/usr/bin/env python3
"""
測試腳本：驗證 Maya 在多角色查詢中的身份回答

這個腳本測試 QAChain 是否能正確處理包含 Maya 的多角色查詢
"""

import sys
import os

# 添加項目根目錄到 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from maya_sawa.core.qa_chain import QAChain

def test_maya_identity_in_multi_character():
    """測試包含 Maya 的多角色查詢"""
    print("=== 測試包含 Maya 的多角色查詢 ===")
    
    # 創建 QAChain 實例
    qa_chain = QAChain()
    
    # 測試問題
    test_questions = [
        "你是誰? 誰是Sorane",
        "你叫什麼名字？Sorane是誰？",
        "誰是Maya？誰是Chiaki？",
        "你是誰？Yuki的身高是多少？",
        "Sorane的身高是多少？",
        "Yuki的生日是什麼時候？"
    ]
    
    for question in test_questions:
        print(f"\n問題: {question}")
        
        # 檢測角色名稱
        detected_names = qa_chain._detect_all_queried_names(question)
        print(f"檢測到的角色: {detected_names}")
        
        # 檢查是否包含 Maya
        has_maya = any(name.lower() == "maya" for name in detected_names)
        other_names = [name for name in detected_names if name.lower() != "maya"]
        
        print(f"包含 Maya: {has_maya}")
        print(f"其他角色: {other_names}")
        
        if has_maya:
            print("會使用特殊的多角色處理邏輯（Maya 以第一人稱回答）")
        else:
            print("會使用普通的多角色評論邏輯")

def test_single_maya_identity():
    """測試單獨的 Maya 身份詢問"""
    print("\n=== 測試單獨的 Maya 身份詢問 ===")
    
    qa_chain = QAChain()
    
    test_questions = [
        "你是誰",
        "你叫什麼名字",
        "誰是Maya",
        "誰是佐和真夜"
    ]
    
    for question in test_questions:
        print(f"\n問題: {question}")
        
        # 檢測角色名稱
        detected_names = qa_chain._detect_all_queried_names(question)
        print(f"檢測到的角色: {detected_names}")
        
        if len(detected_names) == 1 and detected_names[0].lower() == "maya":
            print("會使用純身份詢問邏輯（Maya 以第一人稱回答）")
        else:
            print("會使用其他邏輯")

if __name__ == "__main__":
    print("開始測試 Maya 身份回答修復...")
    
    try:
        test_single_maya_identity()
        test_maya_identity_in_multi_character()
        print("\n=== 測試完成 ===")
    except Exception as e:
        print(f"測試過程中發生錯誤: {str(e)}")
        import traceback
        traceback.print_exc() 