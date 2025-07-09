"""
Markdown Q&A System - 主應用程式入口點

這個模組是整個 Markdown Q&A 系統的主要入口點，負責：
1. 初始化 FastAPI 應用程式
2. 配置 CORS 中間件
3. 註冊 API 路由
4. 管理應用程式的啟動和關閉事件
5. 啟動文章同步排程器

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導入
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
import asyncio
import pathlib

# 第三方庫導入
from dotenv import load_dotenv

# 本地模組導入
from .api.qa import router as qa_router
from .core.scheduler import ArticleSyncScheduler
from .core.people import sync_data
from .core.config import Config

# ==================== 日誌配置 ====================
# 設置日誌級別為 DEBUG，用於開發環境的詳細調試信息
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ==================== 環境變數配置 ====================
# 載入環境變數，override=True 表示強制覆蓋已存在的環境變數
env_path = pathlib.Path(__file__).parent.parent / '.env'
logger.debug(f"Loading .env file from: {env_path}")
load_dotenv(env_path, override=True)

# 從環境變數獲取 OpenAI API 配置
api_key = os.getenv("OPENAI_API_KEY")
api_base = os.getenv("OPENAI_API_BASE")

# 記錄 API 配置信息（隱藏敏感信息）
logger.debug(f"API Key loaded: {api_key[:8]}...{api_key[-4:] if api_key else 'None'}")
logger.debug(f"API Base URL: {api_base}")
logger.debug(f"PUBLIC_API_BASE_URL: {Config.PUBLIC_API_BASE_URL}")

# 檢查關鍵環境變數是否正確載入
if not api_key:
    logger.error("OPENAI_API_KEY not found in environment variables!")
if not api_base:
    logger.error("OPENAI_API_BASE not found in environment variables!")

# ==================== FastAPI 應用程式初始化 ====================
# 創建 FastAPI 應用程式實例
app = FastAPI(
    title="Markdown Q&A System",  # API 文檔標題
    description="A powerful document Q&A system based on FastAPI, LangChain, and ChromaDB",  # API 描述
    version="0.1.0",  # API 版本
    root_path="/maya-sawa"  # 添加根路徑支持，用於 Kubernetes Ingress 路徑前綴
)

# ==================== CORS 中間件配置 ====================
# 添加 CORS 中間件，允許跨域請求
# 在生產環境中應該限制 allow_origins 為特定的域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允許所有來源（開發環境）
    allow_credentials=True,  # 允許攜帶認證信息
    allow_methods=["*"],  # 允許所有 HTTP 方法
    allow_headers=["*"],  # 允許所有請求頭
)

# ==================== 路由註冊 ====================
# 註冊問答相關的 API 路由
app.include_router(qa_router)

# ==================== 排程器初始化 ====================
# 創建文章同步排程器實例
scheduler = ArticleSyncScheduler()

# ==================== 應用程式生命週期事件 ====================

@app.on_event("startup")
async def startup_event():
    """
    應用程式啟動時執行的事件處理器
    
    這個函數在 FastAPI 應用程式啟動時自動執行，負責：
    1. 執行初始文章同步
    2. 執行人員和武器數據同步
    3. 啟動定期同步任務
    4. 記錄啟動日誌
    """
    try:
        # 檢查配置
        missing_config = Config.validate_required_config()
        if missing_config:
            logger.warning(f"缺少必要的配置變數: {', '.join(missing_config)}")
        
        # 記錄同步配置
        sync_config = Config.get_sync_config_summary()
        logger.info(f"同步配置: {sync_config}")
        
        # 執行初始文章同步（如果啟用）
        if Config.ENABLE_AUTO_SYNC_ON_STARTUP:
            logger.info("應用程式啟動，開始執行初始文章同步...")
            try:
                await scheduler.run_initial_sync()
            except Exception as e:
                logger.error(f"初始文章同步失敗: {str(e)}")
                # 不讓文章同步失敗阻止應用程式啟動
        else:
            logger.info("跳過初始文章同步（已禁用）")
        
        # 執行人員和武器數據同步（如果啟用）- 改為背景任務
        if Config.ENABLE_PEOPLE_WEAPONS_SYNC:
            logger.info("開始執行人員和武器數據同步（背景任務）...")
            
            async def sync_people_weapons_background():
                """背景任務：同步人員和武器數據"""
                try:
                    people_weapons_result = sync_data()
                    logger.info(f"人員和武器數據同步完成: 人員 {people_weapons_result['people_updated']} 條, 武器 {people_weapons_result['weapons_updated']} 條")
                except Exception as e:
                    logger.error(f"人員和武器數據同步失敗: {str(e)}")
            
            # 創建背景任務，不阻塞主線程
            asyncio.create_task(sync_people_weapons_background())
        else:
            logger.info("跳過人員和武器數據同步（已禁用）")
        
        # 啟動定期同步任務（如果啟用）
        if Config.ENABLE_PERIODIC_SYNC:
            await scheduler.start_periodic_sync(
                interval_days=Config.SYNC_INTERVAL_DAYS, 
                hour=Config.SYNC_HOUR, 
                minute=Config.SYNC_MINUTE
            )
            logger.info("定期同步任務已啟動")
        else:
            logger.info("跳過定期同步任務（已禁用）")
        
        logger.info("應用程式啟動完成")
    except Exception as e:
        # 記錄啟動錯誤，但不讓啟動錯誤阻止應用程式運行
        logger.error(f"啟動時發生錯誤: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    """
    應用程式關閉時執行的事件處理器
    
    這個函數在 FastAPI 應用程式關閉時自動執行，負責：
    1. 停止定期同步任務
    2. 清理資源
    3. 記錄關閉日誌
    """
    try:
        # 停止定期同步任務，避免資源洩漏
        await scheduler.stop_periodic_sync()
        logger.info("應用程式關閉，排程任務已停止")
    except Exception as e:
        # 記錄關閉錯誤
        logger.error(f"關閉時發生錯誤: {str(e)}")

# ==================== 根路由 ====================

@app.get("/")
async def root():
    """
    根路由處理器
    
    返回 API 的基本信息，包括：
    - 歡迎消息
    - API 版本
    - API 文檔 URL
    
    Returns:
        dict: 包含 API 基本信息的字典
    """
    return {
        "message": "Welcome to Markdown Q&A System",
        "version": "0.1.0",
        "docs_url": "/docs"  # FastAPI 自動生成的 API 文檔地址
    } 