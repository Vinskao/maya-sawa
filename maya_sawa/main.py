from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.qa import router as qa_router
import os
from dotenv import load_dotenv
import logging

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

@app.get("/")
async def root():
    """根路由，返回 API 信息"""
    return {
        "message": "Welcome to Markdown Q&A System",
        "version": "0.1.0",
        "docs_url": "/docs"
    } 