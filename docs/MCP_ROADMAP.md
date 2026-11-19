# Maya Sawa MCP 擴充規劃

目標：讓同事與他們的 Agent 能用同一個登入，查到 Maya Sawa 已公開的研究資料。Maya 仍是 FastAPI，MCP 只是同一批資料的另一個介面。

現況：`/market/research/mcp` 只有一個工具 `get_stock_analysis`（`api/research_mcp.py`），Birch 發文 MCP 在 `api/publisher_mcp.py`。兩者各自手寫一份 JSON-RPC，再加工具就會複製第三份。

## 原則

1. **只開唯讀。** 寫入類（主張提案、monitor PUT、發文以外的管理）維持排程用的 agent key，不進 MCP。
2. **權限不擴大。** 研究端點維持單一 scope `research.read`，audience 不變。持股與 IB 資料不開；真要開，另立 `owner.portfolio` scope、另一個端點。
3. **工具少而粗。** 一個工具回答一類問題，不把每支 API 都包成工具。
4. **資料來源用現成的。** 公開 API 已有 `public_data(...)` 註冊（`api/market.py`、`market_reports.py`），工具直接呼叫同一批讀取函式，確保 MCP 與公開網頁看到的版本一致。
5. 不動 Keycloak 設定與 `core/security.py` 的 `resource_paths`；新工具都放在既有 `/market/research/mcp`，不新增路徑。

## 工具清單

| 階段 | 工具 | 參數 | 讀取來源 |
|---|---|---|---|
| 0 | `get_stock_analysis`（已有） | market, code | `market_ai_analysis_db.read` |
| 1 | `get_macro_snapshot` | `series?`（如 taiex_bias、valuation、csp、leverage） | `/market/dashboard/macro`、`/dashboard/macro/nodes` |
| 1 | `get_benchmark_monitor` | `code?`（龍頭代碼） | `tw_benchmark` 的 monitor 讀取（只讀，不含 configuration 的 revision 寫入欄位） |
| 1 | `get_daily_reading` | `date?`（預設最新已核准） | `daily_maya` 已核准的文字與日期，不含音檔 |
| 2 | `search_reports` | `keyword`, `code?` | `/market/reports/fulltext`、`/claims` |
| 2 | `get_stock_fundamentals` | code | `/dashboard/fundamentals/{code}` |
| 3 | `ask_maya` | `question` | `/qa/query`；會耗 AI 額度，需自己的限流，額度用完回既有「還沒上班」文字 |

階段 1 做完先給同事用兩週，看實際被呼叫的工具再決定階段 2、3。

## 實作步驟（給 GPT）

每一步先寫失敗測試，再實作，再跑測試，最後 commit 推 `main`（SSH URL）。

1. **抽共用核心（已完成，示範版）。** 新增 `maya_sawa/api/mcp_core.py`：JSON-RPC 解析、`initialize`／`ping`／`tools/list`／`tools/call`、body 上限、錯誤格式，以及 `Tool` 註冊（名稱、說明、pydantic 輸入模型、處理函式、`readOnlyHint`）。`research_mcp.py` 改成只註冊工具；行為不變，現有 `tests/test_research_mcp.py` 必須原封不動通過。Birch 的 `publisher_mcp.py` 這次不動。
2. **階段 1 的三個工具。** 每個工具一個處理函式，回傳 `structuredContent` 與一份文字 JSON；輸入用 `extra='forbid'`；查無資料回 `status: not_found`，不丟例外；例外一律回 `isError`，內容不洩漏內部訊息。
3. **回傳大小控制。** 每個工具的輸出上限（例如 24 KB），超過就截斷並附 `truncated: true` 與提示改用較窄的參數。
4. **文件。** 更新 `docs/RESEARCH_MCP.md` 的工具清單與 Mermaid 圖；站上 `/api` 頁加一段 MCP 說明與 Claude Code／Codex 的加入範例。
5. **專案層級設定。** repo 根目錄加 `.mcp.json`（只含 `ty-research` 的網址，不放任何密鑰），讓同事 clone 後核准即可。
6. **skill。** 在 `keycloak-mcp-oauth` skill 補「新增工具不需動 Keycloak」，另可新增一份 `research-mcp` skill 記工具清單與新增工具的步驟。

## 驗收

- 測試：`poetry run python -m pytest tests/test_research_mcp.py tests/test_mcp_core.py -q`（新工具各自有成功、查無、參數錯誤、超大輸出四種案例）。
- 部署後：未登入 401 帶 `WWW-Authenticate`；Codex 與 Claude Code 各登入一次，`tools/list` 看到全部工具；每個工具的回傳與公開 API 版本一致；研究 token 打 Birch 端點被拒。
- 部署與 Keycloak 驗證由 TY 或有權限的人執行，GPT 不要自己改 Keycloak。

## 不做

- 不用 FastMCP（會逼 starlette 升到 1.x，與 FastAPI 0.115.9 不相容）。
- 不開持股、IB、個人資產類資料。
- 不開任何寫入工具。
- 不另建 MCP 專用 repo；沿用 maya-sawa。

## 進度

- 步驟 1 完成：`api/mcp_core.py`（`McpServer`、`Tool`）、`tests/test_mcp_core.py`；`research_mcp.py` 縮成認證加一筆 `Tool` 註冊，既有測試未改且通過。新增工具只需寫處理函式與輸入模型，再加進 `server` 的清單。
