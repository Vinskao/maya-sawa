# Markdown 問答系統

這是一個基於 FastAPI、LangChain 和 PostgreSQL (pgvector) 建構的強大文件問答系統。你可以對你的 Markdown 文件提問，系統會根據文件內容提供 AI 驅動的答案。

## 系統架構圖

```mermaid
graph TD
    %% User Layer
    User[User] --> WebAPI[Web API]
    User --> CLI[CLI Tools]
    
    %% API Layer
    WebAPI --> FastAPI[FastAPI Application]
    CLI --> FastAPI
    
    %% Core Service Layer
    FastAPI --> QARouter[QA Router]
    FastAPI --> SyncRouter[Sync Router]
    FastAPI --> ChatRouter[Chat Router]
    
    %% Business Logic Layer
    QARouter --> QAChain[QA Chain]
    QARouter --> VectorStore[Vector Store]
    QARouter --> ChatHistory[Chat History]
    
    SyncRouter --> Scheduler[Scheduler]
    SyncRouter --> VectorStore
    
    ChatRouter --> ChatHistory
    
    %% Data Processing Layer
    QAChain --> LLM[OpenAI GPT]
    QAChain --> Embeddings[OpenAI Embeddings]
    
    VectorStore --> Postgres[(PostgreSQL + pgvector)]
    ChatHistory --> Redis[(Redis)]
    
    %% External Services
    Scheduler --> RemoteAPI[Remote API]
    Loader[Document Loader] --> VectorStore
    
    %% Connection Pool Management
    ConnectionPool[Connection Pool Manager] --> Postgres
    ConnectionPool --> Redis
    
    %% Style Definitions
    classDef userLayer fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    classDef apiLayer fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef serviceLayer fill:#e8f5e8,stroke:#1b5e20,stroke-width:2px
    classDef dataLayer fill:#fff3e0,stroke:#e65100,stroke-width:2px
    classDef externalLayer fill:#fce4ec,stroke:#880e4f,stroke-width:2px
    
    %% Apply Styles
    class User,WebAPI,CLI userLayer
    class FastAPI,QARouter,SyncRouter,ChatRouter apiLayer
    class QAChain,VectorStore,ChatHistory,Scheduler,Loader,ConnectionPool serviceLayer
    class Postgres,Redis dataLayer
    class LLM,Embeddings,RemoteAPI externalLayer
```

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
│       ├── postgres_store.py # PostgreSQL 向量存儲
│       └── qa_chain.py # 問答鏈實作
├── data/               # 資料目錄
│   └── uploads/        # 上傳的文件存放處
├── pyproject.toml      # Poetry 專案配置
└── README.md          # 本文件
```

## 功能特點

- 文件載入與處理
- 文本分塊（支援重疊）
- 使用 PostgreSQL + pgvector 進行向量存儲
- 整合 OpenAI 的嵌入模型和聊天模型
- FastAPI REST API 介面

## 環境需求

- Python 3.12 或更高版本
- Poetry（Python 套件管理器）
- PostgreSQL 13+ 與 pgvector 擴展
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

3. 設置 PostgreSQL 資料庫：

### 3.1 安裝 pgvector 擴展
```sql
-- 安裝 pgvector 擴展
CREATE EXTENSION IF NOT EXISTS vector;
```

### 3.2 創建資料表結構
```sql
-- 創建 articles 表
CREATE TABLE articles (
    id SERIAL PRIMARY KEY,
    file_path VARCHAR(500) NOT NULL,
    content TEXT NOT NULL,
    file_date TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding vector(1536)  -- OpenAI 嵌入向量維度
);

-- 創建索引
CREATE UNIQUE INDEX idx_articles_file_path ON articles(file_path);
CREATE INDEX idx_articles_file_date ON articles(file_date);

-- 創建向量索引
CREATE INDEX ON articles 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### 3.3 創建相似度搜索函數
```sql
-- 創建相似度搜索函數
CREATE OR REPLACE FUNCTION similarity_search(
    query_embedding vector,
    match_threshold float,
    match_count int
)
RETURNS TABLE (
    id int,
    file_path varchar,
    content text,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        a.id,
        a.file_path,
        a.content,
        1 - (a.embedding <=> query_embedding) as similarity
    FROM articles a
    WHERE 1 - (a.embedding <=> query_embedding) > match_threshold
    ORDER BY a.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;
```

4. 建立 `.env` 檔案：
```bash
cp .env.example .env
```

5. 編輯 `.env` 並加入你的配置：
```
OPENAI_API_KEY=sk-your-api-key-here
POSTGRES_CONNECTION_STRING=postgresql://username:password@localhost:5432/your_database_name
SIMILARITY_THRESHOLD=0.5
MATCH_COUNT=4
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
```

## 使用方式

1. 啟動伺服器：

Windows PowerShell:
```powershell
$env:PYTHONPATH = "."; poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

Unix/Linux/macOS:
```bash
# 1. 啟動服務器（Debug 模式）
PYTHONPATH=. poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000

# 2. 同步文章（使用預計算的 embedding）
curl -X POST "http://localhost:8000/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{"remote_url":"${PUBLIC_API_BASE_URL}/paprika/articles"}'
```

## 有對話紀錄版本
```bash
# 1. 問答並記錄：
curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"你身高多高、體重多重?","user_id":"user123","language":"chinese"}'

curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"你是誰? 誰是Sorane","user_id":"user123","language":"chinese"}'

curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"誰是Sorane、Maya?","user_id":"user123"}'

Invoke-RestMethod -Uri "http://localhost:8000/qa/query" `
  -Method POST `
  -Headers @{"Content-Type"="application/json"} `
  -Body '{"text":"你身高多高、體重多重?","user_id":"user123"}'
  
Invoke-RestMethod -Uri "http://localhost:8000/qa/query" `
  -Method POST `
  -Headers @{"Content-Type"="application/json"} `
  -Body '{"text":"誰是森築空音?","user_id":"user123"}'
# 2. 查看對話歷史：k
curl -X GET "http://localhost:8000/qa/chat-history/user123"

# 3. 查看統計資訊：
curl -X GET "http://localhost:8000/qa/chat-stats/user123"
```

## 部署配置

### Docker 部署

1. 構建 Docker 映像：
```bash
docker build -t maya-sawa .
```

2. 運行容器：
```bash
docker run -p 8000:8000 \
  -e OPENAI_API_KEY=your-api-key \
  -e POSTGRES_CONNECTION_STRING=your-connection-string \
  -e REDIS_HOST=your-redis-host \
  maya-sawa
```

### Kubernetes 部署

1. 確保已配置 Jenkins 憑證：
   - `OPENAI_API_KEY`
   - `OPENAI_ORGANIZATION`
   - `POSTGRES_CONNECTION_STRING`
   - `REDIS_HOST`
   - `REDIS_CUSTOM_PORT`
   - `REDIS_PASSWORD`
   - `REDIS_QUEUE_QA_KM`
   - `dockerhub-credentials`
   - `kubeconfig-secret`

2. 執行 Jenkins Pipeline：
   - 自動構建 Docker 映像
   - 推送到 Docker Hub
   - 部署到 Kubernetes 集群

3. 訪問服務：
   - 生產環境：`https://peoplesystem.tatdvsonorth.com/maya-sawa/`
   - API 文檔：`https://peoplesystem.tatdvsonorth.com/maya-sawa/docs`

### API 使用示例 (本地開發 vs 生產環境)

#### 1. 同步文章
```bash
# 本地開發
curl -X POST "http://localhost:8000/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{"remote_url":"https://peoplesystem.tatdvsonorth.com/paprika/articles"}'

# 生產環境
curl -X POST "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{"remote_url":"https://peoplesystem.tatdvsonorth.com/paprika/articles"}'
```

#### 2. 問答查詢
```bash
# 本地開發
curl -X POST "http://localhost:8000/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"What is Java OOP?","user_id":"user123"}'

# 生產環境
curl -X POST "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"你幾公分高?","user_id":"user123"}'
```

#### 3. 查看聊天歷史
```bash
# 本地開發
curl -X GET "http://localhost:8000/qa/chat-history/user123"

# 生產環境
curl -X GET "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/chat-history/user123"
```

#### 4. 查看聊天統計
```bash
# 本地開發
curl -X GET "http://localhost:8000/qa/chat-stats/user123"

# 生產環境
curl -X GET "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/chat-stats/user123"
```

#### 5. 清除聊天歷史
```bash
# 本地開發
curl -X DELETE "http://localhost:8000/qa/chat-history/user123"

# 生產環境
curl -X DELETE "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/chat-history/user123"
```

#### 6. 查看所有用戶
```bash
# 本地開發
curl -X GET "http://localhost:8000/qa/chat-users"

# 生產環境
curl -X GET "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/chat-users"
```

#### 7. 查看文章統計
```bash
# 本地開發
curl -X GET "http://localhost:8000/qa/stats"

# 生產環境
curl -X GET "https://peoplesystem.tatdvsonorth.com/maya-sawa/qa/stats"
```

#### 8. API 文檔
```bash
# 本地開發
open http://localhost:8000/docs

# 生產環境
open https://peoplesystem.tatdvsonorth.com/maya-sawa/docs
```

## 自動同步功能

### 1. 程式啟動時同步
當 Maya Sawa 應用程式啟動時，會自動執行一次文章同步，確保資料是最新的。

### 2. 定期同步排程
系統提供兩種定期同步方式：

#### 方式一：應用程式內建排程（推薦）
- 每 3 天凌晨 3:00 自動執行同步
- 由應用程式內部管理，無需額外配置
- 在 `maya_sawa/main.py` 中配置

#### 方式二：Kubernetes CronJob
- 使用 Kubernetes CronJob 進行排程
- 每 3 天凌晨 3:00 執行
- 獨立於應用程式運行
- 配置在 `k8s/cronjob.yaml`

### 3. 手動同步
可以使用以下方式手動執行同步：

```bash
# 使用同步腳本
poetry run python scripts/sync_articles.py

# 或使用 API 端點
curl -X POST "http://localhost:8000/qa/sync-from-api" \
  -H "Content-Type: application/json"
```

### 4. 同步配置
同步功能會：
- 從遠端 API 獲取文章資料
- 使用預計算的 embedding 進行向量化
- 更新 PostgreSQL 資料庫
- 記錄同步日誌

### 5. 監控同步狀態
```bash
# 查看 CronJob 狀態
kubectl get cronjobs
kubectl get jobs

# 查看同步日誌
kubectl logs job/maya-sawa-sync-<timestamp>

# 查看應用程式日誌
kubectl logs deployment/maya-sawa
```

## 資料庫查詢範例

### 查看所有文章
```sql
SELECT id, file_path, title, publish_date, created_at 
FROM articles 
ORDER BY created_at DESC;
```

### 按標籤搜索文章
```sql
-- 搜索包含特定標籤的文章
SELECT title, file_path, tags 
FROM articles 
WHERE tags && ARRAY['SRP', 'OCP'];

-- 使用函數搜索
SELECT * FROM search_by_tags(ARRAY['JavaScript', 'Algorithms'], 5);
```

### 查看向量相似度
```sql
-- 假設你有一個查詢向量
SELECT 
    title,
    file_path,
    tags,
    1 - (embedding <=> '[0.1, 0.2, ...]'::vector) as similarity
FROM articles
ORDER BY embedding <=> '[0.1, 0.2, ...]'::vector
LIMIT 5;
```

### 查看資料庫大小
```sql
SELECT 
    pg_size_pretty(pg_total_relation_size('articles')) as table_size,
    COUNT(*) as total_articles
FROM articles;
```

### 按發布日期範圍搜索
```sql
SELECT title, file_path, publish_date
FROM articles
WHERE publish_date BETWEEN '2023-01-01' AND '2024-12-31'
ORDER BY publish_date DESC;
```

### 統計標籤使用頻率
```sql
SELECT 
    unnest(tags) as tag,
    COUNT(*) as frequency
FROM articles
GROUP BY tag
ORDER BY frequency DESC;
```

## 授權條款

MIT License

## API 回應格式

### 成功回應
```json
{
    "success": true,
    "answer": "AI 生成的答案",
    "data": [
        {
            "id": 11,
            "file_path": "SOLID.md",
            "content": "文件內容片段...",
            "similarity": 0.85
        }
    ]
}
```

### 無相關內容回應
```json
{
    "success": false,
    "message": "抱歉，我沒有找到相關的文件內容來回答您的問題。",
    "data": []
}
```

