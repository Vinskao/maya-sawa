#!/usr/bin/env python3
"""
測試身份切換修復
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from maya_sawa.core.qa_chain import QAChain
from maya_sawa.core.langchain_shim import Document

def test_identity_switch():
    """測試身份切換功能"""
    print("=== 測試身份切換功能 ===")
    
    # 創建 QAChain 實例
    qa_chain = QAChain()
    
    # 測試問題
    test_query = "請分享關於應用程序部署、容器化和 DevOps 實踐的經驗。"
    test_documents = [
        Document(
            page_content="這是一個測試文檔，包含關於 DevOps 的信息。",
            metadata={"source": "test.md"}
        )
    ]
    
    print(f"初始身份: {qa_chain.self_name}")
    print(f"初始提示模板: {qa_chain.prompt_template.template[:100]}...")
    
    # 測試 Maya 身份
    print("\n--- 測試 Maya 身份 ---")
    result_maya = qa_chain.get_answer(test_query, test_documents, self_name="Maya")
    print(f"Maya 身份: {qa_chain.self_name}")
    print(f"Maya 回答長度: {len(result_maya['answer'])}")
    print(f"Maya 回答前100字: {result_maya['answer'][:100]}...")
    
    # 測試 Etsuko 身份
    print("\n--- 測試 Etsuko 身份 ---")
    result_etsuko = qa_chain.get_answer(test_query, test_documents, self_name="Etsuko")
    print(f"Etsuko 身份: {qa_chain.self_name}")
    print(f"Etsuko 回答長度: {len(result_etsuko['answer'])}")
    print(f"Etsuko 回答前100字: {result_etsuko['answer'][:100]}...")
    
    # 檢查提示模板是否更新
    print(f"\n更新後的提示模板: {qa_chain.prompt_template.template[:100]}...")
    
    # 驗證身份是否正確切換
    if "Etsuko" in qa_chain.prompt_template.template:
        print("✅ 身份切換成功！提示模板已更新為 Etsuko")
    else:
        print("❌ 身份切換失敗！提示模板仍包含 Maya")
    
    return result_maya, result_etsuko

if __name__ == "__main__":
    test_identity_switch() 