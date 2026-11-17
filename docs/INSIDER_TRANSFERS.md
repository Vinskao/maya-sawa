# 內部人申報賣股（2026-11-17）

個股若有董事、監察人、經理人或大股東申報「持股轉讓事前申報」且有效轉讓期間還沒結束，就在個股列（含持股清單）與個股明細標題旁標「內部人申報賣股中」；有效期間 7 天內才開始的標「內部人即將賣股」。滑過去看申報人、預定股數、轉讓方式與期間。這筆也會出現在「近期公司事件」表。

```mermaid
flowchart LR
  A[TWSE OpenAPI t187ap12_L<br/>上市 每日內部人持股轉讓事前申報] --> C
  B[TPEx OpenAPI mopsfin_t187ap12_O<br/>上櫃 同上] --> C
  C[market_insider_transfers.collect<br/>每 4 小時，民國日期轉換、分出賣股] --> D[(maya_sawa_insider_transfer<br/>保留到期間結束後 120 天)]
  D --> E[market_company_events.get<br/>只取選定標的、期間未結束的賣股]
  E --> F[/market/dashboard/events/]
  F --> G[前端 insiderSaleNotice<br/>個股列徽章 + 明細標題]
```

## 規則

- **只把賣到市場的轉讓算賣股**：一般交易、盤後定價、鉅額、洽特定人、拍賣、標購、公開招募。贈與、信託等不算，不標示（`SALE_METHODS`）。
- 同一檔多人申報合併為一筆事件，股數加總，寫「N 位內部人」。
- 申報是「預定」轉讓上限，不代表已成交；期間結束沒賣完會另有「未轉讓申報」，見下節。

## 限制

- OpenAPI 每次只列**最新一個營業日**的申報，沒有歷史。所以要每天收、存進資料庫。**部署前已申報、期間還沒結束的不會出現**，約一個月後才完整。
- MOPS 的查詢頁對匿名請求回「因安全性考量無法呈現」，不能補歷史（見前端 `docs/MARKET_DASHBOARD_PLAN.md`）。

## 開發方法

用當天真實回應各取 4 筆做 fixture（`tests/fixtures/market/insider_transfer_twse.json`、`insider_transfer_tpex.json`），`tests/market/test_insider_transfers.py` 測民國日期、兩市場欄位差異、賣股分類、期間判斷、多人合併、存取不重複與公司事件整合；前端 `tests/market/companyEventPresentation.test.ts` 測徽章文字。

## 未轉讓申報與內部人增持（2026-11-17 同日加）

| 標記 | 顏色 | 來源 | 規則 |
|---|---|---|---|
| 內部人申報賣股中／即將賣股 | 紅 | `t187ap12_L`、`mopsfin_t187ap12_O`（每日） | 見上 |
| 內部人申報未賣出 | 灰 | `t187ap13_L`、`mopsfin_t187ap13_O`（每日） | 申報日起 14 天內顯示，含未轉讓股數、原申報股數與理由（如「股價不理想」） |
| 內部人增持 | 綠 | `t187ap11_L`、`mopsfin_t187ap11_O`（每月董監事持股餘額） | 與上個月比，只算兩個月都在名單上的人，淨增加 ≥ 10 張；顯示到下個月資料出來 |

```mermaid
flowchart LR
  U[t187ap13 未轉讓申報 每日] --> T[(maya_sawa_insider_untransferred)]
  H[t187ap11 董監事持股餘額 每月 約 10MB] --> S{資料年月比已存的新？}
  S -- 否 --> X[略過]
  S -- 是 --> C[與上月逐人比較<br/>新任／卸任不算、同一人多職稱只算一次]
  C --> SN[(maya_sawa_insider_holding_snapshot<br/>每市場一列 JSON，只留最新月)]
  C --> CH[(maya_sawa_insider_holding_change)]
  T --> E[market_company_events]
  CH --> E
```

增持判斷的取捨：

- **只給最新一個月，沒有歷史**：第一次部署只會存下當月快照，**要等下個月資料公布（約每月中）才有第一批增持標記**。
- 同一人可能以多個職稱出現（例：法人代表人兼總經理），以姓名去重，避免重複加總。
- 所有人持股同比例增加（±0.5%）視為配股，不標記。
- 月持股差額可能含員工認股、繼承等非市場取得，所以標「增持」並在說明寫明，不寫成「買進」。
- 快照存成每市場一列 JSON，不逐人寫入，避免每月數萬列寫進只有 100m CPU 的 postgres。
- 未轉讓申報、持股餘額每天抓一次（排程每 4 小時一輪，每 6 輪做一次）；持股檔同月份會略過比較。

開發方法：fixture 為當天真實回應（`insider_untransferred_*.json`；`insider_holdings_twse.json` 取 1101、2330 兩檔），上月資料由測試在 fixture 上改動產生；測試涵蓋空白列、多職稱去重、新任卸任、配股型態、10 張門檻、同月重跑。
