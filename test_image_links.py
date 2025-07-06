#!/usr/bin/env python3
"""
測試圖片連結功能
"""

import asyncio
import httpx
import json

async def test_image_links():
    """測試圖片連結功能"""
    
    # 測試問題列表
    test_questions = [
        "Wavo是誰？",  # 單一角色
        "請介紹 Wavo 和 Maya",  # 多角色（包含 Maya）
        "Wavo 和 Alice 誰比較高？",  # 多角色（不包含 Maya）
        "Wavo的身高是多少？",  # 具體數據問題
    ]
    
    print("=== 測試圖片連結功能 ===\n")
    
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
                        if "https://peoplesystem.tatdvsonorth.com/images/people/" in answer:
                            print("✅ 回答包含圖片連結")
                            
                            # 檢查是否包含 Wavo 的圖片連結
                            if "Wavo.png" in answer:
                                print("✅ 包含 Wavo 的圖片連結")
                            else:
                                print("⚠️  沒有找到 Wavo 的圖片連結")
                        else:
                            print("❌ 回答沒有包含圖片連結")
                    else:
                        print(f"❌ API 返回錯誤: {result.get('message', '未知錯誤')}")
                else:
                    print(f"❌ HTTP 錯誤: {response.status_code}")
                    
        except Exception as e:
            print(f"❌ 請求失敗: {str(e)}")
        
        print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(test_image_links()) 