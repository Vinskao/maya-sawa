# 台灣 VIX 與美國 VIX（總經頁最上方，即時更新）

2026-11-16。總經頁最上方、場內／場外利率圖之上，左邊「台指選擇權波動率指數（台灣 VIX）」、右邊「美國 VIX」。每張圖是已存的每日收盤線，加上今天的即時值當最新一點，圖上方一行顯示即時值、漲跌、當日開高低與時間，約每分鐘更新。

```mermaid
flowchart TD
    A[TAIFEX 每月日收盤檔 log2data/YYYYMMnew.txt] -->|每 6 小時，保留並延伸已存歷史| M[總經快取序列 TW_VIX]
    Y[Yahoo ^VIX 日線] -->|既有流程| U[總經序列 US_VIX]
    M --> S[GET /market/dashboard/macro]
    U --> S
    L1[TAIFEX 行情服務 TAIWANVIX] --> C[VolatilityLive 快取 30 秒]
    L2[Yahoo ^VIX 一分鐘線] --> C
    C --> V[GET /market/dashboard/volatility/live]
    K[Cboe 每日結算價 CSV] -->|每 6 小時，補齊近 45 天| FU[總經快取序列 VIX_FUT_FRONT：近月期貨結算價]
    FU --> S
    L3[Yahoo VIXY 含盤前盤後] --> C
    S --> F[前端：每日收盤線]
    V -->|每 60 秒，頁面可見時| F
    F --> P[今天的即時值接在線尾＋讀數列]
```

## 資料來源

| 項目 | 來源 | 備註 |
|---|---|---|
| 台灣 VIX 日收盤 | 期交所每月檔（Big5 文字），取「收盤前 1 分鐘均值」 | 網站只留約 4 個月，所以歷史存在總經快取並逐次延伸 |
| 台灣 VIX 即時 | 期交所行情服務 `mis.taifex.com.tw/futures/api/getQuoteDetail`，`SymbolID: TAIWANVIX` | 約 15 秒更新；含開高低與前收 |
| 美國 VIX 日收盤 | 既有 `US_VIX`（Yahoo） | 每 5 小時 |
| 美國 VIX 即時 | Yahoo `^VIX` 一分鐘線 meta | 休市時回最近一次收盤 |
| VIX 近月期貨（日） | Cboe 每日結算價 CSV（`/us/futures/market_statistics/settlement/csv?dt=`） | 取到期日最近的標準月合約（`VX/X6`），週合約不算；畫在美國 VIX 圖上當第二條線 |
| VIX 期貨夜間替代 | Yahoo `VIXY`（VIX 短期期貨 ETF）一分鐘線含盤前盤後 | **不是期貨本身**，只在讀數列顯示「VIXY … 非期貨本身」與盤前／盤中／盤後、較收盤與較昨收的漲跌 |

兩個即時來源都不是官方 API；失敗時該欄為 `null`，前端沿用上一次讀數與日收盤線，其他功能不受影響。

## 開發方法

- 解析與快取寫成純函式／小類別（`maya_sawa/services/volatility.py`），用真實回應做 fixture：`tests/market/macro/test_volatility_live.py`。
- `TW_VIX` 進 `FREE_CACHE_CODES`，沿用 `_cache_free_series`（重啟後可從資料庫還原）與 `reserve_source_call("TAIFEXVix")` 額度。
- 前端 `macroLive.ts` 的 `withLivePoint`／`liveReadout` 為純函式，`tests/market/macroVolatility.test.ts` 先寫；圖版面常數在 `macroLayout.ts` 的 `MACRO_VOLATILITY_CHARTS`。
- 前端經 `/api/market/dashboard/volatility/live` 轉送，每分鐘輪詢，頁面隱藏時暫停。

## VIX 期貨（2026-11-16 補）

- 免費來源沒有 VIX 期貨的夜間即時價：Cboe 的延遲行情（CDN）回 403，Yahoo、Stooq 都沒有 VX 期貨。能取得的是 Cboe 每日公布的結算價（官方、免費）。
- 夜間看 **VIXY**：美股盤前（美東 04:00）到盤後（20:00）都有價，涵蓋台灣的整個晚上，但它追蹤的是 S&P 500 VIX 短期期貨指數（近月與次月的混合），不等於近月期貨，也有損耗；所以只當方向參考，畫面一律標「非期貨本身」。
- Cboe 遇到假日或當天尚未結算，會回前一個交易日的結算價，所以抓取程式跳過「今天」，並把與前一天檔案完全相同的檔案視為假日重複。
- 若之後有 IBKR 的 CFE 期貨行情訂閱，可改接 IBKR 取得真正的 VX 近月夜間價。
