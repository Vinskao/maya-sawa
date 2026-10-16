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
    app.dependency_overrides[market.require_authenticated] = lambda: {"sub": "owner"}
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
    app.dependency_overrides[market.require_authenticated] = lambda: {"sub": "owner"}
    client = TestClient(app)
    body = {"model": "AI", "content": "Rates are a valuation headwind", "expectedRevision": 0}
    assert client.put("/market/dashboard/analysis/US?productType=macro", json=body).json()["analysis"]["revision"] == 1
    assert client.get("/market/dashboard/analysis/us?productType=macro").json()["analysis"]["productType"] == "macro"
    assert client.get("/market/dashboard/analysis/US?productType=stock").json()["analysis"] is None
    assert client.put("/market/dashboard/analysis/2330?productType=macro", json=body).status_code == 422
    assert client.get("/market/dashboard/analysis/US?productType=bond").status_code == 422
