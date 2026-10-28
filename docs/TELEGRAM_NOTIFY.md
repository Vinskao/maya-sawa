# Telegram 通知（只通知本人）

排程（Claude 雲端 routine）寫完資料、或卡在需要登入時，透過 maya-sawa 發 Telegram 訊息給本人。

## 運作方式
- 排程結束時呼叫 `POST /maya-sawa/market/notify`，帶 `X-Market-Agent-Key`（和寫分析同一把限縮金鑰，不另開權限）。
- body：`{"kind": "update" | "attention", "title": "...", "body": "..."}`
  - `update`：資料已存好（✅）。
  - `attention`：需要你處理，例如要登入、被擋、連續失敗（⚠️ 需要處理）。
- 後端用 `TELEGRAM_BOT_TOKEN` 呼叫 `sendMessage`，只送到 `TELEGRAM_CHAT_ID`。單向發送，沒有 webhook，也不讀任何訊息。
- 沒設定 token 或 chat id 時，介面回 `{"sent": false, "reason": "not configured"}`，排程不會失敗。
- 訊息內形似 token／金鑰的字串會被遮蔽，所以不要在 `body` 放憑證；`attention` 只寫「哪個排程、卡在哪」。

## 一次性設定
1. 手機 Telegram 對 `@BotFather` 傳 `/newbot`，取得 token。
2. Jenkins 新增兩個 Secret text：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`（在資料夾 `vinskao`，與 `BLS_API_KEY` 同處）。
3. 對機器人傳一句話，再在本機執行 `scripts/telegram_chat_id.py`（token 由環境變數帶入）取得 chat id。
4. 重新部署：`Configure Telegram Notifications` 階段建立 k8s secret `telegram-notify`；缺憑證只會標 UNSTABLE，不擋部署。

## 排程怎麼用
每個排程在最後送**一則**彙整訊息（不是每檔一則，避免手機連續震動）：
- 成功：`update`，標題寫排程名稱，內文列更新了哪些標的／節點。
- 登入或權限問題：`attention`，寫哪個排程、哪一步。
- **代號自動補名稱（2026-10-28）：** 排程常只寫代號（`3008 賣→中立`）。`POST /market/notify` 轉發前用儀表板標的清單（持倉、自訂、AI 觀察）把代號補成「代號 名稱」（`3008 大立光 賣→中立`），Telegram 與網站鈴鐺都一樣。已寫名稱的不重複加；不在清單的代號、數字裡的數字（`3008.5`、日期、`2330天`）不動；同一代號對到兩個不同名稱（東京 6857 與台灣 6857）時不補。名稱讀取失敗就照原文送出。
測試：`tests/test_telegram_notify.py`、`tests/test_market_ai_analysis.py::test_notify_endpoint_requires_agent_key_and_relays`。

## 排程 token 用量記錄（費用第二軸）
- 排程（Claude Code 雲端 routine）可匯出 OpenTelemetry 指標：`POST /maya-sawa/otel/v1/metrics`（OTLP http/json）。
- 驗證：排程的網路代理會自動加上 `X-Market-Agent-Key`（和寫分析同一把），所以排程環境**不需要放任何新密鑰**。通過後用量以 `claude-routine` 記入 `/ai-usage`；本機 Claude Code 仍是 `claude`（需 ingest token）。
- 排程要設的環境變數（非機密）：`CLAUDE_CODE_ENABLE_TELEMETRY=1`、`OTEL_METRICS_EXPORTER=otlp`、`OTEL_EXPORTER_OTLP_PROTOCOL=http/json`、`OTEL_EXPORTER_OTLP_ENDPOINT=https://peoplesystem.tatdvsonorth.com/maya-sawa/otel`。
- 首頁報酬率圖的第二軸只加總 `claude-routine`。
- 測試：`tests/test_otel_usage.py`。

## 通知歷史（網站鈴鐺）與頻道貼文清單（2026-10-27）

**通知歷史。** `POST /market/notify` 除了送 Telegram，也會把同一則（已遮蔽疑似金鑰的字串）存進 `maya_sawa_market_notification`，
只保留最新 500 則。即使 Telegram 沒設定，也會存；存失敗只記 log，不影響 Telegram。
`GET /market/notifications?limit=100`（`limit` 最多 200）回傳最新在前的清單，需要擁有者角色（同 `/market/auth-status`），
網站導覽列的鈴鐺用它顯示「全部／未讀」，已讀的訊息仍留在清單裡可以重讀。已讀狀態存在瀏覽器 localStorage，
不會寫回後端。

**頻道貼文出現在研究報告清單。** `list_reports` 會附上每個 Telegram 頻道最新 10 則「已有主張」的貼文
（`COLLECTOR_LISTED_PER_CHANNEL`）；沒有主張的貼文（廣告、閒聊）不列，更舊的貼文仍在資料庫，主張照常供分析引用。
這些貼文沒有 PDF，卡片改顯示「頻道貼文」與原貼文連結。

## 排程用量自我回報（2026-10-28，取代 OpenTelemetry 路徑）

首頁報酬率圖的「費用線」讀 `claude-routine` 的用量。先前用環境變數讓雲端 Claude Code 匯出 OpenTelemetry，實測從沒有資料進來，改成排程自己回報：

1. 排程最後一步執行倉庫裡的 `maya_sawa/public_scripts/report_routine_usage.py "<標籤>"`。雲端工作階段會把每則訊息的用量寫進
   `~/.claude/projects/*/<session>.jsonl`，腳本把每個模型的 input / output / cache 建立 / cache 讀取加總（同一則訊息只算一次）。
2. 腳本 POST 到 `POST /market/routine-usage`；寫入 key 由雲端環境的代理自動加，腳本不碰金鑰、不輸出對話內容。
3. 後端用 `services/routine_cost.py` 估算費用（Claude 沒有公開的逐筆價格，費率由本站已記錄的 Claude Code 成本回推：Opus 5.5 約輸入每百萬 $1.46、
   Sonnet 5.5 約 $1.18，輸出 5 倍、cache 建立 1.25 倍、cache 讀取 0.1 倍；是估算），再轉給用量服務（`PUBLIC_TYMB_URL` / `AI_USAGE_INGEST_TOKEN`），記為 `claude-routine`。
4. 端點如實回報下游有沒有收下（`{"recorded": n, "failed": {...}}`），腳本據此印出「usage reported」或「usage not recorded」。

要點：
- **腳本必須在排程的倉庫目錄裡執行**。排程要在 `sources` 附上 `Vinskao/maya-sawa`。從網路下載再 `| python3` 會被雲端的安全分類器擋下（「從外部下載並執行程式碼」），
  所以 `GET /market/routine-usage.py` 雖然存在，排程不該用它。
- 腳本放在套件目錄 `maya_sawa/public_scripts/`，不能放 `scripts/`：Docker 映像用 `.dockerignore` 排除了 `scripts/`。
- 每週文章排程沒有寫入金鑰（也不該有），所以它的用量不會被記錄。
- 2026-10-28 實測：一次性測試排程回報成功，資料庫出現 `claude-routine`、`claude-sonnet-5-5`、約 66k token、$0.024。
