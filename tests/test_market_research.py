import json

import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.market_ai_analysis_db import MarketAiAnalysisDatabase
from maya_sawa.services import market_research


def record(**overrides):
    content = {
        "name": "台積電", "market": "TW", "asOf": "2026-10-18",
        "summary": "Foundry leader.",
        "supplyChain": "flowchart LR\n  ASML[ASML EUV] --> TSMC[台積電]\n  TSMC --> NVDA[NVIDIA]",
        "technology": "flowchart LR\n  N3 --> N2 --> A16",
        "assessment": {
            "cycle": {"view": "順風", "note": "AI capex"},
            "technology": {"view": "順風", "note": "N2 ramp"},
            "delivery": {"view": "中性", "note": "CoWoS tight"},
        },
        "lean": "中立", "leanReason": "Strong fundamentals, foreign selling.",
        "watch": ["10/16 earnings call"],
        "sources": [{"label": "TSMC IR", "url": "https://investor.tsmc.com/"}],
    }
    content.update(overrides)
    return content


@pytest.fixture
def database(tmp_path):
    return MarketAiAnalysisDatabase(create_engine(f"sqlite:///{tmp_path / 'research.db'}"))


def test_valid_research_record_parses_with_lean_and_three_views():
    parsed = market_research.validate_research_content(json.dumps(record(), ensure_ascii=False))
    assert parsed["lean"] == "中立"
    assert [parsed["assessment"][key]["view"] for key in ("cycle", "technology", "delivery")] == ["順風", "順風", "中性"]


@pytest.mark.parametrize("bad", [
    "not json",
    json.dumps(record(lean="Strong buy")),
    json.dumps(record(supplyChain="")),
    json.dumps(record(technology="sequenceDiagram\n A->>B: hi")),
    json.dumps(record(supplyChain="flowchart LR\n A --> B\n click A \"https://evil.example\"")),
    json.dumps(record(assessment={"cycle": {"view": "順風", "note": ""}})),
    json.dumps(record(sources=[{"label": "x", "url": "javascript:alert(1)"}])),
])
def test_invalid_research_record_is_rejected(bad):
    with pytest.raises(ValueError):
        market_research.validate_research_content(bad)


def test_seed_inserts_missing_records_and_refreshes_only_seed_written_ones(database):
    seeds = {"2330": record(), "6857-JP": record(name="Advantest", market="JP")}
    assert market_research.seed_research(database, seeds) == {"inserted": 2, "updated": 0, "kept": 0}
    # Re-running with identical seeds changes nothing (no duplicate revisions on every restart).
    assert market_research.seed_research(database, seeds) == {"inserted": 0, "updated": 0, "kept": 2}
    # A newer seed replaces a record nobody has edited since.
    seeds["2330"] = record(lean="買")
    assert market_research.seed_research(database, seeds)["updated"] == 1
    assert json.loads(database.read("research", "2330")["analysis"]["content"])["lean"] == "買"
    # Once someone edits a record, seeds never overwrite it.
    current = database.read("research", "2330")["analysis"]
    database.save("research", "2330", "Analyst", json.dumps(record(lean="賣"), ensure_ascii=False), current["revision"], "owner")
    seeds["2330"] = record(lean="中立")
    assert market_research.seed_research(database, seeds)["kept"] == 2
    assert json.loads(database.read("research", "2330")["analysis"]["content"])["lean"] == "賣"


def test_records_persist_after_an_instrument_leaves_holdings_and_are_listed(database):
    market_research.seed_research(database, {"2330": record(), "9999": record(name="Removed holding")})
    listed = market_research.list_research(database)
    assert [(item["code"], item["name"], item["lean"]) for item in listed] == [("2330", "台積電", "中立"), ("9999", "Removed holding", "中立")]
    assert "content" not in listed[0]


def test_bundled_seed_files_are_all_valid_and_cover_current_holdings():
    seeds = market_research.load_seed_records()
    for code in ("TXF", "2330", "3008", "3081", "3017", "3105", "3324", "8996", "6187", "3711", "6442", "6213", "3443",
                 "3167", "2408", "6857-JP", "6524-JP", "META-US", "LITE-US", "000660-KR"):
        assert code in seeds, code
        market_research.validate_research_content(json.dumps(seeds[code], ensure_ascii=False))


def test_api_validates_research_writes_and_lists_records(database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_ai_analysis_db", database)
    app = FastAPI()
    app.include_router(market.router)
    app.dependency_overrides[market.require_authenticated] = lambda: {"sub": "owner"}
    client = TestClient(app)
    endpoint = "/market/dashboard/analysis/2330?productType=research"
    assert client.put(endpoint, json={"model": "AI", "content": "free text", "expectedRevision": 0}).status_code == 422
    body = {"model": "AI", "content": json.dumps(record(), ensure_ascii=False), "expectedRevision": 0}
    assert client.put(endpoint, json=body).json()["analysis"]["revision"] == 1
    assert client.get("/market/dashboard/research").json()["records"][0]["code"] == "2330"
