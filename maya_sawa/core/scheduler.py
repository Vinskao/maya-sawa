"""
Markdown Q&A System - 文章同步排程器模組

這個模組實現了自動化的文章同步功能，負責：
1. 定期從遠端 API 同步文章
2. 管理同步任務的生命週期
3. 處理同步錯誤和重試
4. 提供初始同步功能
5. 支持可配置的同步間隔

主要功能：
- 異步任務管理
- 定期同步排程
- 錯誤處理和重試
- 日誌記錄
- 資源清理

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import os

# 本地模組導入
from ..api.qa import sync_articles_from_api, SyncFromAPIRequest
from ..people import sync_data
from .config import Config

# ==================== 日誌配置 ====================
logger = logging.getLogger(__name__)

class ArticleSyncScheduler:
    """
    文章同步排程器
    
    負責管理文章同步任務，包括：
    - 定期同步任務的啟動和停止
    - 初始同步執行
    - 錯誤處理和重試機制
    - 任務狀態管理
    """
    
    def __init__(self):
        """
        初始化文章同步排程器
        
        設置同步任務的初始狀態
        """
        # 同步任務的異步任務對象
        self._sync_task: Optional[asyncio.Task] = None
        # 停止標誌
        self._stop_flag = False
        
    async def sync_articles_from_api(self, remote_url: Optional[str] = None) -> dict:
        """
        從遠端 API 同步文章並使用預計算的 embedding
        
        調用 API 模組中的同步功能，處理同步結果的格式轉換
        
        Args:
            remote_url (Optional[str]): 遠端 API URL，可選
            
        Returns:
            dict: 同步結果字典
            
        Raises:
            Exception: 當同步失敗時拋出異常
        """
        try:
            # 直接使用 qa.py 中的現有邏輯
            request = SyncFromAPIRequest(remote_url=remote_url)
            result = await sync_articles_from_api(request)
            
            # 轉換 FastAPI 響應格式為字典
            if hasattr(result, 'body'):
                # 如果是 FastAPI Response 對象，需要解析 body
                import json
                return json.loads(result.body.decode())
            else:
                # 如果已經是字典，直接返回
                return result
                
        except Exception as e:
            logger.error(f"同步文章時發生錯誤: {str(e)}")
            raise Exception(f"同步失敗: {str(e)}")
    
    def sync_people_weapons_data(self) -> dict:
        """
        同步人員和武器數據
        
        調用人員和武器數據同步功能
        
        Returns:
            dict: 同步結果字典
            
        Raises:
            Exception: 當同步失敗時拋出異常
        """
        try:
            logger.info("開始同步人員和武器數據...")
            result = sync_data()
            logger.info(f"人員和武器數據同步完成: 人員 {result['people_updated']} 條, 武器 {result['weapons_updated']} 條")
            return result
        except Exception as e:
            logger.error(f"同步人員和武器數據時發生錯誤: {str(e)}")
            raise Exception(f"人員武器同步失敗: {str(e)}")
    
    async def start_periodic_sync(self, interval_days: int = 3, hour: int = 3, minute: int = 0):
        """
        啟動定期同步任務
        
        創建一個異步任務來執行定期同步，支持：
        - 可配置的同步間隔
        - 指定同步時間
        - 任務狀態檢查
        
        Args:
            interval_days (int): 同步間隔天數，默認 3 天
            hour (int): 同步時間（小時），默認凌晨 3 點
            minute (int): 同步時間（分鐘），默認 0 分
        """
        # 檢查是否已有同步任務在運行
        if self._sync_task and not self._sync_task.done():
            logger.warning("定期同步任務已經在運行中")
            return
        
        # 創建新的異步同步任務
        self._sync_task = asyncio.create_task(self._periodic_sync_loop(interval_days, hour, minute))
        logger.info(f"定期同步任務已啟動，每 {interval_days} 天在 {hour:02d}:{minute:02d} 執行")
    
    async def stop_periodic_sync(self):
        """
        停止定期同步任務
        
        安全地停止正在運行的同步任務，包括：
        - 任務取消
        - 異常處理
        - 狀態清理
        """
        # 設置停止標誌
        self._stop_flag = True
        
        if self._sync_task and not self._sync_task.done():
            # 取消同步任務
            self._sync_task.cancel()
            try:
                # 等待任務完成取消
                await self._sync_task
            except asyncio.CancelledError:
                # 忽略取消異常
                pass
            logger.info("定期同步任務已停止")
    
    async def _periodic_sync_loop(self, interval_days: int, hour: int, minute: int):
        """
        定期同步循環（內部方法）
        
        執行定期同步的核心邏輯，包括：
        - 計算下次執行時間
        - 等待到指定時間
        - 執行同步操作
        - 錯誤處理和重試
        
        Args:
            interval_days (int): 同步間隔天數
            hour (int): 同步時間（小時）
            minute (int): 同步時間（分鐘）
        """
        while not self._stop_flag:
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
                
                # 分段等待，每分鐘檢查一次停止標誌
                for _ in range(int(wait_seconds // 60)):
                    if self._stop_flag:
                        logger.info("定期同步任務收到停止信號")
                        return
                    await asyncio.sleep(60)
                
                # 等待剩餘時間
                remaining_seconds = wait_seconds % 60
                if remaining_seconds > 0:
                    await asyncio.sleep(remaining_seconds)
                
                # 檢查停止標誌
                if self._stop_flag:
                    logger.info("定期同步任務收到停止信號")
                    return
                
                # 執行文章同步操作（如果啟用）
                if Config.ENABLE_PERIODIC_SYNC:
                    logger.info("開始執行定期文章同步...")
                    try:
                        articles_result = await self.sync_articles_from_api()
                        logger.info(f"定期文章同步完成: {articles_result.get('message', '同步完成')}")
                    except Exception as e:
                        logger.error(f"定期文章同步失敗: {str(e)}")
                
                # 執行人員和武器數據同步操作（如果啟用）
                if Config.ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC:
                    logger.info("開始執行定期人員和武器數據同步...")
                    try:
                        people_weapons_result = self.sync_people_weapons_data()
                        logger.info(f"定期人員武器同步完成: 人員 {people_weapons_result['people_updated']} 條, 武器 {people_weapons_result['weapons_updated']} 條")
                    except Exception as e:
                        logger.error(f"定期人員武器同步失敗: {str(e)}")
                
                # 等待指定的天數間隔（分段等待）
                for _ in range(interval_days * 24 * 60):  # 每分鐘檢查一次
                    if self._stop_flag:
                        logger.info("定期同步任務收到停止信號")
                        return
                    await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                # 處理任務取消
                logger.info("定期同步任務被取消")
                break
            except Exception as e:
                # 處理同步錯誤
                logger.error(f"定期同步任務發生錯誤: {str(e)}")
                # 發生錯誤時等待 1 小時後重試
                await asyncio.sleep(3600)
    
    async def run_initial_sync(self):
        """
        程式啟動時執行初始同步
        
        在應用程式啟動時執行一次同步，確保系統有最新的文章數據
        
        Returns:
            dict: 初始同步結果
            
        Raises:
            Exception: 當初始同步失敗時拋出異常
        """
        try:
            logger.info("程式啟動，執行初始文章同步...")
            result = await self.sync_articles_from_api()
            logger.info(f"初始文章同步完成: {result.get('message', '同步完成')}")
            return result
        except Exception as e:
            logger.error(f"初始文章同步失敗: {str(e)}")
            raise 