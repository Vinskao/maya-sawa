from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.qa import router as qa_router
from .core.scheduler import ArticleSyncScheduler
import os
from dotenv import load_dotenv
import logging
import asyncio

# 設置日誌
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv(override=True)  # 強制覆蓋已存在的環境變數
api_key = os.getenv("OPENAI_API_KEY")
api_base = os.getenv("OPENAI_API_BASE")
logger.debug(f"API Key loaded: {api_key[:8]}...{api_key[-4:] if api_key else 'None'}")
logger.debug(f"API Base URL: {api_base}")

# 檢查環境變數是否正確載入
if not api_key:
    logger.error("OPENAI_API_KEY not found in environment variables!")
if not api_base:
    logger.error("OPENAI_API_BASE not found in environment variables!")

app = FastAPI(
    title="Markdown Q&A System",
    description="A powerful document Q&A system based on FastAPI, LangChain, and ChromaDB",
    version="0.1.0",
    root_path="/maya-sawa"
)

# 設置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(qa_router)

# 創建排程器實例
scheduler = ArticleSyncScheduler()

@app.on_event("startup")
async def startup_event():
    """應用程式啟動時執行的事件"""
    try:
        # 執行初始同步
        logger.info("應用程式啟動，開始執行初始同步...")
        await scheduler.run_initial_sync()
        
        # 啟動定期同步任務（每3天凌晨3點執行）
        await scheduler.start_periodic_sync(interval_days=3, hour=3, minute=0)
        
        logger.info("應用程式啟動完成，排程任務已啟動")
    except Exception as e:
        logger.error(f"啟動時發生錯誤: {str(e)}")
        # 不讓啟動錯誤阻止應用程式運行

@app.on_event("shutdown")
async def shutdown_event():
    """應用程式關閉時執行的事件"""
    try:
        # 停止定期同步任務
        await scheduler.stop_periodic_sync()
        logger.info("應用程式關閉，排程任務已停止")
    except Exception as e:
        logger.error(f"關閉時發生錯誤: {str(e)}")

@app.get("/")
async def root():
    """根路由，返回 API 信息"""
    return {
        "message": "Welcome to Markdown Q&A System",
        "version": "0.1.0",
        "docs_url": "/docs"
    } 