---
slug: engineering-market-lab-2026-10
title: "把季報疊到日 K 線上而不偷看未來：公布日對齊與時間窗"
description: "季度財務指標（營益率、存貨天數、本益比）要用公布日而不是季末對齊股價，否則圖表就有前視偏誤。說明對齊規則、缺公布日時的估計、時間窗以最後一筆觀測為錨，附程式碼、替代方案與測試。"
category: Software Engineering
tags: [Software Engineering, Time Series, Look-ahead Bias, TypeScript, Data Visualization, TDD]
publishDate: "2026-10-27T09:00:00+08:00"
---

## 問題

**輸入**：
- 每日 K 線 `{date, open, high, low, close, volume}`。
- 每季財務指標 `{period: "2026Q2", operatingMargin, inventoryDays, publishedAt?}`。有時帶 `publishedAt`，有時沒有。

**輸出**：每一根 K 線旁邊，顯示「那一天市場已經知道的」最新財務數字，畫在右軸上。

**限制**：不能插值造出不存在的日資料；缺值要留空，不能補 0；同一張圖要能切換「一日、一週、一月、一年、五年、全部」。

**常見錯法**：把 2026Q2 的營益率畫在季末 2026-06-30，或更糟，畫在季初 2026-04-01。台股第二季財報的法定公告期限是 8 月 14 日，所以在 7 月看圖的人會「看到」一個當時還沒公布的數字。圖看起來營益率一上升股價就漲，其實是指標被往前挪了一個多月。這就是**前視偏誤（look-ahead bias）**。拿這種圖去回測或下判斷，結果都會偏樂觀。

海外資料還有第二個陷阱。SEC companyfacts 會把一個數字標成「最新一份申報」的日期，而明年的 10-K 會再列一次今年的比較數，所以同一季的數字可能被標成一年後才「申報」。

## 原理

在任一天 *d*，可用的財務值是：**公布日 ≤ d** 的所有發布裡，公布日最晚的那一個（as-of join，或稱 point-in-time 查詢）。它是一個階梯函數：公布當天跳到新值，之後保持不變，直到下一次公布。

公布日不明時有兩種選擇：

- 丟掉該筆資料：安全，但線會大段空白。
- 用「不會更早」的日期估計，並標示為估計。估計日只能晚、不能早，晚了只會讓圖慢半拍，早了就會偷看未來。

## 實作

程式碼在 `ty-multiverse-frontend/src/scripts/market/priceComparison.ts` 與 `chartViewport.ts`（最新 commit `cb2ea67`）。圖表檔只負責畫，這些規則都是純函式，可以單獨測試。

### 1. 決定每一筆季報「什麼時候算公布」

```ts
// Without a publication timestamp, use the Taiwan filing deadline, explicitly marked as estimated.
// Never align a quarter's financial result to the first day of that quarter.
function statementDate(row: Record<string, any>, market: string) {
    const published = typeof row.publishedAt === 'string' ? chartDate(row.publishedAt.slice(0, 10)) : null;
    if (published) return { date: published, estimated: false };
    const quarter = /^(\d{4})Q([1-4])$/.exec(String(row.period));
    if (!quarter) return null;
    const year = Number(quarter[1]);
    if (market !== 'TW') {
        const end = chartDate(String(row.period))!;
        return { date: new Date(Date.parse(`${end}T00:00:00Z`) + 120 * 86_400_000).toISOString().slice(0, 10), estimated: true };
    }
    return { date: [`${year}-05-15`, `${year}-08-14`, `${year}-11-14`, `${year + 1}-03-31`][Number(quarter[2]) - 1], estimated: true };
}
```

規則依序是：

1. 有真實公布日就用公布日。
2. 台股沒有公布日時，用法定期限：Q1 是 5/15、Q2 是 8/14、Q3 是 11/14，年報是隔年 3/31。
3. 海外沒有公布日時，用季末加 120 天。

估計值都帶 `estimated: true`，讀數會標示「估計」。

海外的 EPS 另有一道上限：申報日如果晚於季末 120 天，就視為比較數重列，改用 120 天的估計日，避免 SEC 把它標成一年後。

```ts
const allowance = new Date(Date.parse(`${end}T00:00:00Z`) + 120 * 86_400_000).toISOString().slice(0, 10);
return filed > allowance ? { date: allowance, estimated: true } : { date: filed, estimated: false };
```

### 2. As-of 查詢

```ts
export function comparisonAt(series: readonly ComparisonPoint[], date: string): ComparisonPoint | null {
    let found: ComparisonPoint | null = null;
    for (const point of series) if (point.date <= date && (!found || point.date >= found.date)) found = point;
    return found;
}
```

**不變式**：對任一天，回傳值的 `date` 一定 ≤ 那一天。公布前一天回傳 `null`，不是上一季的值，也不是 0。日期一律用 `YYYY-MM-DD` 字串比較，不轉成本地時間，避免時區把日期往前推一天。

這裡每根 K 線都線性掃一次，複雜度是 O(K 線數 × 發布數)。一檔股票五年約 1,250 根 K 線、20 季，可以忽略。資料量大時可以換成下面表格裡的雙指標合併。

### 3. 時間窗以最後一筆觀測為錨

```ts
export function rangeWindow(dates: string[], range: ChartRange): ChartWindow | null {
    const full = bounds(dates); if (!full || range === 'all') return full;
    const end = new Date(`${full.end}T00:00:00Z`);
    if (range === 'day') return { start: full.end, end: full.end };
    if (range === 'week') return { start: iso(end.getTime() - 6 * DAY), end: full.end };
    const months = range === 'month' ? 1 : range === 'year' ? 12 : 60;
    const first = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() - months, 1));
    const lastDay = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0)).getUTCDate();
    first.setUTCDate(Math.min(end.getUTCDate(), lastDay));
    return { start: iso(first.getTime()), end: full.end };
}
```

窗口的終點是**資料裡最後一個日期**，不是今天。月資料（例如 CPI）通常晚一個多月才公布，如果用「今天往前一個月」，「一月」視窗會是空的。往回推月份時要夾住月底：2024-02-29 往前一年是 2023-02-28，不能溢位成 3 月 1 日。

`chartDate` 會把 `2024Q2` 轉成季末 `2024-06-30`、`2024-05` 轉成月底，讓季資料、月資料和日資料可以放進同一個窗口篩選。這裡只決定「落在哪個時間窗」，跟上面的公布日對齊是兩件事。

## 替代方案

| 做法 | 前視偏誤 | 線的連續性 | 複雜度 | 何時適用 |
|---|---|---|---|---|
| 畫在季末或季初 | 有，約 45～90 天 | 連續 | O(1) 查表 | 只看「各季本身」的走勢、不跟股價比時 |
| 只用有真實公布日的資料 | 無 | 缺很多段 | 同下 | 用於回測，寧缺勿錯 |
| **公布日；缺的話用法定期限或季末＋120 天估計，並標示（本文）** | 無；估計日只會偏晚 | 連續 | O(K·R) | 用於研究圖，要看趨勢也要誠實 |
| 雙指標合併（K 線與發布都已排序） | 同上 | 同上 | O(K+R) | 資料量大、或在伺服器端批次計算時 |
| 把季值內插成日值 | 有，而且會造出不存在的數字 | 平滑 | O(K) | 不建議 |

## 驗證

Vitest，`tests/market/priceComparison.test.ts` 與 `tests/market/chartViewport.test.ts`，共 16 個測試全部通過。其中直接鎖住本文規則的有：

- `aligns statements on explicit publication dates and keeps period labels in the readout`：2026Q2 在 8/14 公布，8/13 查詢得到 `null`，8/14 才得到 12.3%。沒有公布日的存貨天數在 8/14 出現，並標示 `estimated: true`。
- `preserves zero margins, rejects placeholders and invalid inventory, and sorts releases`：營益率 0% 要保留，`null` 和負的存貨天數則丟掉。
- `uses only same-day official PE, never fills missing PE from a later or previous trading day`：官方本益比只用當日值，不往前或往後填。
- `gives US stocks a PE across a fiscal Q4 that exists only in the 10-K, dating restated comparatives as estimated (META)`：比較數重列套用 120 天上限。
- `anchors presets on the latest observation and clamps leap years`：2024-02-29 往前一年是 2023-02-28。
- `filters and sorts sparse observations, without inventing daily data`：季資料不會被展開成日資料。

## 給維護者的檢查清單

1. 任何「季度值畫到日線」的地方，先問：這一天市場知道這個數字了嗎？寫一個「公布前一天是 null」的測試。
2. 不知道公布日時，用只會偏晚的估計並標示出來；永遠不要用季初。
3. 日期用 `YYYY-MM-DD` 字串、UTC 午夜處理，不用 `new Date('2026-08-14')` 再轉本地時間。
4. 時間窗錨在最後一筆資料，不是今天；月份回推要夾住月底。
5. 缺值留空。0 是合法值，例如營益率 0%。
6. 圖表檔只畫圖；對齊、格式、單位判斷都抽成純函式，再寫測試。

## 限制

- 法定期限是上限，實際多半更早公布；用估計日時，圖會慢幾天到幾週，只會偏晚，不會偷看。
- 財報事後更正（restatement）時，資料庫通常只留最新版。所以就算日期對了，顯示的也可能是更正後的值，嚴格來說還不是 point-in-time。要做嚴謹回測，得保存每一版公布的原始值。
- 海外 120 天是經驗值，涵蓋美國 10-Q／10-K 和日本決算短信的常見時程，個別公司可能不同。
- 這張圖是研究工具，不是交易訊號，也不構成投資建議。

## 參考資料

- 證券交易法第 36 條：財務報告公告申報期限（年報為會計年度終了後三個月內；第一、二、三季為各季終了後 45 日內）。
- SEC EDGAR XBRL companyfacts API：<https://www.sec.gov/edgar/sec-api-documentation>
- Marcos López de Prado，*Advances in Financial Machine Learning*（2018），談回測偏誤與 point-in-time 資料。
- 本站實作：`src/scripts/market/priceComparison.ts`、`src/scripts/market/chartViewport.ts`；說明文件 `docs/CHART_INTERACTION_PLAN.md`。
