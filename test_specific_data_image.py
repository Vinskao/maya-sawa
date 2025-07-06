#!/usr/bin/env python3
"""
測試具體數據問題是否包含圖片連結
"""

import asyncio
import httpx
import json

async def test_specific_data_image():
    """測試具體數據問題的圖片連結"""
    
    # 測試問題列表
    test_questions = [
        "Chiaki的身高和體重是多少",  # 具體數據問題
        "Chiaki的身高是多少",       # 具體數據問題
        "Chiaki的體重是多少",       # 具體數據問題
        "Chiaki是誰",               # 一般介紹問題（對比用）
    ]
    
    print("=== 測試具體數據問題的圖片連結 ===\n")
    
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
                        
                        # 檢查是否包含圖片連結
                        if "https://peoplesystem.tatdvsonorth.com/images/people/Chiaki.png" in answer:
                            print("✅ 包含 Chiaki 的圖片連結")
                        else:
                            print("❌ 沒有包含 Chiaki 的圖片連結")
                    else:
                        print(f"❌ API 返回錯誤: {result.get('message', '未知錯誤')}")
                else:
                    print(f"❌ HTTP 錯誤: {response.status_code}")
                    
        except Exception as e:
            print(f"❌ 請求失敗: {str(e)}")
        
        print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(test_specific_data_image()) 