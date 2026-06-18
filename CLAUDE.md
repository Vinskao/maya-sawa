# Maya Sawa - 本地開發指南

## 工作流指南 ⚠️

**直接在 `main` 上改。不建立特性分支。**

- 本專案只用 `main`
- 改動完測通後直接 `git push origin main`（用 SSH URL，HTTPS token 無效）
- 分岔分支會導致合併地獄（已有經驗教訓）

---

## 快速開始

```bash
cd maya-sawa
poetry install
poetry run maya  # 或 poetry run maya --port 8001 (預設 8000)
```

訪問 API 文檔：`http://localhost:8000/maya-sawa/docs`

---

## Shioaji 本地登入問題

### 症狀
啟動時 Redis cache 永遠無資料（`USAGE`/`PORTFOLIO` 無法拿到），endpoint 回 503。

### 根因
**家用 IP 白名單限制**：永豐 Shioaji 驗證登入 IP，未在白名單拒絕。
```
shioaji.BadRequestError: StatusCode: 400, Detail: ip: 1.163.102.248 not allow.
```

K8s pod 正常是因為叢集 IP 已在永豐白名單。

### 三種解決方案

#### 方案 1：向永豐添加家用 IP（最快，但家用 IP 會變動）
- 訪問永豐 Shioaji 開發者後台，找到使用中的 API key
- 將目前外網 IP（`curl https://icanhazip.com`）加進白名單
- 家用 DHCP IP 每次重啟會變，需要重複此步驟

#### 方案 2：共用 K8s Redis cache（推薦如果常在本地測試）
```bash
# 在另一個終端
kubectl port-forward svc/redis 6379:6379 -n default

# 本地 .env.development 改為
REDIS_HOST=127.0.0.1
REDIS_CUSTOM_PORT=6379
REDIS_PASSWORD=<K8s redis password>
SHIOAJI_REDIS_DB=0
SHIOAJI_REDIS_CACHE_PREFIX=maya-sawa:market  # 確保與 K8s 一致
```
這樣本地直接讀 K8s 已填好的 cache，不需要登入。

#### 方案 3：使用平台分流 key（推薦長期方案）
修改 `maya_sawa/services/shioaji_market.py:206` 的 `_login()` 為：
```python
@staticmethod
def _login() -> Any:
    import shioaji as sj
    import platform
    
    # Platform-specific key selection
    if platform.system() == "Windows":
        api_key = os.getenv("SHIOAJI_LOCAL2_API_KEY") or os.getenv("SHIOAJI_API_KEY")
        secret_key = os.getenv("SHIOAJI_LOCAL2_SECRET_KEY") or os.getenv("SHIOAJI_SECRET_KEY")
    elif platform.system() == "Darwin":  # macOS
        api_key = os.getenv("SHIOAJI_LOCAL1_API_KEY") or os.getenv("SHIOAJI_LOCAL1_SECRET_KEY")
        secret_key = os.getenv("SHIOAJI_LOCAL1_SECRET_KEY") or os.getenv("SHIOAJI_SECRET_KEY")
    else:  # Linux (K8s)
        api_key = os.getenv("SHIOAJI_API_KEY")
        secret_key = os.getenv("SHIOAJI_SECRET_KEY")
    
    api = sj.Shioaji(simulation=os.getenv("SHIOAJI_SIMULATION", "false").lower() == "true")
    api.login(api_key=api_key, secret_key=secret_key, fetch_contract=True)
    return ReadOnlyShioajiClient(api, share_unit=sj.Unit.Share)
```

`.env` 已有 `SHIOAJI_LOCAL1_*` (macOS) 和 `SHIOAJI_LOCAL2_*` (Windows)，永豐後台對這些 key 已設不同 IP 白名單。

---

## 環境檔案

- `.env` — 預設配置（被 `.env.development` 覆蓋）
- `.env.development` — 本地開發用（git ignore）
- `.env.example` — 配置範本

若需要臨時改設定，編輯 `.env.development`（優先度最高）。

---

## 常見問題排查

### 啟動時 port 8000 被占用
```bash
# 檢查佔用程序
Get-NetTCPConnection -LocalPort 8000  # Windows PowerShell

# 使用別的 port
poetry run maya --port 8001
```

### Redis 連線失敗
```bash
# 確認本地 Redis 運行
redis-cli ping

# 或
poetry run python -c "import redis; r=redis.Redis(host='127.0.0.1',port=6379,password='RedisPassword123'); print(r.ping())"
```

### Shioaji 模組找不到
```bash
poetry install  # 重新安裝依賴
```

---

## 開發工作流

### 測試單一功能
```bash
# 測試 Shioaji 登入是否正常
poetry run python -c "
from maya_sawa.services.shioaji_market import ShioajiMarketService
svc = ShioajiMarketService()
api = svc._login()
print('登入成功', api.usage())
"

# 檢查 Redis cache 內容
poetry run python -c "
import redis
r = redis.Redis(host='127.0.0.1', port=6379, password='RedisPassword123', decode_responses=True)
print(r.keys('maya-sawa:market:*'))
"
```

### 調試背景 refresh loop
背景 refresh 會靜默吃掉例外。若要看真正的錯誤：
1. 改 `shioaji_market.py:158` 的 `_refresh_payload()` 加 log
2. 或直接手動呼叫 `svc._login()` 讓例外浮出

---

## API 測試快速命令

```bash
# 根端點
curl http://localhost:8000/maya-sawa/

# QA 查詢
curl -X POST http://localhost:8000/maya-sawa/qa/query \
  -H "Content-Type: application/json" \
  -d '{"text":"測試","user_id":"dev"}'

# Paprika 文章列表
curl http://localhost:8000/maya-sawa/paprika/articles

# 市場數據（會失敗如果無 cache）
curl http://localhost:8000/maya-sawa/market/internal/usage
```

詳見 [AGENTS.md](AGENTS.md) 的完整 API 測試表。

---

## 分支與部署

- **本地開發**：使用方案 1 或 3（平台分流 key）
- **K8s pod**：使用通用 `SHIOAJI_API_KEY`（叢集 IP 已白名單）
- **CI/CD**：確保 `.env.development` 不提交（git ignore）
