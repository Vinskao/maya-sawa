import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import os
from ..api.qa import sync_articles_from_api, SyncFromAPIRequest

logger = logging.getLogger(__name__)

class ArticleSyncScheduler:
    def __init__(self):
        self._sync_task: Optional[asyncio.Task] = None
        
    async def sync_articles_from_api(self, remote_url: Optional[str] = None) -> dict:
        """從遠端 API 同步文章並使用預計算的 embedding"""
        try:
            # 直接使用 qa.py 中的現有邏輯
            request = SyncFromAPIRequest(remote_url=remote_url)
            result = await sync_articles_from_api(request)
            
            # 轉換 FastAPI 響應格式為字典
            if hasattr(result, 'body'):
                # 如果是 FastAPI Response 對象
                import json
                return json.loads(result.body.decode())
            else:
                # 如果已經是字典
                return result
                
        except Exception as e:
            logger.error(f"同步文章時發生錯誤: {str(e)}")
            raise Exception(f"同步失敗: {str(e)}")
    
    async def start_periodic_sync(self, interval_days: int = 3, hour: int = 3, minute: int = 0):
        """啟動定期同步任務"""
        if self._sync_task and not self._sync_task.done():
            logger.warning("定期同步任務已經在運行中")
            return
        
        self._sync_task = asyncio.create_task(self._periodic_sync_loop(interval_days, hour, minute))
        logger.info(f"定期同步任務已啟動，每 {interval_days} 天在 {hour:02d}:{minute:02d} 執行")
    
    async def stop_periodic_sync(self):
        """停止定期同步任務"""
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            logger.info("定期同步任務已停止")
    
    async def _periodic_sync_loop(self, interval_days: int, hour: int, minute: int):
        """定期同步循環"""
        while True:
            try:
                # 計算下次執行時間
                now = datetime.now()
                next_run = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                # 如果今天的時間已經過了，就設定為明天
                if next_run <= now:
                    next_run += timedelta(days=1)
                
                # 等待到下次執行時間
                wait_seconds = (next_run - now).total_seconds()
                logger.info(f"下次同步時間: {next_run.strftime('%Y-%m-%d %H:%M:%S')} (等待 {wait_seconds:.0f} 秒)")
                
                await asyncio.sleep(wait_seconds)
                
                # 執行同步
                logger.info("開始執行定期同步...")
                result = await self.sync_articles_from_api()
                logger.info(f"定期同步完成: {result.get('message', '同步完成')}")
                
                # 等待指定的天數間隔
                await asyncio.sleep(interval_days * 24 * 3600)
                
            except asyncio.CancelledError:
                logger.info("定期同步任務被取消")
                break
            except Exception as e:
                logger.error(f"定期同步任務發生錯誤: {str(e)}")
                # 發生錯誤時等待 1 小時後重試
                await asyncio.sleep(3600)
    
    async def run_initial_sync(self):
        """程式啟動時執行初始同步"""
        try:
            logger.info("程式啟動，執行初始同步...")
            result = await self.sync_articles_from_api()
            logger.info(f"初始同步完成: {result.get('message', '同步完成')}")
            return result
        except Exception as e:
            logger.error(f"初始同步失敗: {str(e)}")
            raise 