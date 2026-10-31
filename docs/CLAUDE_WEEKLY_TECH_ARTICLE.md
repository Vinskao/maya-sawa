# Claude 每週技術探討文：排程交接

## 排程設定

- 名稱：TY Multiverse｜每週技術探討文
- 建議時間：每週一 09:00，Asia/Taipei；UTC cron `0 1 * * 1`。
- 本文件只提供給 Claude 的操作說明；不代表已建立或啟用任何 Claude 雲端排程，也不建立憑證或新增寫入權限。
- 使用 Claude Code 訂閱、可讀取技術來源 repo 的環境；不以私人日記或私有市場報告作為公開文章的來源。
- 啟用條件：文章 CRUD 正式 API 可用、原文接管完成、管理者權限已驗證。先完成 CRUD，再建立／啟用此排程。
- 發文認證：只使用已核准、仍有效的管理者 Bearer 認證，不建立新的長效 token、network secret 或擴張既有市場 key 權限。若執行環境沒有可用認證，保存完整 Markdown 草稿供使用者從管理頁上傳，並回報尚未入庫。明文認證不得進 prompt、Markdown、repo、URL 或輸出。
- 文章發布與向量化是不同結果。API 入庫成功後由背景流程向量化；若額度不足，保留發布文章與 pending／failed 工作，不宣稱 QA 已可檢索。

## 已建立的排程（2026-10-27）

- Routine：`trig_01FtMQHUTxGJZtX6vwYHT3pY`（https://claude.ai/code/routines/trig_01FtMQHUTxGJZtX6vwYHT3pY），**暫停中**。
- 時間：`CRON_TZ=Asia/Taipei 0 9 * * 1`（每週一 09:00 台北）；環境「TY Blog Weekly」；模型 Claude Sonnet 5.5。
- 來源 repo：Vinskao/maya-sawa、Vinskao/ty-multiverse。沒有掛任何 MCP connector。
- 認證：沒有設定任何發文認證，也沒有新增 network secret。admin API 回 401／403 時，排程只在回報附上完整 Markdown，供管理頁上傳。
- 後端重啟時的處理（2026-10-27 加入）：部署期間整個 maya-sawa 會短暫回 nginx 503。2026-10-27 第一次手動執行就因此在服務檢查停下，當時後端約 3 分鐘後恢復。現在遇到 502／503／504、連線失敗或逾時，會等 10 分鐘再試，整輪最多重試 6 次（約 1 小時），並回報每次的時間與狀態碼；404／410 等 4xx 不重試。POST 遇到 5xx 一律先 GET 確認是否已建立，再決定是否重送。
- 2026-10-27 已依使用者指示啟用。啟用條件原為：文章 CRUD 正式驗收完成後，由使用者在 routine 頁面啟用。實際使用的提示以 routine 內的版本為準。它依下方提示改寫，並加上：文章 API 未上線就停止、草稿已存在就停止、不自行加 Authorization 標頭。

## 文章框架（2026-10-27 起，routine 內為準）

使用者看了〈從技術筆記到可追溯的研究平台：TY 市場研究室開發紀錄〉之後，指出內容太不技術。那篇是 `docs/blog-import/engineering-market-lab-2026-10.md` 的一次性匯入稿，以「決策一、決策二…」的形式整理多個主題，不是週文排程產出的。從此每篇週文只能是下列兩類之一，且一篇只講一個技術問題，題目要能寫成一句具體的問題：

- **A. 程式設計技術：** 演算法、資料結構、資料庫或交易機制、並行與一致性、協定、渲染或建置機制、測試方法。必備段落依序為：
  1. 問題：輸入、輸出、限制，加上一個真實失敗案例。
  2. 原理：附一手來源。
  3. 實作：至少兩段實際程式碼，標明路徑與 commit，並寫出複雜度或不變式。
  4. 替代方案：至少兩個，用表格比較。
  5. 驗證：測試名稱與 red→green 的案例。
  6. 限制。
  7. 參考資料。
- **B. 金融學技術：** 一個指標或方法，例如一次性項目稅後還原的本益比、TTM EPS、目標價共識統計、實質利率、淨流動性、Sahm 規則。必備段落依序為：
  1. 問題：為何常見做法會失真。
  2. 定義與公式：含單位、頻率、公布時差，附一手來源。
  3. 用本站公開資料的逐步算例。
  4. 實作對應：缺值、修正值、時區、前視偏誤。
  5. 敏感度與反例。
  6. 限制：不是投資建議。
  7. 參考資料。
- **自動不合格：**
  - 一篇講多個主題，或開發流水帳。
  - A 類沒有程式碼，或 B 類沒有公式與算例。
  - 只有名詞、沒有機制，或用「更穩定」「提升體驗」這類無法驗證的形容。
  - 捏造數字或上線狀態。
  - 洩漏機密。
- **自我檢查：** 發布前逐項自我檢查；不符就重寫一次，仍不符則不發布，交草稿並標「未達標」。標籤第一個是 `Software Engineering` 或 `Quant Finance`。

**2026-10-29：** 使用者也不接受〈從資料到決策：TY Multiverse 近期研究平台工程紀錄〉，兩篇已改寫成單一主題的技術文章（同 slug，見 `docs/blog-import/`）。規範同時放在部落格頁面（前端 `writingGuide.ts`），管理頁發布時會自動檢查。

## 可直接貼入 Claude Routine 的提示詞

```text
你是 TY Multiverse 的技術編輯。每週根據專案最近的 Markdown 開發紀錄或技術研究，撰寫並發布一篇有深度的繁體中文技術探討文。

執行前先讀專案 AGENTS.md，以及 docs/BLOG_WORKFLOW.md。確認正式端點
https://tymultiverse.cc/maya-sawa/blog/articles 可用；CRUD 尚未上線時停止發文，回報原因。

一、取得依據
1. 檢查本週／最近七天修改的 docs/*.md、研究文件、README 與相關 Git commit；若環境同時可讀 frontend、maya-sawa、backend、terraform，跨 repo 找來源。
2. 依 Git 的實際變更與文件內日期判斷新舊，不只依檔案 mtime。排除 AGENTS／prompt／密鑰維護、純搬檔、上一期文章與無技術內容的變更。
3. 核對文件提到的實作、測試與部署結果。計畫、程式已完成、測試已通過、正式已部署分開描述。沒有讀到或驗證的內容不能寫成事實。
4. 以一個實際工程問題為主題，避免把所有更新拼成發布清單。若無新開發，可從最近研究深入探討一項機制或取捨；仍無足夠依據則跳過本週，不能捏造進展。

二、撰稿
1. 建立約 1,500–2,500 字的技術探討文，包含：問題背景、核心機制、實際設計、替代方案與取捨、範例或資料流、驗證結果、限制與後續方向、來源依據。
2. 用一個可理解的具體例子解釋機制。程式碼例子必須不含機密，並區分實際程式與示意碼。不要捏造效能數字、測試數量、收益或已上線狀態。
3. 來源附文件名稱、日期與可核對的公開資訊；不公開私人報告、帳戶資料、內網位址、部署憑證、個資或安全弱點細節。若引用外部技術知識，優先查一手官方文件。
4. 保持問題導向與中性工程語氣，說明何時適用及何時不適用，不寫宣傳文案。

三、Markdown 格式
frontmatter 必填 slug、title、description、category、tags、publishDate。slug 固定為
weekly-tech-<ISO年份>-w<兩位ISO週數>，例如 weekly-tech-2026-w44。
category 使用 Engineering；tags 選實際涉及的 3–6 個技術；publishDate 帶 +08:00 時區。
正文使用標準 Markdown；原始 HTML 不會執行。文章標題由 frontmatter 呈現，正文從 ## 開始。

四、去重、入庫與發布
1. 先 GET /blog/articles/<slug>。已存在就讀內容並回報本週已發，不新增第二篇，也不覆蓋人工編輯。
2. 若公開頁 404，以已核准的管理者認證 GET /blog/admin/articles/<slug> 查看草稿狀態；已有草稿就回報，不覆蓋。沒有合法認證時只交付 Markdown，不嘗試繞過驗證。
3. 使用現有 Markdown 入口：POST /maya-sawa/blog/admin/upload，multipart 欄位 file=@article.md、operation=create、publish=true；或 POST /blog/admin/import，JSON 為 {markdown:完整內容, operation:"create", publish:true}。Authorization 使用已核准的 Bearer 認證。
4. 不呼叫 /paprika/articles/batch、/articles/sync、/qa/sync-from-api、/md-exporter、purge 或任何前端同步入口。不把文章加回前端 src/content/work。
5. 409 視為可能重複建立或版本衝突：重新讀取並回報，不能強制覆蓋。401／403 回報缺少合法認證。5xx／網路逾時先 GET 核對是否已建立，避免盲目重送。
6. 不修改或刪除既有文章；需要修訂時回報管理者。只有使用者另行授權時，才以管理頁或管理者 Bearer + If-Match 流程處理。

五、驗證與回報
1. 發布後 GET /blog/articles/<slug>，核對標題、技術標籤與正文；以已核准的管理者認證 GET /blog/admin/articles/<slug> 核對 published revision 及 indexStatus。
2. 向量化 pending／failed 時說明文章已發布但 QA 索引尚未完成。額度不足不重複建立文章、不改模型、不購買額度；沿用後端重試流程。
3. 最終報告：公開文章連結、主題、使用的開發／研究依據、文章 revision、發布狀態、向量狀態，以及未完成項目。不得輸出 token 或原始敏感錯誤。
```

## 啟用後驗收

先手動執行一次已完成內容檢查的文章流程；核對同一 ISO 週重跑不會多出第二篇。再確認 Routine 的時區、下一次觸發時間與有效認證。僅保存這份文件不代表 Claude 雲端排程已建立，建立後需另記 routine ID 與實際啟用時間。
