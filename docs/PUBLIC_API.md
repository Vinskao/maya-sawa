# 公開資料 API（網站「API」分頁）

網站導覽列「關於」右邊的「API」分頁（`/tymultiverse/api-reference/`）列出任何人都能呼叫的**市場資料**端點。清單不是手寫的，
前端直接讀 `GET /maya-sawa/public-openapi.json`，所以不會和實際部署的端點有出入。

## 怎麼公開一個新的 API（不用動網站）

在路由的裝飾器加一行，網站的 API 分頁會自己出現它，前端不用改：

```python
from ..core.public_api import public_data

@router.get("/dashboard/foo/{code}", **public_data("中文說明", "分組名稱"))
async def get_foo(code: str): ...
```

- 分組名稱就是頁面上的標題；沒出現過的名稱會自動變成新的一組。
- 沒有加標記的路由永遠不會公開。FastAPI 內建的 `/openapi.json` 列出全部 100 多個端點（含內部、管理與 agent key 的路由），公開頁面不用它，
  改讀 `GET /maya-sawa/public-openapi.json`（只含有標記的 GET，不含請求內容與資料結構）。
- `tests/test_public_api.py` 在每次測試時檢查所有有標記的路由：必須是 GET、沒有登入／agent key／內部密鑰的依賴（含在函式裡直接讀標頭的情況）、
  有中文說明；持股、用量、通知、上傳、搜尋等都不能被標記。標錯了測試會失敗。

## 認證現況（Python 服務）

| 類型 | 怎麼驗證 | 例子 |
|---|---|---|
| 公開唯讀 | 無 | `/market/dashboard`、`/market/dashboard/history/{code}`、`/market/reports`、`/market/watch`（即本頁清單） |
| 擁有者 | Keycloak JWT + `manage-users` 角色 | `/market/portfolio`、`/market/usage`、`/market/notifications`、`POST /market/reports`、`/market/reports/web` |
| 排程 agent | `X-Market-Agent-Key`（雲端環境的代理自動加；後端只存 SHA-256） | `PUT …/analysis/{code}`、`POST /market/notify`、`/market/watch`、`/market/routine-usage`、`/market/reports/pending` |
| 內部 | `require_internal_secret` | `/market/internal/*` |

需要 SSO token 的端點無法在頁面上直接呼叫，頁面註明「請聯繫網站擁有者」。

## Spring Boot（ty-multiverse-backend）

不加 swagger：它的公開端點是人物、武器、圖庫與 AI 用量統計，都不是市場資料。

## 已知但不在這次範圍的未驗證端點

探測時發現下列 GET 不需要任何驗證：`/qa/chat-users`、`/qa/chat-history/{user_id}`（對話紀錄）、`/maya-v2/conversations/`、
`/maya-v2/ai-models/`、`/paprika/articles`（回應 560 KB）。其中對話紀錄與使用者名單是否該公開，需要擁有者決定。

