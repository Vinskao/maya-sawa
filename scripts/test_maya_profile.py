#!/usr/bin/env python3
"""
測試 Maya 個人資料動態獲取功能

這個腳本用於測試：
1. 從 API 獲取 Maya 的個人資料
2. 刷新個人資料緩存
3. 驗證個人資料格式

作者: Maya Sawa Team
版本: 0.1.0
"""

import sys
import os
import asyncio
import httpx
import json
from typing import Dict, Any

# 添加項目根目錄到 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from maya_sawa.core.qa_chain import QAChain

async def test_maya_profile_api():
    """
    測試從 API 獲取 Maya 個人資料
    """
    print("=== 測試 Maya 個人資料 API ===")
    
    url = "https://peoplesystem.tatdvsonorth.com/tymb/people/get-by-name"
    payload = {"name": "Maya"}
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            print(f"正在向 {url} 發送 POST 請求...")
            response = await client.post(url, json=payload)
            response.raise_for_status()
            
            data = response.json()
            print(f"✅ API 請求成功！")
            print(f"狀態碼: {response.status_code}")
            print(f"響應數據: {json.dumps(data, indent=2, ensure_ascii=False)}")
            
            # 檢查關鍵欄位
            required_fields = ["name", "nameOriginal", "codeName", "physicPower", "magicPower", "utilityPower"]
            missing_fields = [field for field in required_fields if field not in data]
            
            if missing_fields:
                print(f"⚠️  缺少關鍵欄位: {missing_fields}")
            else:
                print(f"✅ 所有關鍵欄位都存在")
            
            # 檢查 embedding 欄位
            if "embedding" in data:
                embedding = data["embedding"]
                if isinstance(embedding, list):
                    print(f"✅ Embedding 存在，長度: {len(embedding)}")
                else:
                    print(f"⚠️  Embedding 格式不正確: {type(embedding)}")
            else:
                print(f"⚠️  缺少 embedding 欄位")
            
            return data
            
    except httpx.RequestError as e:
        print(f"❌ 網路請求錯誤: {str(e)}")
        return None
    except Exception as e:
        print(f"❌ 其他錯誤: {str(e)}")
        return None

def test_qa_chain_profile():
    """
    測試 QA Chain 的個人資料功能
    """
    print("\n=== 測試 QA Chain 個人資料功能 ===")
    
    try:
        # 創建 QA Chain 實例
        qa_chain = QAChain()
        print("✅ QA Chain 實例創建成功")
        
        # 獲取個人資料摘要
        print("正在獲取個人資料摘要...")
        profile_summary = qa_chain._get_profile_summary()
        print(f"✅ 個人資料摘要獲取成功")
        print(f"摘要長度: {len(profile_summary)} 字符")
        print(f"摘要內容:\n{profile_summary}")
        
        # 檢查緩存狀態
        print(f"緩存狀態: {'已緩存' if qa_chain._profile_cache else '未緩存'}")
        
        # 測試刷新功能
        print("\n正在測試刷新功能...")
        qa_chain.refresh_profile()
        print("✅ 個人資料刷新成功")
        
        # 再次獲取摘要
        new_summary = qa_chain._get_profile_summary()
        print(f"刷新後摘要長度: {len(new_summary)} 字符")
        
        return True
        
    except Exception as e:
        print(f"❌ QA Chain 測試失敗: {str(e)}")
        return False

async def test_api_endpoints():
    """
    測試 API 端點（已移除 Maya 個人資料端點，因為是內部服務）
    """
    print("\n=== 測試 API 端點 ===")
    print("Maya 個人資料端點已移除（內部服務）")
    print("✅ 不需要外部 API 端點，個人資料在 QA Chain 內部管理")

def main():
    """
    主函數
    """
    print("Maya 個人資料動態獲取功能測試")
    print("=" * 50)
    
    # 測試 API 獲取
    api_data = asyncio.run(test_maya_profile_api())
    
    # 測試 QA Chain 功能
    qa_success = test_qa_chain_profile()
    
    # 測試 API 端點
    asyncio.run(test_api_endpoints())
    
    print("\n" + "=" * 50)
    print("測試完成！")
    
    if api_data and qa_success:
        print("✅ 所有測試通過")
    else:
        print("⚠️  部分測試失敗，請檢查錯誤信息")

if __name__ == "__main__":
    main() 