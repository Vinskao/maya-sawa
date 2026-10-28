# Binance 資產與報價（第一、二、三階段已完成）

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

## 第一階段現況（2026-10-28 完成）

- `maya_sawa/services/binance_market.py`：背景每 60 秒檢查一次；報價（`/api/v3/ticker/24hr`，一次批次查全部幣）每分鐘、日線（`/api/v3/klines`）每 6 小時。第一次回補 1000 天，之後每次只抓最近 5 根。
- 資料存進 IBKR 同一張表 `maya_sawa_ibkr_datasets`（`market=CRYPTO`、`conid=0`，kind 為 `quote`、`daily`、`history_raw`）。API 只讀資料庫，不會打 Binance。
- 失敗（含 HTTP 451／403 地區限制）記成 `unavailable`，原因只存分類，不存原始錯誤文字；上次成功的資料保留。失敗後最多一小時內重試。
- 公開端點：`/market/dashboard` 新增 `crypto` 清單；`/market/dashboard/overseas/{code}?market=CRYPTO` 回日線、報價與資料狀態（未收集的幣回 404）。AI 分析可用 `productType=crypto`、代碼 `BTC-CRYPTO`。
- 前端：持股頁新增「加密貨幣 · Binance 現貨（USDT）」清單，詳情只開價格、研究、AI 分析分頁；成交量單位是幣本身，不疊加本益比和券商目標價。
- 環境變數：`BINANCE_SYMBOLS`（預設 `BTC,ETH`）、`BINANCE_MARKET_ENABLED`（預設 `true`）、`BINANCE_API_BASE`（預設 `https://api.binance.com`）。
- 測試：`tests/test_binance_market.py`、`tests/test_market_dashboard.py`（crypto 部分）；前端 `tests/market/priceChart.test.ts`、`overseasResearch.test.ts`、`instrumentIdentity.test.ts`。
- 唯讀 key 已存進 Jenkins credential `BINANCE_API_KEY`、`BINANCE_API_SECRET`（第二階段才接進部署）。尚未設定 IP 白名單。
- 連線：2026-10-28 部署後確認 pod（OCI 新加坡）連得到 Binance，`coverage.quote` 與 `coverage.history_raw` 都是 `ok`。日後若出現 `status=unavailable`、`reason=BinanceRegionRestricted`，就是被地區限制擋了。

## 第二階段現況（2026-10-28 完成，待部署驗證）

- `maya_sawa/services/binance_account.py`：`BINANCE_API_KEY` 與 `BINANCE_API_SECRET` 都有值才啟動；每 5 分鐘讀一次：
  - `GET /api/v3/account?omitZeroBalances=true`：現貨，`LD*` 資產視為 Simple Earn 活期（例如 `LDUSDT` 算 USDT／Earn）。
  - `POST /sapi/v1/asset/get-funding-asset`：資金錢包。
  - `GET /sapi/v1/asset/wallet/balance?quoteAsset=USDT`：各錢包 USDT 總額，總資產以它為準；它和逐項持倉的差額記為 `otherWallets`（例如定期理財、合約）。
  - `GET /api/v3/ticker/price`（公開）：USDT 價格，沒有 USDT 交易對的走 BTC 換算；穩定幣算 1；都沒有的列進 `unpriced`。
  - 匯率：`USD_TWD_RATE` 覆寫 → IBKR 用的 open.er-api → 31.5 備援（`fxSource` 記來源）。USDT 視為 1 美元。
- 簽章：HMAC-SHA256，先取 `/api/v3/time` 校正時鐘，`recvWindow=10000`。錯誤 log 只留 HTTP 狀態與 Binance 錯誤碼，不留網址（含簽章）。
- 快照存在 `maya_sawa_ibkr_datasets`（`code=BINANCE`、`market=PRIVATE`、kind `portfolio`，每 15 分鐘一筆歷史），沒有公開 API；不存 uid、權限等帳戶識別。
- `/market/portfolio`（只有 owner）：`totalAssetsEstimated` 加上 Binance 台幣總額，新增 `regions.crypto` 與 `binance` 區塊；現金與損益不動（穩定幣不算銀行現金，成本與損益是第三階段）。Binance 讀取失敗不影響台股持股；持股歷史快照自動包含。
- 前端：總資產下方的區域小字變成「台 · 外 · 幣」（`src/scripts/market/portfolioRegions.ts`），總資產 tooltip 多一段 `+ Binance N`。海外與合併圓餅圖目前是暫停狀態，所以沒有另外加加密貨幣圓餅圖。
- Jenkins：`Configure Binance Key` stage 把兩個 credential 寫進 k8s secret `binance-credentials`（缺少時 stage 標 UNSTABLE，不擋部署），deployment 以 `optional: true` 注入。
- IP 白名單：尚未設定。唯讀 key 不綁 IP 也能用；之後查到 OKE 對外 IP 再到 Binance 設。

## 第三階段現況（2026-10-28 完成，待部署驗證）

- `maya_sawa/services/binance_costs.py`：移動加權平均成本。來源：
  - 現貨成交 `GET /api/v3/myTrades`（weight 20），只查持有中非穩定幣、以 USDT／FDUSD／USDC 計價且存在的交易對。依 `fromId` 增量抓，每頁 1000 筆，每次最多 20 頁。
  - 閃兌 `GET /sapi/v1/convert/tradeFlow`（weight 3000），第一次回補 365 天（每次最多 30 天一段），之後從上次結束時間接著抓；每段存一次進度。
  - 每小時更新一次歷史，存在 `maya_sawa_ibkr_datasets`（`code=BINANCE`、`market=PRIVATE`、kind `trades:<pair>` 與 `converts`，period `all`）。成本每 5 分鐘隨餘額重新計算。
- 手續費：扣在幣本身就減少數量；扣在計價幣就加進成本（買）或扣掉賣出金額（賣）；扣 BNB 的不計入成本。
- **沒有成本的部分不算損益**：外部轉入、理財利息、法幣直接買、幣換幣閃兌。快照的 `costBasis.<asset>` 列出持有數量、有成本數量（`coveredQuantity`）、無成本數量（`uncoveredQuantity`）、平均成本、未實現與已實現損益。沒有任何成本紀錄的幣，平均成本與損益是 `null`，不會當成零。
- 已實現損益只算持有中的幣；已經全部賣光的幣不在追蹤範圍。
- `/market/portfolio`：`totalPnl` 加上有成本部分的未實現損益（台幣），`regions.crypto.totalPnl` 同步。前端損益 tooltip 多一行「加密貨幣（有成本者）」。
- 成交或閃兌紀錄讀取失敗時，用上次存的歷史計算，餘額照常更新。

## 分階段

1. ✅ 公開報價與日線（不需要 key）：`BTC`、`ETH` 出現在行情圖。
2. ✅ 唯讀 key 接餘額，併進持股頁與持股歷史。
3. ✅ 成本與損益（現貨成交＋閃兌）。合約（`/fapi`）、法幣買幣紀錄、幣換幣閃兌的成本仍未接。
