import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.market_ai_analysis_db import MarketAiAnalysisDatabase, AnalysisConflict


@pytest.fixture
def database(tmp_path):
    return MarketAiAnalysisDatabase(create_engine(f"sqlite:///{tmp_path / 'analysis.db'}"))


def test_next_ai_updates_current_comment_and_keeps_prior_revision(database):
    first = database.save("stock", "2330", "AI One", "First analysis", 0, "owner")
    second = database.save("stock", "2330", "AI Two", "Updated analysis", first["revision"], "owner")
    stored = database.read("stock", "2330")
    assert stored["analysis"] == second
    assert second["revision"] == 2
    assert [row["content"] for row in stored["history"]] == ["Updated analysis", "First analysis"]
    assert "updated_by" not in second and "owner" not in str(stored)
    assert database.read("futures", "2330")["analysis"] is None


def test_stale_writer_cannot_overwrite_and_retry_does_not_duplicate(database):
    saved = database.save("stock", "2330", "AI", "Saved", 0, "owner")
    assert database.save("stock", "2330", "AI", "Saved", 0, "owner") == saved
    with pytest.raises(AnalysisConflict):
        database.save("stock", "2330", "Other AI", "Stale draft", 0, "owner")
    assert len(database.read("stock", "2330")["history"]) == 1


def test_save_removes_literal_newline_escape_suffixes_from_2408_analysis(database):
    # This mirrors the 2408 report-view format saved by the manual Taiwan run:
    # each markdown line ended with the two-character sequence ``\\n`` and
    # then an actual newline, making the escape visible in the website.
    content = (
        "【結論】賣\\n\n"
        "報告觀點：記憶體循環（p10）與現行判斷相反\\n\n"
        "來源：財經M平方，p10–p12，9/15（封面未載年份）\\n\n"
        "維持賣出：2026Q2 毛利率 79.49%，仍需觀察營收年增與報價趨勢。"
    )

    saved = database.save("stock", "2408", "Claude (scheduled)", content, 0, "agent")

    assert saved["content"] == content.replace("\\n\n", "\n")
    assert all(not line.endswith("\\n") for line in saved["content"].splitlines())


def test_api_requires_login_and_validates_updates(database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_ai_analysis_db", database)
    app = FastAPI()
    app.include_router(market.router)
    client = TestClient(app)
    endpoint = "/market/dashboard/analysis/2330?productType=stock"
    body = {"model": "AI", "content": "Reviewed analysis", "expectedRevision": 0}
    assert client.get(endpoint).json()["analysis"] is None
    assert client.put(endpoint, json=body).status_code == 401
    app.dependency_overrides[market.analysis_editor] = lambda: "owner"
    assert client.put(endpoint, json={**body, "content": "   "}).status_code == 422
    assert client.put(endpoint, json={**body, "expectedRevision": -1}).status_code == 422
    assert client.put(endpoint, json=body).json()["analysis"]["revision"] == 1
    assert client.put(endpoint, json={**body, "content": "Stale"}).status_code == 409
    assert client.get(endpoint).json()["analysis"]["content"] == "Reviewed analysis"


def test_shared_macro_commentary_uses_its_own_slot(database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_ai_analysis_db", database)
    app = FastAPI()
    app.include_router(market.router)
    app.dependency_overrides[market.analysis_editor] = lambda: "owner"
    client = TestClient(app)
    body = {"model": "AI", "content": "Rates are a valuation headwind", "expectedRevision": 0}
    assert client.put("/market/dashboard/analysis/US?productType=macro", json=body).json()["analysis"]["revision"] == 1
    assert client.get("/market/dashboard/analysis/us?productType=macro").json()["analysis"]["productType"] == "macro"
    assert client.get("/market/dashboard/analysis/US?productType=stock").json()["analysis"] is None
    assert client.put("/market/dashboard/analysis/2330?productType=macro", json=body).status_code == 422
    assert client.get("/market/dashboard/analysis/US?productType=bond").status_code == 422


AGENT_KEY = "test-agent-key-not-a-real-secret"


def test_scheduled_agent_key_writes_stock_research_and_macro_analyses(database, monkeypatch):
    # The scheduled Claude Code routine has no Keycloak login; it sends a dedicated key whose SHA-256 is the only
    # thing the server stores. The key can write analyses and validated per-instrument research maps only.
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_ai_analysis_db", database)
    app = FastAPI()
    app.include_router(market.router)
    client = TestClient(app)
    body = {"model": "Claude (scheduled)", "content": "Daily refresh", "expectedRevision": 0}
    endpoint = "/market/dashboard/analysis/2330?productType=stock"
    monkeypatch.delenv("MARKET_AGENT_KEY_SHA256", raising=False)
    assert client.put(endpoint, json=body, headers={"X-Market-Agent-Key": AGENT_KEY}).status_code == 401  # not configured
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(AGENT_KEY.encode()).hexdigest())
    assert client.put(endpoint, json=body, headers={"X-Market-Agent-Key": "wrong"}).status_code == 401
    assert client.put(endpoint, json=body, headers={"X-Market-Agent-Key": AGENT_KEY}).json()["analysis"]["revision"] == 1
    assert client.put("/market/dashboard/analysis/US?productType=macro", json=body,
                      headers={"X-Market-Agent-Key": AGENT_KEY}).status_code == 200
    research = {
        "name": "台積電", "market": "TW", "asOf": "2026-10-29", "summary": "先進製程需求穩健",
        "supplyChain": "flowchart LR\nA[設備] --> B[晶圓製造]",
        "technology": "flowchart LR\nA[試產] --> B[量產]",
        "assessment": {
            "cycle": {"view": "中性", "note": "週期持平"},
            "technology": {"view": "順風", "note": "N2 於 2026-10 進入量產"},
            "delivery": {"view": "中性", "note": "交期未變"},
        }, "lean": "中立", "leanReason": "新資料尚未改變三項判斷", "watch": [], "sources": [],
    }
    research_body = {"model": "Claude (scheduled)", "content": __import__("json").dumps(research), "expectedRevision": 0}
    assert client.put("/market/dashboard/analysis/2330?productType=research", json=research_body,
                      headers={"X-Market-Agent-Key": AGENT_KEY}).status_code == 200
    assert database.last_editor("stock", "2330") == "agent:scheduled-analysis"
    assert client.put("/market/dashboard/industries/ai-optics", json={},
                      headers={"X-Market-Agent-Key": AGENT_KEY}).status_code == 401  # the key is not a login


def test_macro_chain_nodes_each_keep_their_own_analysis(database, monkeypatch):
    # 2026-10-27: the macro dashboard became logic chains; every node (a chart) carries its own analysis that the
    # scheduled routine rewrites. Node ids come from the frontend graph (src/storages/macroLogicGraph.json).
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_ai_analysis_db", database)
    app = FastAPI()
    app.include_router(market.router)
    client = TestClient(app)
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(AGENT_KEY.encode()).hexdigest())
    agent = {"X-Market-Agent-Key": AGENT_KEY}
    body = {"model": "Claude (scheduled)", "content": "【判讀】逆風\n核心通膨 2026-09 年增 3.1%", "expectedRevision": 0}
    assert client.put("/market/dashboard/analysis/core-inflation?productType=macro-node", json=body,
                      headers=agent).json()["analysis"]["revision"] == 1
    assert client.put("/market/dashboard/analysis/FOCUS-DISCOUNT-RATE?productType=macro-node", json=body,
                      headers=agent).status_code == 200
    assert client.put("/market/dashboard/analysis/bad_id!?productType=macro-node", json=body, headers=agent).status_code == 422
    assert client.get("/market/dashboard/analysis/US?productType=macro").json()["analysis"] is None  # shared commentary untouched
    listed = client.get("/market/dashboard/macro/nodes").json()["analyses"]
    assert [row["code"] for row in listed] == ["CORE-INFLATION", "FOCUS-DISCOUNT-RATE"]
    assert listed[0]["content"].startswith("【判讀】逆風")
    assert database.last_editor("macro-node", "CORE-INFLATION") == "agent:scheduled-analysis"


def test_notify_endpoint_requires_agent_key_and_relays(monkeypatch):
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    app = FastAPI()
    app.include_router(market.router)
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(b"k").hexdigest())
    sent = []
    monkeypatch.setattr(market.telegram_notify, "send", lambda kind, title, body="": sent.append((kind, title, body)) or {"sent": True})
    monkeypatch.setattr(market, "instrument_names", lambda: {})
    client = TestClient(app)
    body = {"kind": "attention", "title": "週報文章", "body": "需要登入"}
    assert client.post("/market/notify", json=body).status_code == 401
    assert client.post("/market/notify", json=body, headers={"x-market-agent-key": "wrong"}).status_code == 401
    assert client.post("/market/notify", json={**body, "kind": "spam"}, headers={"x-market-agent-key": "k"}).status_code == 422
    ok = client.post("/market/notify", json=body, headers={"x-market-agent-key": "k"})
    assert ok.status_code == 200 and ok.json() == {"sent": True} and sent == [("attention", "週報文章", "需要登入")]
    # Bare codes from a routine get their names before the message is sent.
    monkeypatch.setattr(market, "instrument_names", lambda: {"3008": "大立光"})
    sent.clear()
    client.post("/market/notify", json={"kind": "update", "title": "台股", "body": "3008 賣→中立"}, headers={"x-market-agent-key": "k"})
    assert sent == [("update", "台股", "3008 大立光 賣→中立")]
