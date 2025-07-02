#!/usr/bin/env python3
"""
Maya Sawa 文章同步腳本

這個腳本用於手動執行或測試文章同步功能，可以：
1. 從遠端 API 同步文章到本地向量數據庫
2. 使用預計算的 embedding 提高同步效率
3. 提供詳細的同步日誌和統計信息
4. 支持命令行執行和錯誤處理

使用方式：
    python scripts/sync_articles.py

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import asyncio
import sys
import os
import logging
from pathlib import Path

# 添加專案根目錄到 Python 路徑
# 這樣可以正確導入 maya_sawa 模組
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 本地模組導入
from maya_sawa.api.qa import sync_articles_from_api, SyncFromAPIRequest

# ==================== 日誌配置 ====================
# 設置日誌格式和級別，用於記錄同步過程
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """
    主函數
    
    執行文章同步的主要邏輯，包括：
    - 調用同步 API
    - 處理同步結果
    - 記錄詳細日誌
    - 錯誤處理
    
    Returns:
        int: 退出碼，0 表示成功，1 表示失敗
    """
    try:
        logger.info("開始執行文章同步...")
        
        # 創建同步請求對象（使用默認配置）
        request = SyncFromAPIRequest()
        
        # 調用同步 API，使用預計算的 embedding
        result = await sync_articles_from_api(request)
        
        # 記錄同步結果
        logger.info(f"同步完成: {result.get('message', '同步完成')}")
        logger.info(f"同步文章數量: {result.get('count', 0)}")
        
        # 顯示同步的文章詳情
        articles = result.get('articles', [])
        if articles:
            logger.info("同步的文章:")
            for article in articles:
                logger.info(f"  - {article['file_path']} (ID: {article['id']})")
        
        return 0  # 成功退出
        
    except Exception as e:
        # 記錄錯誤並返回失敗退出碼
        logger.error(f"同步失敗: {str(e)}")
        return 1

if __name__ == "__main__":
    # 運行主函數並設置退出碼
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 