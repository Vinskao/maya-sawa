"""The public data API: market-data endpoints anyone may read, published as a small OpenAPI document for the site's API page.

FastAPI's own /openapi.json lists every route (internal, admin and agent-key ones too), so the page reads this document instead.
A route is public only when its decorator says so, and then it shows up on the page by itself, nothing else to edit:

    @router.get("/dashboard/foo", **public_data("中文說明", "分組名稱"))

tests/test_public_api.py checks every marked route is a GET with no login, key or internal secret.
"""
import copy

MARK = "x-public-data"
TITLE = "TY 市場研究室 公開資料 API"
DESCRIPTION = ("市場資料與研究紀錄的唯讀端點，任何人都能呼叫、不需要登入。寫入、持股與帳戶資料不在此列；"
               "需要 SSO token 的端點請聯繫網站擁有者。")
KEEP_RESPONSES = {"200", "404", "422", "503"}


def public_data(summary: str, group: str, *, schema: dict | None = None, examples: list | None = None) -> dict:
    """Decorator keyword arguments that publish a GET route on the API page, with a Chinese summary and a group heading.

    `schema` (inline JSON Schema of the 200 body) and `examples` ({venue, title, path} queries that work today) are optional."""
    return {"summary": summary, "openapi_extra": {MARK: {"group": group, "schema": schema, "examples": examples or []}}}


def build_public_openapi(app) -> dict:
    full = app.openapi()
    paths = {}
    for path, operations in full["paths"].items():
        operation = operations.get("get")
        if not operation or MARK not in operation:
            continue
        mark = operation[MARK]
        group = mark["group"]
        parameters = [dict(parameter) for parameter in copy.deepcopy(operation.get("parameters", [])) if "$ref" not in parameter]
        for parameter in parameters:
            parameter["schema"] = {"type": (parameter.get("schema") or {}).get("type", "string")}
        responses = {code: {"description": response.get("description", "")} for code, response in operation.get("responses", {}).items()
                     if code in KEEP_RESPONSES}
        if mark.get("schema") and "200" in responses:
            responses["200"]["content"] = {"application/json": {"schema": copy.deepcopy(mark["schema"])}}
        paths[path] = {"get": {
            "summary": operation.get("summary", path),
            "tags": [group],
            "x-group": group,
            "parameters": parameters,
            "responses": responses,
            **({"x-examples": copy.deepcopy(mark["examples"])} if mark.get("examples") else {}),
        }}
    return {"openapi": "3.1.0", "info": {"title": TITLE, "description": DESCRIPTION, "version": "1"},
            "servers": [{"url": "/maya-sawa"}], "paths": paths}
