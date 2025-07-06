#!/usr/bin/env python3
"""
測試多角色查詢是否包含所有四種圖片連結
"""

import asyncio
import httpx
import json

async def test_multi_character_images():
    """測試多角色查詢是否包含所有四種圖片連結"""
    
    # 測試查詢
    test_query = "Chiaki,Sorane的身高和體重是多少"
    
    # 準備請求數據
    request_data = {
        "text": test_query,
        "user_id": "test_user",
        "language": "chinese"
    }
    
    print(f"測試查詢: {test_query}")
    print("=" * 50)
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "http://localhost:8000/qa/query",
                json=request_data,
                headers={"Content-Type": "application/json"}
            )
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("success"):
                    answer = result.get("answer", "")
                    print("✅ 查詢成功")
                    print(f"回答長度: {len(answer)} 字符")
                    print("\n回答內容:")
                    print("-" * 30)
                    print(answer)
                    print("-" * 30)
                    
                    # 檢查是否包含所有四種圖片連結
                    chiaki_images = [
                        "https://peoplesystem.tatdvsonorth.com/images/people/Chiaki.png",
                        "https://peoplesystem.tatdvsonorth.com/images/people/ChiakiFighting.png",
                        "https://peoplesystem.tatdvsonorth.com/images/people/ChiakiRuined.png",
                        "https://peoplesystem.tatdvsonorth.com/images/people/RavishingChiaki.png"
                    ]
                    
                    sorane_images = [
                        "https://peoplesystem.tatdvsonorth.com/images/people/Sorane.png",
                        "https://peoplesystem.tatdvsonorth.com/images/people/SoraneFighting.png",
                        "https://peoplesystem.tatdvsonorth.com/images/people/SoraneRuined.png",
                        "https://peoplesystem.tatdvsonorth.com/images/people/RavishingSorane.png"
                    ]
                    
                    # 檢查 Chiaki 的圖片
                    print("\n檢查 Chiaki 的圖片連結:")
                    for i, img_url in enumerate(chiaki_images):
                        if img_url in answer:
                            print(f"✅ Chiaki 圖片 {i+1}: {img_url}")
                        else:
                            print(f"❌ Chiaki 圖片 {i+1} 缺失: {img_url}")
                    
                    # 檢查 Sorane 的圖片
                    print("\n檢查 Sorane 的圖片連結:")
                    for i, img_url in enumerate(sorane_images):
                        if img_url in answer:
                            print(f"✅ Sorane 圖片 {i+1}: {img_url}")
                        else:
                            print(f"❌ Sorane 圖片 {i+1} 缺失: {img_url}")
                    
                    # 統計結果
                    total_images = len(chiaki_images) + len(sorane_images)
                    found_images = sum(1 for img in chiaki_images + sorane_images if img in answer)
                    
                    print(f"\n📊 統計結果:")
                    print(f"總圖片數: {total_images}")
                    print(f"找到圖片數: {found_images}")
                    print(f"缺失圖片數: {total_images - found_images}")
                    
                    if found_images == total_images:
                        print("🎉 所有圖片連結都已包含！")
                    else:
                        print("⚠️  仍有圖片連結缺失")
                        
                else:
                    print("❌ 查詢失敗")
                    print(f"錯誤信息: {result.get('error', 'Unknown error')}")
            else:
                print(f"❌ HTTP 錯誤: {response.status_code}")
                print(f"響應內容: {response.text}")
                
    except Exception as e:
        print(f"❌ 請求失敗: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_multi_character_images()) 