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
