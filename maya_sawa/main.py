from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import qa

app = FastAPI(
    title="Maya Sawa",
    description="Markdown Q&A System with FastAPI, LangChain, and GPT API",
    version="0.1.0"
)

# CORS 設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 在生產環境中應該設定具體的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 註冊路由
app.include_router(qa.router)

@app.get("/")
async def root():
    return {
        "message": "Welcome to Maya Sawa API",
        "docs_url": "/docs",
        "endpoints": {
            "upload": "/qa/upload",
            "query": "/qa/query"
        }
    } 