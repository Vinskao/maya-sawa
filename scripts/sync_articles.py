#!/usr/bin/env python3
"""
Maya Sawa 文章同步腳本
用於手動執行或測試文章同步功能
"""

import asyncio
import sys
import os
import logging
from pathlib import Path

# 添加專案根目錄到 Python 路徑
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from maya_sawa.api.qa import sync_articles_from_api, SyncFromAPIRequest

# 設置日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """主函數"""
    try:
        logger.info("開始執行文章同步...")
        
        # 直接使用 qa.py 中的現有邏輯
        request = SyncFromAPIRequest()
        result = await sync_articles_from_api(request)
        
        logger.info(f"同步完成: {result.get('message', '同步完成')}")
        logger.info(f"同步文章數量: {result.get('count', 0)}")
        
        articles = result.get('articles', [])
        if articles:
            logger.info("同步的文章:")
            for article in articles:
                logger.info(f"  - {article['file_path']} (ID: {article['id']})")
        
        return 0
        
    except Exception as e:
        logger.error(f"同步失敗: {str(e)}")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code) 