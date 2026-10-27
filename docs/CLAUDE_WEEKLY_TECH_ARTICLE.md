# Claude 每週技術探討文：排程交接

## 排程設定

- 名稱：TY Multiverse｜每週技術探討文
- 建議時間：每週一 09:00，Asia/Taipei；UTC cron `0 1 * * 1`。
- 使用 Claude Code 訂閱的專用環境 `TY Blog Weekly`，僅連結技術來源 repo；不沿用含私人日記或市場報告存取權限的環境。
- 啟用條件：文章 CRUD 正式 API 可用、原文接管完成、管理者權限已驗證。先完成 CRUD，再建立／啟用此排程。
- 發文認證：專用 network secret `ty-blog-weekly-writer`，代理對 `peoplesystem.tatdvsonorth.com` 注入 `X-Blog-Agent-Key`，不加 Bearer 前綴。後端僅存 SHA-256（`BLOG_WEEKLY_AGENT_KEY_SHA256`），明文不進 prompt、Markdown、repo、URL 或輸出。此 key 只能建立當週 `weekly-tech-YYYY-wWW` 的 Engineering 文章、讀自己文章的狀態，不能更新、刪除或取得管理者 CRUD 權限。既有市場 key 不擴權。建立持續性的雲端寫入憑證須先完成使用者確認。
- 文章發布與向量化是不同結果。API 入庫成功後由背景流程向量化；若額度不足，保留發布文章與 pending／failed 工作，不宣稱 QA 已可檢索。

## 可直接貼入 Claude Routine 的提示詞

```text
你是 TY Multiverse 的技術編輯。每週根據專案最近的 Markdown 開發紀錄或技術研究，撰寫並發布一篇有深度的繁體中文技術探討文。

執行前先讀專案 AGENTS.md，以及 docs/BLOG_WORKFLOW.md。確認正式端點
https://peoplesystem.tatdvsonorth.com/maya-sawa/blog/articles 可用；CRUD 尚未上線時停止發文，回報原因。

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
2. 若公開頁 404，再 GET /blog/weekly/articles/<slug> 查看自己的草稿／處理狀態；已有草稿就回報，不覆蓋。404 時才建立。
3. 使用每週排程專用的 Markdown 入口：
   POST /maya-sawa/blog/weekly/import
   JSON 為 {markdown:完整內容, operation:"create", publish:true}。
   環境代理會自動注入 X-Blog-Agent-Key；不要讀取、輸出或手動設定 key。
4. 不呼叫 /paprika/articles/batch、/articles/sync、/qa/sync-from-api、/md-exporter、purge 或任何前端同步入口。不把文章加回前端 src/content/work。
5. 409 視為可能重複建立或版本衝突：重新讀取並回報，不能強制覆蓋。401／403 回報缺少合法認證。5xx／網路逾時先 GET 核對是否已建立，避免盲目重送。
6. 排程 key 不可更新或刪除任何文章。需要修訂時回報管理者，由管理頁或管理者 Bearer + If-Match 流程處理。

五、驗證與回報
1. 發布後 GET /blog/articles/<slug>，核對標題、技術標籤與正文；再 GET /blog/weekly/articles/<slug> 核對自己的 published revision 及 indexStatus。
2. 向量化 pending／failed 時說明文章已發布但 QA 索引尚未完成。額度不足不重複建立文章、不改模型、不購買額度；沿用後端重試流程。
3. 最終報告：公開文章連結、主題、使用的開發／研究依據、文章 revision、發布狀態、向量狀態，以及未完成項目。不得輸出 token 或原始敏感錯誤。
```

## 啟用後驗收

先手動執行一次已完成內容檢查的文章流程；核對同一 ISO 週重跑不會多出第二篇。再確認 Routine 的時區、下一次觸發時間與有效認證。僅保存這份文件不代表 Claude 雲端排程已建立，建立後需另記 routine ID 與實際啟用時間。
