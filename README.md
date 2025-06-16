# Markdown 問答系統



這是一個基於 FastAPI、LangChain 和 ChromaDB 建構的強大文件問答系統。你可以對你的 Markdown 文件提問，系統會根據文件內容提供 AI 驅動的答案。


## 專案結構

```
maya_sawa/
├── maya_sawa/          # 主要程式碼目錄
│   ├── __init__.py
│   ├── main.py         # FastAPI 應用程式入口點
│   ├── api/            # API 路由模組
│   │   ├── __init__.py
│   │   └── qa.py       # 問答相關的 API 路由
│   └── core/           # 核心功能模組
│       ├── __init__.py
│       ├── loader.py   # 文件載入和分塊
│       ├── embed.py    # 向量存儲和檢索
│       └── qa_chain.py # 問答鏈實作
├── data/               # 資料目錄
│   ├── uploads/        # 上傳的文件存放處
│   └── chroma/         # ChromaDB 向量存儲（自動生成）
│       └── chroma.sqlite3  # ChromaDB 的資料庫文件
├── pyproject.toml      # Poetry 專案配置
└── README.md          # 本文件
```

## 功能特點

- 文件載入與處理
- 文本分塊（支援重疊）
- 使用 ChromaDB 進行向量存儲
- 整合 OpenAI 的嵌入模型和聊天模型
- FastAPI REST API 介面

## 環境需求

- Python 3.12 或更高版本
- Poetry（Python 套件管理器）
- OpenAI API 金鑰

## 安裝步驟

1. 複製專案：
```bash
git clone https://github.com/yourusername/maya-sawa.git
cd maya-sawa
```

2. 使用 Poetry 安裝依賴：
```bash
poetry install
```

3. 建立 `.env` 檔案：
```bash
cp .env.example .env
```

4. 編輯 `.env` 並加入你的 OpenAI API 金鑰：
```
OPENAI_API_KEY=sk-your-api-key-here
```

## 使用方式

1. 準備你的文件：
   - 將 Markdown 或 PDF 文件放在 `data/uploads/` 目錄下
   - 或者直接通過 API 上傳文件

2. 啟動伺服器：

Windows PowerShell:
```powershell
$env:PYTHONPATH = "."; poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

Unix/Linux/macOS:
```bash
PYTHONPATH=. poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

3. 上傳文件：

方法一：上傳文件

Windows PowerShell:
```powershell
Invoke-WebRequest -Method POST -Form @{file=Get-Item "data/uploads/haha.md"} -Uri "http://localhost:8000/qa/upload"
```

Git Bash/Unix/Linux/macOS:
```bash
curl -X POST -F "file=@data/uploads/haha.md" http://localhost:8000/qa/upload
```

方法二：直接上傳文本內容

Windows PowerShell:
```powershell
Invoke-WebRequest -Method POST -Form @{content=(Get-Content "data/uploads/haha.md" -Raw); filename="haha.md"} -Uri "http://localhost:8000/qa/upload"
```

Unix/Linux/macOS:
```bash
curl -X POST -F "content=$(cat data/uploads/haha.md)" -F "filename=haha.md" http://localhost:8000/qa/upload
```

4. 提問：

Windows PowerShell:
```powershell
Invoke-WebRequest -Method POST -Body (@{text="你的問題"} | ConvertTo-Json) -ContentType "application/json" -Uri "http://localhost:8000/qa/query"
```

Unix/Linux/macOS:
```bash
curl -X POST -H "Content-Type: application/json" -d '{"text":"文件主旨是什麼"}' http://localhost:8000/qa/query
```

## 授權條款

MIT License
