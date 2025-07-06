#!/usr/bin/env python3
"""
測試不存在的角色處理是否正確
"""

import asyncio
import httpx
import json

async def test_not_found_fix():
    """測試不存在的角色處理"""
    
    # 測試問題列表
    test_questions = [
        "Tsubasa的身高和體重是多少",  # 不存在的角色
        "Chiaki的戰鬥力如何",        # 不存在的角色
        "Yuki的個性是什麼",          # 不存在的角色
        "Sorane的身材怎麼樣",        # 不存在的角色
        "haha的身高是多少",          # 不存在的角色
        "mama的體重是多少",          # 不存在的角色
    ]
    
    print("=== 測試不存在的角色處理 ===\n")
    
    for i, question in enumerate(test_questions, 1):
        print(f"測試 {i}: {question}")
        print("-" * 50)
        
        try:
            # 發送請求到 API
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "http://localhost:8000/qa/query",
                    json={
                        "text": question,
                        "user_id": "test_user",
                        "language": "chinese"
                    },
                    timeout=30.0
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        answer = result.get("answer", "")
                        print(f"回答: {answer}")
                        
                        # 檢查是否正確處理了不存在的角色
                        if any(name in question for name in ["Tsubasa", "Chiaki", "Yuki", "Sorane", "haha", "mama"]):
                            if ("沒聽過" in answer or "找不到" in answer or "抱歉" in answer or 
                                "問錯人了" in answer or "無法找到" in answer):
                                print("✅ 正確處理了不存在的角色")
                            else:
                                print("❌ 沒有正確處理不存在的角色")
                        else:
                            print("✅ 問題中沒有不存在的角色")
                    else:
                        print(f"❌ API 返回錯誤: {result.get('message', '未知錯誤')}")
                else:
                    print(f"❌ HTTP 錯誤: {response.status_code}")
                    
        except Exception as e:
            print(f"❌ 請求失敗: {str(e)}")
        
        print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(test_not_found_fix()) 