# AI 分析每日時間戳記（OpenTimestamps）

目的：證明某天的 AI 分析在那天就已經寫好，之後一字未改。資料庫是站方自己的，日期可以事後改；把指紋錨定在比特幣上，就不需要信任站方。

程式：`maya_sawa/services/analysis_timestamps.py`（`.ots` 解析與排程）、`maya_sawa/databases/analysis_timestamp_db.py`（資料表 `maya_sawa_analysis_timestamp`）。測試：`tests/test_analysis_timestamps.py`。

## 名詞

- **時間戳記**：一份「這份內容最晚在某時間點已存在」的證明，類似郵局存證信函，但蓋章的是比特幣區塊鏈。
- **雜湊（SHA-256 指紋）**：內容改一個字，指紋就完全不同；從指紋推不回內容，所以送出指紋不會外流分析。
- **OpenTimestamps 時間戳記伺服器（calendar）**：收集全世界送來的指紋，合併成一筆比特幣交易，手續費由它們吸收，使用者免費、不需要錢包。
- **`.ots` 證明檔**：從我們的指紋一路算到比特幣區塊的步驟（append、prepend、sha256…），最後是「等待中（pending）」或「比特幣區塊高度」。

## 流程

1. 每小時檢查一次；若「昨天（台北時間）」還沒蓋章，且昨天有寫入任何 AI 分析版本，就蓋章。
2. **清單（manifest）**：昨天每個版本（`maya_sawa_market_ai_analysis_revision`，版本寫入後不會再改）算一個指紋，依 productType、code、revision 排序成 JSON。清單只有指紋，沒有內容。
3. 清單的 SHA-256 送到三個公開伺服器（`a.pool.opentimestamps.org`、`b.pool.opentimestamps.org`、`a.pool.eternitywall.com`），至少一個收下才算成功。收據存進資料表，狀態 `pending`。
4. 幾小時後比特幣出塊，伺服器會回傳到區塊的完整路徑；排程把它補進 `.ots`，狀態改成 `confirmed`，記下區塊高度。
5. 只會連上述網域的 https（`calendar_allowed`），收據裡寫的其他網址一律不連。

## 每個版本的指紋怎麼算

```
sha256( JSON{code, content, model, productType, revision, updatedAt}，key 排序、無空白、UTF-8 )
```

欄位和值都跟公開 API `GET /maya-sawa/market/dashboard/analysis/{code}?productType=...` 的 `history` 一模一樣（`updated_by` 不公開，所以不納入）。任何人都能從公開 API 重算，比對清單裡的指紋。

## 公開端點（會自動出現在網站 API 分頁）

| 端點 | 內容 |
|---|---|
| `GET /maya-sawa/market/timestamps` | 最近 90 天：日期、清單指紋、版本數、狀態、比特幣區塊高度 |
| `GET /maya-sawa/market/timestamps/{day}/manifest` | 當天被蓋章的清單原始檔（`ai-analysis-YYYY-MM-DD.json`） |
| `GET /maya-sawa/market/timestamps/{day}/proof` | 對應的證明檔（`ai-analysis-YYYY-MM-DD.json.ots`） |

## 怎麼驗證

1. 下載某天的 manifest 和 proof。
2. 把兩個檔案拖到 <https://opentimestamps.org> 的驗證區；狀態 `confirmed` 後會顯示比特幣區塊時間。
3. 要驗證某一則分析：從公開 API 取那個版本，照上面的公式算指紋，確認它在清單裡。

## 能證明與不能證明的

- 能證明：清單裡的每個版本，在那個比特幣區塊時間之前就存在，之後沒改。
- 不能證明：是誰寫的、內容對不對。
- 防「同一天偷蓋兩份」：每天只會有一份清單，而且清單和指紋公開在上面的端點，事後多出來的版本對不上。
- 公開 API 每檔只回傳最近 20 個版本；更早的版本仍在資料庫，清單指紋一樣有效，但目前無法從公開 API 取回原文來重算。
- 蓋章是從功能上線（2026-10-28）後的「昨天」開始，不回補更早的日子；回補只能證明「蓋章當下已存在」，容易被誤讀成當天就蓋過。

## 實作備註

- 不加套件：`.ots` 格式自己解析，測試用官方範例 `hello-world.txt.ots`（比特幣區塊 358391）逐位元組讀寫一致，以及 2026-10-28 三個伺服器的真實回應（`tests/fixtures/ots/`）。
- 只有一個 pod（`replicas: 1`），資料表以日期為主鍵，重跑也不會重複蓋章。
