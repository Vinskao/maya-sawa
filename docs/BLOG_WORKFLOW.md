# 文章知識庫：Markdown 直接入庫

## 撰稿規範（2026-10-29 起，人與 AI 都適用）

文章要讓之後的人或 AI 讀完就能維護或仿作，不是開發日記。規範的唯一來源是前端 `src/scripts/work/writingGuide.ts`（`WRITING_GUIDE`），顯示在 `/tymultiverse/work` 與 `/tymultiverse/work/manage`；管理頁「存入並發布」會跑同一個 `auditArticle`，不符合就不發布（草稿仍可存）。重點：一篇一個技術問題；第一個標籤是 `Software Engineering` 或 `Quant Finance`；依序有問題、原理、實作（兩段以上真實程式碼）、替代方案表格、驗證、限制、參考資料；不寫「決策一…」「近期」「下一步」。範例：`docs/blog-import/research-platform-engineering-2026-10-28.md`、`docs/blog-import/engineering-market-lab-2026-10.md`。API 匯入不經過這個檢查，Agent 發文前要自己逐項核對。

## 最終架構與狀態

正文、文章資訊、修訂與向量都保存於 PostgreSQL。前端不再保存文章來源，也不再同步文章。

本機程式與測試已建立；尚未執行正式 DB DDL、正式匯入、向量 API 端到端驗證或部署。`BLOG_ENABLED` 預設 false。不要先單獨部署新版前端：它依賴新版文章 API。

曾參考 `peoplesystem-terraform-oke/object-storage` 的私有 OCI bucket、獨立 state、Instance Principal 與無刪除權限設計。最後採 PostgreSQL，是因為 Maya Sawa 的 `QAVectorDatabase.similarity_search` 在主 DB 的 `articles` 同時查正文與 pgvector；把正文獨立放 bucket 會增加跨儲存一致性。bucket 本次沒有變更，可另作附件或備份。

## 使用方式

1. 管理者開啟 `/tymultiverse/work/manage`，上傳 UTF-8 `.md` 或將完整 Markdown 貼進文字框。
2. 「直接存入 DB 草稿」建立草稿；「存入並發布」保存後發布。載入既有文章後，匯入會更新該文章並帶版本檢查。
3. 發布、下架與刪除直接更新 DB；不需前端 build，也沒有 Sync 按鈕。
4. Agent 可呼叫 JSON 匯入或 multipart 上傳 API。使用既有 Keycloak `manage-users` 權限，沒有新增共用寫入金鑰。

Markdown 範例：

```markdown
---
slug: engineering-log
title: "工程開發紀錄"
description: "這次解決的問題與成果"
category: Engineering
tags: [Astro, FastAPI, PostgreSQL, TDD]
publishDate: "2026-10-27T09:00:00+08:00"
---

## 背景

## 決策與實作

## 驗證與限制
```

剪貼簿內容必須含 slug；上傳檔案缺 slug 時使用檔名。舊文無時區的日期按台北時間解讀。YAML 使用 safe loader，禁止 alias／anchor 與可執行標記；正文以安全 CommonMark 渲染，原始 HTML 不執行。

## API

路徑前綴為 `/maya-sawa/blog`；瀏覽器另可透過同源 `/tymultiverse/api/blog` proxy。讀寫目標固定，不接受任意 upstream URL。

- `GET /articles`：公開已發布列表，不含正文與編輯資訊。
- `GET /articles/{slug}`：公開發布版本正文。
- `GET /admin/articles`、`GET /admin/articles/{slug}`：草稿、發布版本、etag 與背景工作狀態。
- `POST /admin/import`：JSON `{markdown, operation: "create"|"update", publish: false|true, slug?}`。
- `POST /admin/upload`：multipart 的 `file`（.md）、`operation`、`publish`。
- `POST /admin/articles/{slug}`、`PUT /admin/articles/{slug}`：結構化欄位 CRUD，供其他工具使用。
- `POST /admin/articles/{slug}/publish|unpublish|restore`：生命週期操作。
- `DELETE /admin/articles/{slug}`：移至可復原回收區。
- `POST /admin/articles/{slug}/trigger`：重試該篇文章的向量化工作。
- `GET /admin/articles/{slug}/revisions/{revision}`：讀取不可變修訂。復原舊稿可將該修訂重新提交為草稿。

所有 admin API 需要 Bearer token 與管理角色。更新、發布、下架、刪除與復原需 `If-Match`，取自最近 GET／寫入回應的 `etag`；缺少回 428，過期或正在處理回 409。POST create 遇到同 slug 回 409，絕不自動覆蓋。Agent 不要把 token 寫入 Markdown、URL 或 Git。

API 呼叫範例（token 由工具既有的安全認證注入）：

```text
POST /maya-sawa/blog/admin/upload
Authorization: Bearer <existing-token>
Content-Type: multipart/form-data
file=@engineering-log.md
operation=create
publish=true
```

更新前先 GET admin article，再以回傳 etag 帶 `If-Match` 上傳 `operation=update`。

## 資料與交易

使用 `Config.DB_CONNECTION_STRING` 指向的主資料庫，與 QA 的 pgvector 查詢相同；不依賴可能獨立設定的 Paprika DB。

- `blog_article_state`：slug 對應的 JSONB 編輯狀態與整數版本。包含 draft revision、published revision、deleted、editor、事件、向量化狀態、lease、attempts 與 retryAfter。
- `blog_article_revisions`：不可變的 JSONB 修訂；保留 title、description、category、tags、publishDate、Markdown 正文、sha256、revision 與 updatedAt。
- 既有 `articles`：公開查詢用正文與向量。正式欄位為 `text`，為相容舊 ORM 保留原型別，QA 使用 `embedding::vector` 計算；保留原有 ID 與 `file_path={slug}.md` 身分。

草稿修訂先保存，state 以 compare-and-swap 更新；若版本衝突，最多留下沒有被引用的修訂，不會覆蓋他人的內容。revision 正文可供日後稽核，沒有自動清除。

發布 state 與 `articles` 正文更新在同一筆 DB transaction。只有正文變更才將舊 embedding 設為 NULL；只更新標題或分類會沿用既有向量。下架或刪除時移除衍生的 `articles` 搜尋列；正文及修訂仍在 editorial tables，可復原。QA 同時排除 `deleted_at IS NOT NULL` 的舊資料。

向量化工作事件與 state 一起持久保存。背景 worker 每 30 秒掃描 pending／failed，180 秒 lease 與版本 CAS 防止同時處理；失敗採遞增等待、上限一小時，也可管理頁手動重試。服務重啟會重新讀取待辦。生成向量後鎖定 state、核對 published revision，才寫進 pgvector；舊工作不能覆蓋新版向量。

向量化沿用既有 EmbeddingService 的模型與維度設定。草稿不呼叫 embedding API；發布後會呼叫。向量化失敗不影響文章閱讀，但該版在完成前不會出現在語意查詢。

## 遷移與切換順序

1. 備份文章資料，核對 `articles.embedding` 的 text／vector 型別、向量可轉成 pgvector、欄位齊全且維度與 EmbeddingService 相同。不要執行 `sql/philotes.sql`：它含 DROP TABLE。
2. 部署後端程式，維持 `BLOG_ENABLED=false`。舊站此時仍可讀。
3. `docs/blog-import/` 保存 67 篇原文與 1 篇新開發紀錄，是一次性匯入檔，並由 `.dockerignore` 排除於 runtime image。先乾跑：

   ```text
   poetry run python -m scripts.import_blog
   ```

4. 在可連主 DB 的受控環境執行：

   ```text
   poetry run python -m scripts.import_blog --apply --initialize --publish
   ```

   `--initialize` 只新增兩張 editorial tables；不重建既有 articles。先依 file_path 接管既有 DB 文章，保留原 ID、DB 正文與向量，只從 Markdown 補文章資訊。DB 正文與封存不同時以 DB 為準；只有缺文才新增。既有向量不重建，僅為缺向量或正文變更的版本排程。已被人工編輯的 state 不覆蓋。

5. 套用 `k8s/blog-config.yaml`，核對後把 BLOG_ENABLED 改為 true 並重新部署後端。此開關啟用公開 API／worker，也讓舊 Paprika 寫入與 QA sync 回 410。`k8s/cronjob.yaml` 已設 suspend，不能再從遠端覆蓋 DB。
6. 驗證匿名 GET 正文、管理者 Markdown 上傳、一般帳號 403、草稿 404、下架後 QA 不可搜尋、向量完成狀態與實際 QA 命中，再部署前端並執行 Jenkins production build。
7. 新前端 `/api/sync-articles` 與 `/md-exporter` 永遠回 410，不再呼叫批次刪除、purge 或同步。後續文章直接透過 DB API 管理。

回退前端須使用同一代文章 API 介面；不要重開舊 Sync 去覆蓋人工文章。必要時恢復上版程式與已備份 DB，並保持舊同步停用。

## 驗證範圍

後端測試命令：

```text
poetry run python -m pytest tests/test_blog.py tests/test_blog_postgres.py tests/test_blog_markdown.py tests/test_blog_import.py tests/test_blog_legacy_guard.py -q
```

涵蓋生命週期、授權、MD 匯入、真實舊文、CAS、修訂、交易 rollback、來源與 QA 正文一致、舊向量清除、工作重試與舊 sync 保護。另以 `tests/integration_blog_postgres.py` 在獨立 PostgreSQL schema 實測 JSONB、原 ID／向量保留、multipart CRUD、真實向量 SQL 搜尋及下架過濾；測試結束只清除此測試 schema。

前端：`<bundled-node> node_modules/vitest/vitest.mjs run tests/work`。本機視覺預覽使用明確的暫存測試資料，不是正式 DB，也未呼叫付費向量 API。
