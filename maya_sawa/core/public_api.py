"""The public data API: the market-data endpoints anyone may read, as a small OpenAPI document for the site's API page.

FastAPI's own /openapi.json lists every route (internal, admin and agent-key ones too), so the page uses this opt-in list instead.
Adding a path here is a deliberate decision; tests/test_public_api.py checks that each one is a GET with no login or key.
"""
import copy

# (path, Chinese summary). Market data only: no portfolio, usage, notifications, uploads or anything that writes.
PUBLIC_DATA: list[tuple[str, str]] = [
    ("/market/dashboard", "儀表板標的清單與即時報價（固定、自動、自訂、AI 觀察）"),
    ("/market/dashboard/history/{code}", "個股日線與籌碼歷史（最多五年）"),
    ("/market/dashboard/fundamentals/{code}", "個股月營收與季度財報（官方資料）"),
    ("/market/dashboard/overseas/{code}", "海外標的（美、日、韓）日線、財報與資料狀態"),
    ("/market/dashboard/events", "近期營收／財報發布與法說會"),
    ("/market/dashboard/analysis/{code}", "AI 分析、研究圖與其歷史版本"),
    ("/market/dashboard/targets/{code}", "券商目標價、共識與相關報告觀點"),
    ("/market/dashboard/industries", "產業分組"),
    ("/market/dashboard/research", "所有標的的研究圖紀錄"),
    ("/market/dashboard/macro", "總體經濟指標序列"),
    ("/market/dashboard/macro/nodes", "總經邏輯鏈各節點的判讀"),
    ("/market/dashboard/brief", "持股籌碼摘要"),
    ("/market/taiex-futures", "台指期近月報價"),
    ("/market/mini-tsmc-futures", "小型台積電期貨報價"),
    ("/market/reports", "公開研究報告清單（含 SEC 申報、頻道貼文與網路文章）"),
    ("/market/reports/{report_id}", "單一報告內容與其萃取出的主張"),
    ("/market/reports/claims", "研究報告主張（可用 code 或 segment 篩選）"),
    ("/market/reports/collector", "Telegram 頻道收集狀況（各頻道的數量與狀態，不含貼文內容）"),
    ("/market/watch", "AI 觀察名單：觀察中與候選的標的"),
]

TITLE = "TY 市場研究室 公開資料 API"
DESCRIPTION = ("市場資料與研究紀錄的唯讀端點，任何人都能呼叫、不需要登入。寫入、持股與帳戶資料不在此列；"
               "需要 SSO token 的端點請聯繫網站擁有者。")
KEEP_RESPONSES = {"200", "404", "422", "503"}


def build_public_openapi(app) -> dict:
    full = app.openapi()
    paths = {}
    for path, summary in PUBLIC_DATA:
        operation = copy.deepcopy(full["paths"][path]["get"])
        parameters = [dict(parameter) for parameter in operation.get("parameters", []) if "$ref" not in parameter]
        for parameter in parameters:
            parameter["schema"] = {"type": (parameter.get("schema") or {}).get("type", "string")}
        paths[path] = {"get": {
            "summary": summary,
            "tags": [path.split("/")[2] if path.count("/") > 1 else "market"],
            "parameters": parameters,
            "responses": {code: {"description": response.get("description", "")} for code, response in operation.get("responses", {}).items()
                          if code in KEEP_RESPONSES},
        }}
    return {"openapi": "3.1.0", "info": {"title": TITLE, "description": DESCRIPTION, "version": "1"},
            "servers": [{"url": "/maya-sawa"}], "paths": paths}
