# Binance 資產與報價（規劃，尚未實作）

目標：像台股（永豐）與海外（IBKR）一樣，在持股頁看到 Binance 的資產、即時報價與日線圖。2026-10-28 規劃。

## 只讀，不交易

- 只用 **唯讀 API key**：在 Binance 建立 key 時只勾「Enable Reading」，不開交易、不開提領、不開萬向劃轉。即使 key 外洩，也動不了資產。
- **IP 白名單**：key 綁定 OKE 對外 IP，其他地方拿到也不能用。
- key 由使用者自己在 Binance 建立（agent 不建立憑證），存進 Jenkins credential，部署時注入 k8s secret（環境變數 `BINANCE_API_KEY`、`BINANCE_API_SECRET`），不進 repo、log 或對話。

## 要接的 API

| 用途 | 端點 | 需要 key |
|---|---|---|
| 現貨餘額 | `GET /api/v3/account`（HMAC-SHA256 簽名，帶 `timestamp`、`recvWindow`） | ✅ |
| 各錢包總覽（現貨、資金、理財…） | `GET /sapi/v1/asset/wallet/balance` | ✅ |
| 活期理財持倉 | `GET /sapi/v1/simple-earn/flexible/position` | ✅ |
| 即時報價 | `GET /api/v3/ticker/price`、`/api/v3/ticker/24hr` | ❌ 公開 |
| 日線（K 線） | `GET /api/v3/klines?interval=1d` | ❌ 公開 |

合約帳戶（`/fapi`）先不接，等需要再說。

## 怎麼跟現有系統對齊

- **持股**：`/market/portfolio`（`_portfolio_with_ibkr`）旁邊加一個 Binance 來源，作法跟 IBKR 一樣：失敗不影響台股持股、owner 才看得到（`require_manage_users_request`）、寫進 `portfolio_history` 快照累積時間序列。
- **計價**：幣價以 USDT 計，再用既有的 `CBC_USD_TWD` 匯率換成台幣，跟海外持股同一套。
- **報價與圖表**：新增市場 `CRYPTO`（例如 `BTC`、`ETH`），日線由公開 K 線收集進現有的歷史資料表；前端行情圖（K 線、成交量、時間範圍）直接沿用。這部分是公開資料，可以加進公開 API 分頁。
- **新程式位置**：`maya_sawa/services/binance_market.py`（簽名、呼叫、轉換）、測試 `tests/test_binance_market.py`，用去掉個資的真實回應當 fixture（依 AGENTS.md 的 TDD 規則）。

## 開工前要先確認

1. **連線**：maya-sawa 跑在 OCI `ap-singapore-2`。Binance 對部分地區會回 HTTP 451（限制地區），要先從 pod 打一次公開的 `GET https://api.binance.com/api/v3/ping` 確認；不通的話要另想辦法（例如改由其他區域的節點代抓），不能用代理繞過 Binance 的地區限制。
2. **用量**：Binance 以權重限流（每分鐘 6000 權重）；餘額每 5 分鐘、報價每分鐘抓一次，遠低於上限。
3. **使用者要做的**：建立唯讀 key、設 IP 白名單、把 key 存進 Jenkins。

## 分階段

1. 公開報價與日線（不需要 key）：先讓 `BTC`、`ETH` 出現在行情圖。
2. 唯讀 key 接餘額，併進持股頁與持股歷史。
3. 視需要：理財、合約、成本與損益（Binance 的成交紀錄要逐交易對查，較耗權重，最後再做）。
