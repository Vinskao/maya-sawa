# Maya Sawa - Agent 開發指南

## 專案概述

Maya Sawa 是一個**統一的 FastAPI 後端服務**，整合了三個原本獨立的專案：

| 原專案 | 框架 | 現在位置 | 說明 |
|--------|------|----------|------|
| maya-sawa-v1 | FastAPI | `/qa/*` | 原有的文檔問答系統 |
| maya-sawa-v2 | Django | `/maya-v2/*` | 對話管理、多AI模型支援 |
| paprika | Laravel | `/paprika/*` | 文章 CRUD 管理 |

## 整合架構

```
maya-sawa-v1 (FastAPI - 統一入口)
│
├── /maya-sawa/qa/*           原有 FastAPI 功能
│   ├── POST /query           文檔問答查詢
│   ├── GET /stats            文章統計
│   ├── POST /sync-from-api   從 API 同步文章
│   ├── GET /chat-history/{user_id}
│   ├── POST /search-people   人員語義搜索
│   └── POST /convert-to-vector 文本轉向量
│
├── /paprika/*                從 Laravel 移植
│   ├── GET /articles         文章列表
│   ├── GET /articles/{id}    單篇文章
│   ├── POST /articles        創建文章
│   ├── PUT /articles/{id}    更新文章
│   ├── DELETE /articles/{id} 刪除文章
│   ├── POST /articles/sync   批量同步
│   └── GET /up               健康檢查
│
└── /maya-v2/*                從 Django 移植
    ├── /conversations/*      對話 CRUD (ViewSet 風格)
    ├── /ai-models/*          AI 模型管理
    ├── /available-models/    可用模型列表
    ├── /add-model/           添加模型
    ├── /ask-with-model/      多模型問答
    ├── /task-status/{id}     異步任務狀態
    └── /qa/chat-history/{session_id}
```

## 數據庫配置

### 分離式數據庫策略

本專案採用**數據庫分離**策略，各功能連接獨立的數據庫：

| 功能 | 數據庫 | 配置變數 |
|------|--------|----------|
| 原有 QA 系統 | PostgreSQL | `DB_*` |
| 人員系統 | PostgreSQL | `PEOPLE_DB_*` |
| Paprika 文章 | PostgreSQL | `PAPRIKA_DB_*` |
| Maya-v2 對話 | PostgreSQL | `MAYA_V2_DB_*` |

### 環境變數範例

```bash
# 主數據庫 (文章向量)
DB_HOST=your-host
DB_DATABASE=philotes
DB_USERNAME=user
DB_PASSWORD=pass

# 人員數據庫
PEOPLE_DB_HOST=your-host
PEOPLE_DB_DATABASE=peoplesystem

# Paprika 數據庫 (可選)
PAPRIKA_DB_TYPE=sqlite  # 或 postgresql
PAPRIKA_DB_PATH=/path/to/database.sqlite

# Maya-v2 數據庫 (可選)
MAYA_V2_DB_HOST=your-host
MAYA_V2_DB_DATABASE=maya_v2
```

## 多 AI 提供者支援

### 支援的 AI 提供者

| 提供者 | 配置變數 | 預設模型 |
|--------|----------|----------|
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini |
| Google Gemini | `GEMINI_API_KEY` | gemini-1.5-flash |
| Alibaba Qwen | `QWEN_API_KEY` | qwen-turbo |

### 環境變數配置

```bash
# OpenAI (必須)
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.openai.com/v1

# Gemini (可選)
GEMINI_ENABLED=true
GEMINI_API_KEY=xxx

# Qwen (可選)
QWEN_ENABLED=true
DASHSCOPE_API_KEY=xxx

# 啟用的提供者
ENABLED_PROVIDERS=openai,gemini,qwen
```

## Celery 異步任務

### 配置

```bash
# Celery Broker (使用 RabbitMQ 或 Redis)
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672//
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

### 啟動 Worker

```bash
celery -A maya_sawa.tasks.celery_app worker -Q maya_sawa -l info
```

## 文件結構

```
maya_sawa/
├── api/                    API 路由
│   ├── qa.py              原有問答 API
│   ├── articles.py        Paprika 文章 API (新增)
│   ├── ai_models.py       AI 模型管理 API (新增)
│   ├── conversations.py   對話管理 API (新增)
│   └── ask.py             多模型問答 API (新增)
│
├── core/                   核心模組 (重新組織)
│   ├── config/            配置管理
│   │   ├── config.py           主要配置
│   │   └── config_manager.py   配置管理器
│   ├── database/          數據庫連接
│   │   └── connection_pool.py  連接池
│   ├── qa/                問答系統
│   │   ├── qa_chain.py         QA 鏈
│   │   └── qa_engine.py        QA 引擎
│   ├── processing/        文檔處理
│   │   ├── loader.py           文檔載入
│   │   ├── page_analyzer.py    頁面分析
│   │   └── langchain_shim.py   LangChain 適配
│   ├── services/          服務層
│   │   ├── chat_history.py     聊天歷史
│   │   └── scheduler.py        調度器
│   ├── errors/            錯誤處理
│   │   └── errors.py           錯誤定義
│   └── data/              數據文件
│       ├── constants.json
│       ├── keywords.json
│       ├── prompts.json
│       └── rules.json
│
├── services/               服務層 (新增)
│   └── ai_providers/      多 AI 提供者
│       ├── base.py        基類與工廠
│       ├── openai_provider.py
│       ├── gemini_provider.py
│       └── qwen_provider.py
│
├── tasks/                  Celery 任務 (新增)
│   ├── celery_app.py      Celery 配置
│   └── ai_tasks.py        AI 處理任務
│
├── people/                 人員系統模組
└── main.py                 FastAPI 入口
```

## Agent 開發注意事項

### 1. API 路徑兼容性

**關鍵原則**：前端接口必須保持不變！

- 所有 API 路徑必須與原系統完全一致
- 使用 `root_path="/maya-sawa"` 作為 Ingress 前綴
- Legacy 端點必須保留向後兼容

### 2. 數據庫操作

- 使用 `get_article_db()` 操作文章（向後兼容 `get_paprika_db()`）
- 使用 `get_conversation_db()` 操作對話和 AI 模型（向後兼容 `get_maya_v2_db()`）
- 避免在 SQLAlchemy 模型中使用 `metadata` 作為欄位名（保留字）

### 3. AI 提供者

```python
from maya_sawa.services.ai_providers import AIProviderFactory

# 獲取提供者
provider = AIProviderFactory.get_provider('openai', 'gpt-4o-mini')

# 生成回應
response = await provider.generate_response(
    prompt="你的問題",
    context="相關上下文",
    system_message="系統提示"
)
```

### 4. 異步任務

```python
from maya_sawa.tasks.ai_tasks import process_ai_response_task

# 發送異步任務
result = process_ai_response_task.delay(task_id)

# 檢查狀態
status = result.status
```

## 7. 這次排查的經驗

### Internal Secret 與 Pod Env
- `MARKET_INTERNAL_SECRET` 必須確認在**正在執行的 pod process** 裡真的有值，不只看 `kubectl get deploy` 或 `kubectl exec ... env` 的表面輸出。
- 這次問題的核心是 `require_internal_secret()` 讀到空值，導致 `/market/internal/portfolio` 和 `/market/internal/usage` 回 `503 Internal market access is not configured`。
- 若遇到 service-to-service 驗證失敗，請優先檢查：
  - `kubectl exec deploy/maya-sawa -- sh -c 'printf %s "$MARKET_INTERNAL_SECRET" | wc -c'`
  - `/proc/1/environ` 是否和 shell env 一致
  - rollout restart 後 pod 是否重新吃到最新 secret

### 快取與回應驗證
- `shioaji_market_service` 的 portfolio / usage 都是 Redis cache-backed，外部 API 成功不代表前端一定會立即更新。
- 驗證時要同時看：
  - 直接打公開 endpoint 是否回 `200`
  - `fetchedAt` 是否是新時間
  - `kubectl logs deploy/maya-sawa` 是否還在吐舊的 `503` 或 `401`
- 如果前端還顯示舊值，問題可能在前端 fallback cache，而不是後端 endpoint 本身。

## IBKR Client Portal API 整合（海外資產）

### 架構與 Shioaji 的差異
- Shioaji 用 API key 直接登入；IBKR CPAPI v1 需要**有狀態的 Client Portal Gateway**（瀏覽器登入維持 session），maya-sawa 只讀取已驗證的 gateway，不碰帳密。
- 本地 gateway：`clientportal.gw/`，因 macOS 5000 被 AirPlay 佔用，改 `listenPort: 5050`，`https://localhost:5050`。
- OKE：`maya-sawa/ibkr-gateway/` 子目錄（在 maya-sawa repo 內，共用同一條 Jenkins pipeline）。maya-sawa `Jenkinsfile` 的 `Build & Push IBKR Gateway` stage 以 `ibkr-gateway/` 為 build context 建 image `papakao/ibkr-gateway:latest`，Deploy stage `kubectl apply -f ibkr-gateway/k8s/deployment.yaml` 部署成 `Deployment/Service ibkr-gw`（ClusterIP :5000，內部專用）。maya-sawa `.dockerignore` 排除 `ibkr-gateway/`，避免 12MB vendored runtime 污染 maya-sawa image context。`conf.yaml` 的 `ips.allow` **必須包含 `10.*`**（pod CIDR 10.244.0.0/16），否則 maya-sawa 會被 gateway 擋 403。
- Session 在記憶體內：每次 pod 重啟或 ~24h 硬過期後，需人工 `kubectl port-forward deployment/ibkr-gw 5000:5000` 再瀏覽器登入 + 2FA（零售帳號無 headless 登入）。

### 登入模型、port-forward 與安全性（重要）
**「看資料」與「登入 gateway」是兩件分開的事，不要混淆：**
```
[瀏覽器] ←─讀 Redis cache─ [maya-sawa] ←─每 240s 抓一次─ [ibkr-gw pod]
  看資料                                          ↑ session 在記憶體，只有這裡要人工登入
```
- **看資料不需要任何人工介入**：前端只讀 Redis；maya-sawa 每 `IBKR_REFRESH_SECONDS`(240s) 從 gateway 抓 snapshot 寫進 Redis，這個 refresh 同時兼作 keepalive。
- **登入只在 session 失效時才需要**：IBKR 零售帳號 session 硬上限 ~24h，或 pod 重啟（記憶體 session 消失）。所以頻率是「約一天一次 / pod 重啟後一次」，不是每次看都要。
- **零售帳號無法自動登入**：CPAPI 對零售帳號強制互動式瀏覽器登入 + 帳密 + 2FA（IBKR Mobile/簡訊），2FA 無法代理，因此**無法接到網站 login 自動觸發**（只有機構/advisor 帳號有 OAuth）。
- **port-forward 不是永久、也不參與正式資料流**：maya-sawa 走叢集內 Service `https://ibkr-gw:5000`(ClusterIP)，一直都在。`kubectl port-forward` 只是登入那一刻讓本機瀏覽器能連到 gateway 的臨時隧道（綁終端機，關掉就斷），登入完即可關閉，session 留在 pod 記憶體繼續服務。
- **安全性**：
  - gateway 是 ClusterIP、**無 Ingress**，外網碰不到；`conf.yaml` `ips.allow: 10.*` 限制只接受 pod CIDR + localhost。
  - gateway **不存帳密**，只存記憶體 session，重啟即自動登出。
  - ⚠️ 但記憶體裡的 session 是**完整權限**（CPAPI 含下單端點），任何能連到 gateway 的人都能讀 portfolio 甚至下單。**切勿為了省去 port-forward 而把 gateway 開成公開 Ingress** —— 等於把可下單 session 放在公網。維持 ClusterIP + port-forward 登入是目前最安全做法。

### 重新登入步驟（session 失效時）
```bash
ssh oke-node
kubectl port-forward deployment/ibkr-gw 5000:5000 -n default   # 臨時隧道，登入完關掉即可
# 另開瀏覽器 https://localhost:5000 → 輸入 thisisunsafe 跳過自簽憑證 → IBKR 帳密 + 2FA
# 等 "Client login succeeds"，~240s 內 Redis 會更新，前端 Account Portfolio 自動帶出海外資料
```

### 服務與快取（與 Shioaji 同政策）
- `services/ibkr_market.py` 的 `IbkrMarketService` 為 Redis cache-backed：背景 loop（`IBKR_REFRESH_SECONDS`，預設 240s，同時兼作 keepalive）抓 gateway snapshot 寫入 Redis key `maya-sawa:market:ibkr`；request 只讀 cache。
- snapshot 內容：`/portfolio/{acct}/accounts`、`/ledger`（`BASE` key = USD 總額）、`/summary`、`/positions/{page}`（分頁 30、qty=0 略過）。
- 多幣別 FX：`open.er-api.com` USD base，`TWD_per_cur = rates[TWD]/rates[cur]`，處理 USD 股票 + JPY CFD。可用 `USD_TWD_RATE` 覆寫。
- `merge_ibkr_into_portfolio()` 把 IBKR（轉 NT$）併入 Shioaji portfolio 的 cashBalance / totalAssetsEstimated / totalPnl，並掛上 `ibkr` 與 `regions`（台灣 / 海外 / 總）。

### 端點
- `GET /market/ibkr`、`GET /market/internal/ibkr`：單獨回 IBKR snapshot。
- `GET /market/portfolio`、`/market/internal/portfolio`：已併入 IBKR（gateway/cache 不可用時靜默略過，不影響台股 portfolio）。

### 環境變數
```bash
IBKR_ENABLED=true
IBKR_GATEWAY_URL=https://localhost:5050      # 本地；OKE 為 https://ibkr-gw:5000
IBKR_REFRESH_SECONDS=240
# IBKR_ACCOUNT_ID=U16739398                  # 選填，預設取第一個帳號
# USD_TWD_RATE=31.5                          # 選填，覆寫即時匯率
```

### 排查
- IBKR 區塊沒資料：先確認 gateway pod 在跑、session 仍驗證（`/portfolio/accounts` 回 JSON 而非 login redirect）、`kubectl logs deploy/maya-sawa` 沒一直印 `Skipping IBKR merge`。
- 即使 `tickle` 回 `authenticated:false`，`/portfolio/*` 仍會回上次的快取資料（IBKR 後端行為）；要最新值需重新登入。

## API 端點規格說明

### 插入文章 API 規格

#### 單篇文章插入
**端點**: `POST /maya-sawa/paprika/articles`

**請求格式**:
```json
{
  "file_path": "string (max 500 chars, unique)",
  "content": "string (required)",
  "file_date": "datetime (ISO format)"
}
```

**請求示例**:
```bash
curl -X POST "http://localhost:8000/maya-sawa/paprika/articles" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "my-article.md",
    "content": "# My Article\n\nThis is my article content.",
    "file_date": "2024-01-01T12:00:00Z"
  }'
```

**成功回應** (201 Created):
```json
{
  "success": true,
  "message": "Article created successfully",
  "data": {
    "id": 1,
    "file_path": "my-article.md",
    "content": "# My Article\n\nThis is my article content.",
    "file_date": "2024-01-01T12:00:00.000000",
    "embedding": null,
    "created_at": "2024-01-01T12:00:00.000000",
    "updated_at": "2024-01-01T12:00:00.000000"
  }
}
```

**錯誤回應**:
- `422 Unprocessable Entity`: file_path 已存在
- `503 Service Unavailable`: 數據庫不可用

**驗證規則**:
- `file_path`: 必填，最長500字符，必須唯一
- `content`: 必填，字符串
- `file_date`: 必填，ISO格式日期時間

#### 批量文章插入 (推薦)
**端點**: `POST /maya-sawa/paprika/articles/batch`

**請求格式**:
```json
[
  {
    "file_path": "article1.md",
    "content": "# Article 1\nContent 1",
    "file_date": "2024-01-01T00:00:00Z"
  },
  {
    "file_path": "article2.md",
    "content": "# Article 2\nContent 2",
    "file_date": "2024-01-02T00:00:00Z"
  }
]
```

**請求示例**:
```bash
curl -X POST "http://localhost:8000/maya-sawa/paprika/articles/batch" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "file_path": "doc1.md",
      "content": "# Document 1\n\nThis is the first document.",
      "file_date": "2024-01-01T10:00:00Z"
    },
    {
      "file_path": "doc2.md",
      "content": "# Document 2\n\nThis is the second document.",
      "file_date": "2024-01-02T11:00:00Z"
    }
  ]'
```

**成功回應**:
```json
{
  "success": true,
  "total_requested": 2,
  "created": 2,
  "skipped": 0,
  "errors": [],
  "articles": [
    {
      "index": 0,
      "id": 1,
      "file_path": "doc1.md",
      "created": true
    },
    {
      "index": 1,
      "id": 2,
      "file_path": "doc2.md",
      "created": true
    }
  ],
  "message": "Batch creation completed: 2 created, 0 skipped"
}
```

**批量插入 vs 輪詢**:
- ✅ **批量插入**: 一次請求處理多篇文章，高效
- ❌ **輪詢**: 多個單獨請求，效率低，容易出錯

#### 批量文章同步 (一次插入多篇)
**端點**: `POST /maya-sawa/paprika/articles/sync`

**適用場景**: 數據遷移、批量導入、系統初始化

**請求格式**:
```json
{
  "articles": [
    {
      "file_path": "string (max 500 chars)",
      "content": "string (required)",
      "file_date": "string (ISO format, required)"
    }
  ]
}
```

**請求示例**:
```bash
curl -X POST "http://localhost:8000/maya-sawa/paprika/articles/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "articles": [
      {
        "file_path": "article1.md",
        "content": "# Article 1\nContent 1",
        "file_date": "2024-01-01T00:00:00Z"
      },
      {
        "file_path": "article2.md",
        "content": "# Article 2\nContent 2",
        "file_date": "2024-01-02T00:00:00Z"
      }
    ]
  }'
```

**成功回應**:
```json
{
  "success": true,
  "message": "Articles synced successfully",
  "data": {
    "total_received": 2,
    "created": 2,
    "updated": 0,
    "skipped": 0
  },
  "timestamp": "2024-01-01T12:00:00.000000Z"
}
```

**同步邏輯**:
- **創建**: 如果 file_path 不存在
- **更新**: 如果 file_path 存在且新 file_date 較新
- **跳過**: 如果 file_path 存在但 file_date 不較新
## API 端點測試

### 測試環境準備

```bash
# 啟動服務
cd maya-sawa-v1
poetry install
poetry run uvicorn maya_sawa.main:app --reload --host 0.0.0.0 --port 8000

# 在另一個終端啟動 Celery worker (如果需要異步任務)
celery -A maya_sawa.tasks.celery_app worker -Q maya_sawa -l info

# 注意：所有 curl 命令都已寫死為具體的 localhost URL
# 無需設置任何環境變數，直接複製命令執行即可
```

### 1. 根端點測試

```bash
# 健康檢查和 API 信息
curl -X GET "http://localhost:8000/maya-sawa/" | jq .
```

### 2. QA 系統端點 (`/qa/*`)

#### 文檔問答查詢
```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Maya Sawa 是什麼？",
    "user_id": "test_user",
    "language": "chinese",
    "name": "Maya"
  }' | jq .
```

#### 文章統計
```bash
curl -X GET "http://localhost:8000/maya-sawa/qa/stats" | jq .
```

#### 從 API 同步文章

這個 API 用於從遠端服務同步文章數據到本地的向量資料庫。

**注意：** 這個 API 需要遠端服務提供文章數據。如果遠端服務不可用，可以跳過這個測試。

**生產環境測試：**
```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{
    "remote_url": "https://peoplesystem.tatdvsonorth.com/paprika/articles"
  }' | jq .
```

**本地測試選項：**

```bash
# 選項1: 使用預設 URL (會自動拼接 PUBLIC_API_BASE_URL + /paprika/articles)
# 注意：這需要遠端服務可用
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{}' | jq .

# 選項2: 如果你有另一個本地服務運行在不同端口，提供文章數據
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{
    "remote_url": "http://localhost:8001/paprika/articles"
  }' | jq .

# 選項3: 測試遠端服務是否可用 (先檢查遠端服務)
curl -X GET "https://peoplesystem.tatdvsonorth.com/paprika/articles" | jq . || echo "遠端服務不可用"

# 選項4: 完整數據同步測試 (推薦)
# 首先檢查你有多少篇文章在原來的 QA 系統中
curl -X GET "http://localhost:8000/maya-sawa/qa/stats" | jq '.stats.total_articles'

# 步驟1: 創建測試數據
curl -X POST "http://localhost:8000/maya-sawa/paprika/articles" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "test/sync-article.md",
    "content": "# 同步測試文章\n這是一篇測試同步功能的文章。",
    "file_date": "2024-01-01T00:00:00Z"
  }' | jq .

# 步驟2: 測試同步 (使用本地 Paprika 服務作為數據源)
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" \
  -d '{
    "remote_url": "http://localhost:8000/maya-sawa/paprika/articles"
  }' | jq .
```

**測試結果驗證：**
```bash
# ✅ 成功同步 4 篇文章（包括我們創建的測試數據）
# ✅ 所有文章都成功生成 embedding
# ✅ 同步功能完全正常工作
```

**常見問題：**
- **連接失敗**：遠端服務可能暫時不可用，這是正常的
- **只有1篇文章**：因為 Paprika 數據庫中只有1篇文章，需要先添加更多測試數據
- **跳過測試**：如果不需要測試同步功能，可以跳過這個 API
- **完整測試**：按照上面的步驟添加測試數據，然後測試同步功能

**數據遷移說明：**
- 你原來的 QA 系統有 **38 篇文章**
- 新的 Paprika 系統目前有 **4 篇測試文章**
- 要測試完整功能，可以將你的真實文章數據遷移到 Paprika 數據庫中

#### 聊天歷史
```bash
curl -X GET "http://localhost:8000/maya-sawa/qa/chat-history/test_user" | jq .
```

#### 人員語義搜索
```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/search-people" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "戰鬥力很強的角色",
    "limit": 5,
    "threshold": 0.5,
    "sort_by_power": true
  }' | jq .
```

### 3. Paprika 文章管理 (`/paprika/*`)

#### 健康檢查
```bash
curl -X GET "http://localhost:8000/maya-sawa/paprika/up" | jq .
```

#### 文章列表
```bash
curl -X GET "http://localhost:8000/maya-sawa/paprika/articles" | jq .
```

#### 單篇文章查詢
```bash
curl -X GET "http://localhost:8000/maya-sawa/paprika/articles/1" | jq .
```

#### 創建文章
```bash
curl -X POST "http://localhost:8000/maya-sawa/paprika/articles" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "test/article.md",
    "content": "# 測試文章\n這是一篇測試文章的內容。",
    "file_date": "2024-01-01T00:00:00Z"
  }' | jq .
```

#### 更新文章
```bash
curl -X PUT "http://localhost:8000/maya-sawa/paprika/articles/1" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# 更新後的測試文章\n這是更新後的內容。",
    "file_date": "2024-01-01T00:00:00Z"
  }' | jq .
```

#### 批量創建文章 (優化版)
```bash
curl -X POST "http://localhost:8000/maya-sawa/paprika/articles/batch" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "file_path": "batch/article1.md",
      "content": "# 批量文章1\n這是第一篇批量創建的文章。",
      "file_date": "2024-01-01T10:00:00Z"
    },
    {
      "file_path": "batch/article2.md",
      "content": "# 批量文章2\n這是第二篇批量創建的文章。",
      "file_date": "2024-01-02T11:00:00Z"
    },
    {
      "file_path": "batch/article1.md",
      "content": "# 重複文章\n這篇文章會被跳過因為 file_path 重複。",
      "file_date": "2024-01-03T12:00:00Z"
    }
  ]' | jq .
```

**批量創建回應示例：**
```json
{
  "success": true,
  "total_requested": 3,
  "created": 2,
  "skipped_duplicate": 1,
  "failed": 0,
  "errors": [
    {
      "index": 2,
      "file_path": "batch/article1.md",
      "error_code": 1003,
      "error": "Article with this file_path already exists"
    }
  ],
  "articles": [
    {
      "index": 0,
      "id": 2,
      "file_path": "batch/article1.md",
      "created": true
    },
    {
      "index": 1,
      "id": 3,
      "file_path": "batch/article2.md",
      "created": true
    }
  ],
  "message": "Batch creation completed: 2 created, 1 skipped (duplicate), 0 failed"
}
```

**效能改善：**
- ✅ **單次查詢檢查重複**：使用 IN 查詢一次性檢查所有重複項目
- ✅ **批量插入**：使用 SQLAlchemy 的批量插入提升效能
- ✅ **輸入驗證**：檢查空陣列和最大批次大小（1000）
- ✅ **精準統計**：分開統計重複跳過和失敗項目

#### 批量同步文章
```bash
curl -X POST "http://localhost:8000/maya-sawa/paprika/articles/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "articles": [
      {
        "file_path": "sync/article1.md",
        "content": "# 同步文章1\n內容1",
        "file_date": "2024-01-01T00:00:00Z"
      },
      {
        "file_path": "sync/article2.md",
        "content": "# 同步文章2\n內容2",
        "file_date": "2024-01-02T00:00:00Z"
      }
    ]
  }' | jq .
```

#### 刪除文章
```bash
curl -X DELETE "http://localhost:8000/maya-sawa/paprika/articles/1" | jq .
```

### 4. Maya-v2 對話管理 (`/maya-v2/*`)

#### 對話列表
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/conversations/" | jq .
```

#### 創建對話
```bash
curl -X POST "http://localhost:8000/maya-sawa/maya-v2/conversations/" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_type": "general",
    "title": "測試對話"
  }' | jq .
```

#### 獲取單個對話
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/" | jq .
```

#### 更新對話
```bash
curl -X PUT "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "更新後的測試對話",
    "status": "active"
  }' | jq .
```

#### 發送訊息
```bash
curl -X POST "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/send_message/" \
  -H "Content-Type: application/json" \
  -d '{
    "content": "你好，這是測試訊息"
  }' | jq .
```

#### 獲取對話訊息
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/messages/" | jq .
```

#### 刪除對話
```bash
curl -X DELETE "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/" | jq .
```

### 5. AI 模型管理 (`/maya-v2/*`)

#### AI 模型列表
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/ai-models/" | jq .
```

#### 包含非活躍模型
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/ai-models/?include_inactive=true" | jq .
```

#### 單個模型詳情
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/ai-models/1" | jq .
```

#### 可用模型列表
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/available-models/" | jq .
```

#### AI 提供者配置
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/ai-providers/" | jq .
```

#### 添加模型
```bash
curl -X POST "http://localhost:8000/maya-sawa/maya-v2/add-model/" | jq .
```

### 6. 多模型問答 (`/maya-v2/*`)

#### 同步問答
```bash
curl -X POST "http://localhost:8000/maya-sawa/maya-v2/ask-with-model/" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "請解釋什麼是機器學習",
    "model_name": "gpt-4o-mini",
    "sync": true,
    "use_knowledge_base": true
  }' | jq .
```

#### 異步問答
```bash
curl -X POST "http://localhost:8000/maya-sawa/maya-v2/ask-with-model/" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "請解釋什麼是深度學習",
    "model_name": "gpt-4o-mini",
    "sync": false,
    "use_knowledge_base": true
  }' | jq .

# 從回應中獲取 task_id，然後檢查狀態
TASK_ID="從上面回應中獲取的任務ID"
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/task-status/$TASK_ID" | jq .
```

#### 聊天歷史 (Maya-v2 版本)
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-v2/qa/chat-history/qa-12345678" | jq .
```

### 7. Legacy 聊天歷史 (向後兼容)

#### 舊版聊天歷史端點
```bash
curl -X GET "http://localhost:8000/maya-sawa/maya-sawa/qa/chat-history/qa-12345678" | jq .
```

### 8. 同步配置端點

#### 同步配置查詢
```bash
curl -X GET "http://localhost:8000/maya-sawa/qa/sync-config" | jq .
```

#### 停止同步任務
```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/stop-sync" | jq .
```

## 完整 API 端點測試表格

### 測試準備
```bash
# 啟動服務
cd maya-sawa-v1
poetry install
poetry run uvicorn maya_sawa.main:app --reload --host 0.0.0.0 --port 8000

# 在另一個終端啟動 Celery worker (如果需要異步任務)
celery -A maya_sawa.tasks.celery_app worker -Q maya_sawa -l info
```

### API 端點測試矩陣

| 模組 | 端點 | 方法 | 描述 | 測試指令 | 預期結果 |
|------|------|------|------|----------|----------|
| **根端點** | `/` | GET | API 信息和健康檢查 | `curl -X GET "http://localhost:8000/maya-sawa/" \| jq .` | `{"message": "Maya Sawa Unified API v0.2.0", "version": "0.2.0", "status": "healthy"}` |
| **QA 系統** | `/qa/query` | POST | 文檔問答查詢 | `curl -X POST "http://localhost:8000/maya-sawa/qa/query" -H "Content-Type: application/json" -d '{"text": "Maya Sawa 是什麼？", "user_id": "test_user", "language": "chinese", "name": "Maya"}' \| jq .` | `{"success": true, "answer": "...", "sources": [...]}` |
| | `/qa/convert-to-vector` | POST | 文本轉向量 | `curl -X POST "http://localhost:8000/maya-sawa/qa/convert-to-vector" -H "Content-Type: application/json" -d '{"content": "這是測試文本"}' \| jq .` | `{"success": true, "vector": [0.123, ...], "dimensions": 1536, "model": "text-embedding-3-small"}` |
| | `/qa/stats` | GET | 文章統計 | `curl -X GET "http://localhost:8000/maya-sawa/qa/stats" \| jq .` | `{"success": true, "stats": {"total_articles": 38, "total_chunks": 152, "last_sync": "..."}}` |
| | `/qa/sync-from-api` | POST | 從 API 同步文章 | `curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" -H "Content-Type: application/json" -d '{"remote_url": "https://peoplesystem.tatdvsonorth.com/paprika/articles"}' \| jq .` | `{"success": true, "message": "Sync completed", "stats": {...}}` |
| | `/qa/chat-history/{user_id}` | GET | 獲取對話歷史 | `curl -X GET "http://localhost:8000/maya-sawa/qa/chat-history/test_user" \| jq .` | `{"success": true, "history": [...], "total": 5}` |
| | `/qa/search-people` | POST | 人員語義搜索 | `curl -X POST "http://localhost:8000/maya-sawa/qa/search-people" -H "Content-Type: application/json" -d '{"query": "戰鬥力很強的角色", "limit": 5, "threshold": 0.5, "sort_by_power": true}' \| jq .` | `{"success": true, "results": [...], "total_found": 3}` |
| | `/qa/sync-config` | GET | 同步配置查詢 | `curl -X GET "http://localhost:8000/maya-sawa/qa/sync-config" \| jq .` | `{"success": true, "config": {...}, "status": "idle"}` |
| | `/qa/stop-sync` | POST | 停止同步任務 | `curl -X POST "http://localhost:8000/maya-sawa/qa/stop-sync" \| jq .` | `{"success": true, "message": "Sync stopped"}` |
| **Paprika 文章管理** | `/paprika/up` | GET | 健康檢查 | `curl -X GET "http://localhost:8000/maya-sawa/paprika/up" \| jq .` | `{"status": "ok", "timestamp": "2025-12-09T...", "version": "1.0.0", "database_available": true}` |
| | `/paprika/articles` | GET | 文章列表 | `curl -X GET "http://localhost:8000/maya-sawa/paprika/articles" \| jq .` | `{"success": true, "data": [...]}` |
| | `/paprika/articles/{id}` | GET | 單篇文章 | `curl -X GET "http://localhost:8000/maya-sawa/paprika/articles/1" \| jq .` | `{"success": true, "data": {"id": 1, "file_path": "...", "content": "..."}}` |
| | `/paprika/articles` | POST | 創建文章 | `curl -X POST "http://localhost:8000/maya-sawa/paprika/articles" -H "Content-Type: application/json" -d '{"file_path": "test.md", "content": "# Test", "file_date": "2024-01-01T00:00:00Z"}' \| jq .` | `{"success": true, "message": "Article created successfully", "data": {...}}` |
| | `/paprika/articles/batch` | POST | 批量創建文章 | `curl -X POST "http://localhost:8000/maya-sawa/paprika/articles/batch" -H "Content-Type: application/json" -d '[{"file_path": "batch1.md", "content": "# Batch 1", "file_date": "2024-01-01T10:00:00Z"}, {"file_path": "batch2.md", "content": "# Batch 2", "file_date": "2024-01-02T11:00:00Z"}]' \| jq .` | `{"success": true, "created": 2, "skipped_duplicate": 0, "failed": 0, "message": "Batch creation completed: 2 created, 0 skipped (duplicate), 0 failed"}` |
| | `/paprika/articles/sync` | POST | 批量同步文章 | `curl -X POST "http://localhost:8000/maya-sawa/paprika/articles/sync" -H "Content-Type: application/json" -d '{"articles": [{"file_path": "sync1.md", "content": "# Sync 1", "file_date": "2024-01-01T00:00:00Z"}]}' \| jq .` | `{"success": true, "message": "Articles synced successfully", "data": {"created": 1, "updated": 0, "skipped": 0}}` |
| | `/paprika/articles/{id}` | PUT | 更新文章 | `curl -X PUT "http://localhost:8000/maya-sawa/paprika/articles/1" -H "Content-Type: application/json" -d '{"content": "# Updated", "file_date": "2024-01-01T00:00:00Z"}' \| jq .` | `{"success": true, "message": "Article updated successfully", "data": {...}}` |
| | `/paprika/articles/{id}` | DELETE | 刪除文章 | `curl -X DELETE "http://localhost:8000/maya-sawa/paprika/articles/1" \| jq .` | `{"success": true, "message": "Article deleted successfully"}` |
| **Maya-v2 對話管理** | `/maya-v2/conversations/` | GET | 對話列表 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/conversations/" \| jq .` | `{"success": true, "data": [...], "count": 2}` |
| | `/maya-v2/conversations/` | POST | 創建對話 | `curl -X POST "http://localhost:8000/maya-sawa/maya-v2/conversations/" -H "Content-Type: application/json" -d '{"conversation_type": "general", "title": "測試對話"}' \| jq .` | `{"success": true, "data": {"id": "...", "title": "測試對話", ...}}` |
| | `/maya-v2/conversations/{id}/` | GET | 單個對話 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/" \| jq .` | `{"success": true, "data": {"id": "...", "title": "...", ...}}` |
| | `/maya-v2/conversations/{id}/` | PUT | 更新對話 | `curl -X PUT "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/" -H "Content-Type: application/json" -d '{"title": "更新後的對話", "status": "active"}' \| jq .` | `{"success": true, "data": {...}}` |
| | `/maya-v2/conversations/{id}/` | DELETE | 刪除對話 | `curl -X DELETE "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/" \| jq .` | `{"success": true, "message": "Conversation deleted"}` |
| | `/maya-v2/conversations/{id}/send_message/` | POST | 發送訊息 | `curl -X POST "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/send_message/" -H "Content-Type: application/json" -d '{"content": "你好"}' \| jq .` | `{"success": true, "data": {...}}` |
| | `/maya-v2/conversations/{id}/messages/` | GET | 獲取訊息 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/conversations/550e8400-e29b-41d4-a716-446655440000/messages/" \| jq .` | `{"success": true, "data": [...], "count": 1}` |
| **Maya-v2 AI 模型管理** | `/maya-v2/ai-models/` | GET | AI 模型列表 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/ai-models/" \| jq .` | `{"success": true, "data": [...], "count": 3}` |
| | `/maya-v2/ai-models/{id}` | GET | 單個模型 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/ai-models/1" \| jq .` | `{"success": true, "data": {"id": 1, "name": "...", ...}}` |
| | `/maya-v2/available-models/` | GET | 可用模型列表 | `curl -X GET "http://localhost:8000/maya-sawa/maya-vawa/maya-v2/available-models/" \| jq .` | `{"success": true, "models": [...], "providers": {...}}` |
| | `/maya-v2/ai-providers/` | GET | AI 提供者配置 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/ai-providers/" \| jq .` | `{"success": true, "providers": {...}}` |
| | `/maya-v2/add-model/` | POST | 添加模型 | `curl -X POST "http://localhost:8000/maya-sawa/maya-v2/add-model/" \| jq .` | `{"success": true, "message": "Model added", "data": {...}}` |
| **Maya-v2 多模型問答** | `/maya-v2/ask-with-model/` | POST | 同步問答 | `curl -X POST "http://localhost:8000/maya-sawa/maya-v2/ask-with-model/" -H "Content-Type: application/json" -d '{"question": "請解釋機器學習", "model_name": "gpt-4o-mini", "sync": true}' \| jq .` | `{"success": true, "answer": "...", "model_used": "gpt-4o-mini"}` |
| | `/maya-v2/ask-with-model/` | POST | 異步問答 | `curl -X POST "http://localhost:8000/maya-sawa/maya-v2/ask-with-model/" -H "Content-Type: application/json" -d '{"question": "深度學習是什麼", "model_name": "gpt-4o-mini", "sync": false}' \| jq .` | `{"success": true, "task_id": "...", "status": "queued"}` |
| | `/maya-v2/task-status/{id}` | GET | 任務狀態 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/task-status/task-123" \| jq .` | `{"success": true, "status": "completed", "result": {...}}` |
| | `/maya-v2/qa/chat-history/{session_id}` | GET | 聊天歷史 | `curl -X GET "http://localhost:8000/maya-sawa/maya-v2/qa/chat-history/qa-12345678" \| jq .` | `{"success": true, "history": [...], "session_id": "qa-12345678"}` |
| **Legacy 聊天歷史** | `/maya-sawa/qa/chat-history/{user_id}` | GET | 舊版聊天歷史 | `curl -X GET "http://localhost:8000/maya-sawa/maya-sawa/qa/chat-history/test_user" \| jq .` | `{"success": true, "history": [...], "user_id": "test_user"}` |

### 測試腳本

#### 創建完整的測試腳本

```bash
#!/bin/bash
# Maya Sawa v1 完整 API 測試腳本

echo "=== Maya Sawa v1 完整 API 測試 ==="

BASE_URL="http://localhost:8000/maya-sawa"

# 1. 根端點測試
echo "1. 根端點測試"
curl -s -X GET "${BASE_URL}/" | jq '.message'

# 2. Paprika 健康檢查
echo "2. Paprika 健康檢查"
curl -s -X GET "${BASE_URL}/paprika/up" | jq '.status'

# 3. 創建測試文章
echo "3. 創建測試文章"
ARTICLE_RESPONSE=$(curl -s -X POST "${BASE_URL}/paprika/articles" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "test/api-test.md",
    "content": "# API 測試文章\n這是一篇用於 API 測試的文章。",
    "file_date": "'$(date -I)'T00:00:00Z"
  }')

echo "文章創建結果: $(echo $ARTICLE_RESPONSE | jq '.success')"

# 3.5. 批量創建測試文章
echo "3.5. 批量創建測試文章"
BATCH_RESPONSE=$(curl -s -X POST "${BASE_URL}/paprika/articles/batch" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "file_path": "test/batch1.md",
      "content": "# 批量測試文章1\n這是第一篇批量測試文章。",
      "file_date": "'$(date -I)'T10:00:00Z"
    },
    {
      "file_path": "test/batch2.md",
      "content": "# 批量測試文章2\n這是第二篇批量測試文章。",
      "file_date": "'$(date -I)'T11:00:00Z"
    },
    {
      "file_path": "test/api-test.md",
      "content": "# 重複測試\n這篇文章會被跳過因為 file_path 重複。",
      "file_date": "'$(date -I)'T12:00:00Z"
    }
  ]')

echo "批量創建結果: $(echo $BATCH_RESPONSE | jq '.message')"

# 4. QA 查詢測試
echo "4. QA 系統測試"
QA_RESPONSE=$(curl -s -X POST "${BASE_URL}/qa/query" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "測試問題",
    "user_id": "api_test",
    "language": "chinese"
  }')

echo "QA 查詢結果: $(echo $QA_RESPONSE | jq '.success')"

# 5. AI 模型測試
echo "5. AI 模型列表"
curl -s -X GET "${BASE_URL}/maya-v2/available-models/" | jq '.models | length'

echo "=== 測試完成 ==="
```

### 測試腳本

#### 創建完整的測試腳本

```bash
#!/bin/bash
# Maya Sawa v1 API 測試腳本

# 直接使用具體 URL，無需變數

echo "=== Maya Sawa v1 API 測試 ==="

# 1. 健康檢查
echo "1. 根端點測試"
curl -s -X GET "http://localhost:8000/maya-sawa/" | jq '.message'

# 2. Paprika 健康檢查
echo "2. Paprika 健康檢查"
curl -s -X GET "http://localhost:8000/maya-sawa/paprika/up" | jq '.status'

# 3. 創建測試文章
echo "3. 創建測試文章"
ARTICLE_RESPONSE=$(curl -s -X POST "http://localhost:8000/maya-sawa/paprika/articles" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "test/api-test.md",
    "content": "# API 測試文章\n這是一篇用於 API 測試的文章。",
    "file_date": "'$(date -I)'T00:00:00Z"
  }')

echo "文章創建結果: $(echo $ARTICLE_RESPONSE | jq '.success')"

# 3.5. 批量創建測試文章
echo "3.5. 批量創建測試文章"
BATCH_RESPONSE=$(curl -s -X POST "http://localhost:8000/maya-sawa/paprika/articles/batch" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "file_path": "test/batch1.md",
      "content": "# 批量測試文章1\n這是第一篇批量測試文章。",
      "file_date": "'$(date -I)'T10:00:00Z"
    },
    {
      "file_path": "test/batch2.md",
      "content": "# 批量測試文章2\n這是第二篇批量測試文章。",
      "file_date": "'$(date -I)'T11:00:00Z"
    },
    {
      "file_path": "test/api-test.md",
      "content": "# 重複測試\n這篇文章會被跳過因為 file_path 重複。",
      "file_date": "'$(date -I)'T12:00:00Z"
    }
  ]')

echo "批量創建結果: $(echo $BATCH_RESPONSE | jq '.message')"

# 4. QA 查詢測試
echo "4. QA 系統測試"
QA_RESPONSE=$(curl -s -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "測試問題",
    "user_id": "api_test",
    "language": "chinese"
  }')

echo "QA 查詢結果: $(echo $QA_RESPONSE | jq '.success')"

# 5. AI 模型測試
echo "5. AI 模型列表"
curl -s -X GET "http://localhost:8000/maya-sawa/maya-v2/available-models/" | jq '.models | length'

echo "=== 測試完成 ==="
```

## 測試

### 本地啟動

```bash
cd maya-sawa-v1
poetry install
poetry run uvicorn maya_sawa.main:app --reload --host 0.0.0.0 --port 8000
```

### API 文檔

啟動後訪問：
- Swagger UI: http://localhost:8000/maya-sawa/docs
- ReDoc: http://localhost:8000/maya-sawa/redoc

## 故障排除

### 常見問題

1. **SQLAlchemy metadata 錯誤**
   - 原因：`metadata` 是 SQLAlchemy 保留字
   - 解決：使用 `extra_data` 作為 Python 屬性名

2. **數據庫連接失敗**
   - 檢查環境變數是否正確設置
   - 確認數據庫服務是否運行

3. **Celery 任務不執行**
   - 確認 broker (RabbitMQ/Redis) 是否運行
   - 檢查 worker 是否已啟動

## 新增功能測試

### 文本轉向量 API

#### 基本測試
```bash
curl -X POST "http://localhost:8000/maya-sawa/qa/convert-to-vector" \
  -H "Content-Type: application/json" \
  -d '{"content": "這是一段測試文本"}' | jq .
```

**預期結果：**
```json
{
  "success": true,
  "vector": [0.123, -0.456, 0.789, ...],
  "dimensions": 1536,
  "content_length": 8,
  "model": "text-embedding-3-small",
  "message": "Successfully converted content to 1536-dimensional vector"
}
```

#### 功能特點
- ✅ **服務層設計**：使用 EmbeddingService 統一管理向量生成
- ✅ **代碼共用**：與 QA 系統、搜索功能共用相同的向量生成邏輯
- ✅ **向量一致性**：確保所有模組使用相同的嵌入模型
- ✅ **輸入驗證**：檢查空內容，返回友好錯誤信息

#### 使用場景
1. **前端客戶端**：生成向量用於本地向量搜索或緩存
2. **第三方集成**：外部系統需要與 Maya Sawa 相同格式的向量
3. **測試調試**：驗證向量生成功能是否正常
4. **離線處理**：預先生成向量數據用於批量處理

## 版本歷史

- **v0.3.0** - 添加向量轉換 API 和服務層重構
- **v0.2.0** - 整合 maya-sawa-v2 (Django) 和 paprika (Laravel)
- **v0.1.0** - 原始 FastAPI 問答系統

---

## 本地啟動

```bash
cd maya-sawa
poetry install
poetry run maya            # 預設 port 8000
poetry run maya --port 8001  # 換 port（若 8000 被佔用）
```

等同於：
```bash
poetry run uvicorn maya_sawa.main:app --reload --log-level debug --host 0.0.0.0 --port 8000
```

### 連接池測試
```bash
python scripts/test_connection_pool.py
python scripts/monitor_connections.py
```

## AI Token Usage Sync（Windows）

Windows 本地 `ccusage` 資料透過 Task Scheduler 同步到 TY Multiverse DB，每 3 小時一次。

```powershell
# 安裝/更新排程工作（3 小時間隔）
cd F:\002-workspace\ty-multiverse\ty-multiverse-backend
.\scripts\install_windows_ccusage_sync_task.ps1 -IntervalMinutes 180

# 查看排程狀態
schtasks /Query /TN "TY Multiverse AI Usage Sync" /FO LIST /V
```

## API 測試範例

```bash
# 同步文章
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-from-api" \
  -H "Content-Type: application/json" -d '{}'

# 強制本地 Embedding
curl -X POST "http://localhost:8000/maya-sawa/qa/sync-articles" \
  -H "Content-Type: application/json" -d '{}'

# QA 查詢（英文）
curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"Who is Sorane?","user_id":"dev","language":"english","name":"Maya","frontend_source":"/tymultiverse"}'

# QA 查詢（中文）
curl -X POST "http://localhost:8000/maya-sawa/qa/query" \
  -H "Content-Type: application/json" \
  -d '{"text":"誰是Sorane?","user_id":"dev","language":"chinese","name":"Maya","frontend_source":"/tymultiverse"}'

# 對話歷史
curl -X GET "http://localhost:8000/maya-sawa/qa/chat-history/dev"

# 市場數據（需 cache）
curl http://localhost:8000/maya-sawa/market/internal/usage
```

## Docker 建置

```bash
docker build -t papakao/maya-sawa:latest .
```

## IBKR 正確登入紀錄

當你要看 `Market Overview` 裡的 IBKR 資料時，請用這個流程：

```bash
ssh -L 5000:127.0.0.1:15000 oke-node kubectl port-forward deployment/ibkr-gw 15000:5000 -n default --address 127.0.0.1
```

然後在本機瀏覽器開：

```text
https://localhost:5000/
```

如果瀏覽器跳自簽憑證警告，就輸入 `thisisunsafe`。  
如果看到 `ERR_CONNECTION_REFUSED`，通常是本機隧道沒有建立成功，不是 IBKR gateway 本身掛掉。

補充：

- OKE 內部實際服務仍是 `https://ibkr-gw:5000`
- `https://localhost:5000/` 只是在本機做登入用的臨時轉發
- 登入完成後，session 會留在 pod 記憶體，前端之後只讀 Redis cache
