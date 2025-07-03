# 同步控制指南

## 🚨 立即停止同步任務

如果你發現系統一直在運行同步任務，可以使用以下方法停止：

### 方法 1: API 端點
```bash
curl -X POST "http://localhost:8000/qa/stop-sync"
```

### 方法 2: 腳本停止
```bash
python scripts/stop_sync.py
```

### 方法 3: 重啟應用程式
```bash
# 按 Ctrl+C 停止 FastAPI
# 然後重新啟動
uvicorn maya_sawa.main:app --reload
```

## 🔧 配置控制

### 環境變數設置

在 `.env` 文件中設置以下變數來控制同步行為：

```bash
# 啟動時同步（推薦開啟）
ENABLE_AUTO_SYNC_ON_STARTUP=true
ENABLE_PEOPLE_WEAPONS_SYNC=true

# 定期同步（推薦關閉，避免無限循環）
ENABLE_PERIODIC_SYNC=false
ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC=false
```

### 手動同步

如果需要手動同步數據：

```bash
# 同步人員和武器數據（默認60秒限制）
curl -X POST "http://localhost:8000/qa/sync-people-weapons"

# 同步人員和武器數據（自定義時間限制）
curl -X POST "http://localhost:8000/qa/sync-people-weapons" \
  -H "Content-Type: application/json" \
  -d '{"max_time_seconds": 30}'

# 查看同步配置
curl -X GET "http://localhost:8000/qa/sync-config"
```

### 時間限制功能

新的同步系統支持時間限制，避免無限運行：

- **默認限制**: 60秒
- **可自定義**: 通過 API 參數設置
- **進度追蹤**: 每10條記錄或每10秒顯示進度
- **智能分配**: 60%時間處理人員數據，40%時間處理武器數據

## 📊 檢查同步狀態

### 查看日誌
```bash
# 查看應用程式日誌
tail -f logs/app.log
```

### 檢查數據庫
```sql
-- 檢查人員數據
SELECT COUNT(*) FROM people;

-- 檢查武器數據  
SELECT COUNT(*) FROM weapon;

-- 檢查是否有 embedding
SELECT COUNT(*) FROM people WHERE embedding IS NOT NULL;
SELECT COUNT(*) FROM weapon WHERE embedding IS NOT NULL;
```

## ⚠️ 注意事項

1. **定期同步默認關閉**: 避免系統一直運行同步任務
2. **啟動時同步**: 只在應用程式啟動時執行一次
3. **手動控制**: 可以通過 API 或腳本手動控制同步
4. **監控日誌**: 注意查看日誌中的同步狀態

## 🔄 重新啟用定期同步

如果需要定期同步，請謹慎設置：

```bash
# 在 .env 文件中設置
ENABLE_PERIODIC_SYNC=true
ENABLE_PEOPLE_WEAPONS_PERIODIC_SYNC=true

# 設置同步間隔（建議不要太頻繁）
SYNC_INTERVAL_DAYS=7  # 每週同步一次
SYNC_HOUR=3           # 凌晨3點
SYNC_MINUTE=0
``` 