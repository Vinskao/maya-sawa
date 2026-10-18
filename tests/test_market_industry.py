import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.market_industry_db import MarketIndustryDatabase, validate_group
from maya_sawa.services import market_research


@pytest.fixture
def database(tmp_path):
    return MarketIndustryDatabase(create_engine(f"sqlite:///{tmp_path / 'industry.db'}"))


OPTICS = {"id": "ai-optics", "name": {"zh": "AI 光通訊", "en": "AI optical interconnect"}, "diagram": None,
          "members": [{"recordCode": "3081", "name": "聯亞", "market": "TW", "role": "InP 磊晶"},
                      {"recordCode": "LITE-US", "name": "Lumentum", "market": "US", "role": "雷射晶片與模組"}]}
POWER = {"id": "dc-power-rack", "name": {"zh": "機房直流電源", "en": "Datacenter DC power"}, "diagram": "power-rack",
         "members": [{"recordCode": "2308", "name": "台達電", "market": "TW", "role": "電源架 / DC-DC"},
                     {"recordCode": "2301", "name": "光寶科", "market": "TW", "role": "電源架整流器"}]}


def test_groups_and_peers_are_looked_up_by_stock(database):
    database.save_group(OPTICS)
    database.save_group(POWER)
    groups = database.groups_for("3081")
    assert [group["id"] for group in groups] == ["ai-optics"]
    assert [(m["recordCode"], m["name"], m["role"]) for m in groups[0]["members"]] == [
        ("3081", "聯亞", "InP 磊晶"), ("LITE-US", "Lumentum", "雷射晶片與模組")]
    assert database.groups_for("2301")[0]["diagram"] == "power-rack"
    assert database.groups_for("3008") == []


def test_stocks_are_entities_kept_after_leaving_a_group(database):
    database.save_group(OPTICS)
    database.save_group({**OPTICS, "members": OPTICS["members"][:1]})  # LITE removed from the group
    assert [m["recordCode"] for m in database.groups_for("3081")[0]["members"]] == ["3081"]
    assert database.instrument("LITE-US") == {"recordCode": "LITE-US", "code": "LITE", "market": "US", "name": "Lumentum"}


def test_saving_a_group_twice_is_idempotent(database):
    database.save_group(OPTICS)
    database.save_group(OPTICS)
    assert len(database.groups_for("LITE-US")[0]["members"]) == 2
    assert [group["id"] for group in database.list_groups()] == ["ai-optics"]


@pytest.mark.parametrize("bad", [
    {**OPTICS, "id": "Bad Id!"},
    {**OPTICS, "members": [{"recordCode": "3081;drop", "name": "x", "market": "TW", "role": ""}]},
    {**OPTICS, "members": []},
    {**OPTICS, "name": {"zh": "", "en": "x"}},
])
def test_invalid_groups_are_rejected(bad):
    with pytest.raises(ValueError):
        validate_group(bad)


def test_bundled_groups_cover_every_current_research_record():
    groups = market_research.load_industry_groups()
    for group in groups:
        validate_group(group)
    grouped = {member["recordCode"] for group in groups for member in group["members"]}
    held = set(market_research.load_seed_records()) - {"TXF"}  # the index future is not a company
    assert held <= grouped, sorted(held - grouped)
    assert next(group for group in groups if group["id"] == "dc-power-rack")["diagram"] == "power-rack"


def test_api_lists_groups_for_a_stock_and_requires_login_to_write(database, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_industry_db", database)
    app = FastAPI()
    app.include_router(market.router)
    client = TestClient(app)
    assert client.put("/market/dashboard/industries/ai-optics", json=OPTICS).status_code == 401
    app.dependency_overrides[market.require_authenticated] = lambda: {"sub": "owner"}
    assert client.put("/market/dashboard/industries/ai-optics", json={**OPTICS, "id": "other"}).status_code == 422
    assert client.put("/market/dashboard/industries/ai-optics", json=OPTICS).status_code == 200
    body = client.get("/market/dashboard/industries?code=LITE-US").json()
    assert [group["id"] for group in body["groups"]] == ["ai-optics"]
    assert [group["id"] for group in client.get("/market/dashboard/industries").json()["groups"]] == ["ai-optics"]


def test_seeding_creates_missing_groups_and_never_overwrites_edited_ones(database):
    assert market_research.seed_industry_groups(database, [OPTICS, POWER]) == {"inserted": 2, "kept": 0}
    database.save_group({**OPTICS, "members": OPTICS["members"][:1]})  # edited through the API
    assert market_research.seed_industry_groups(database, [OPTICS, POWER]) == {"inserted": 0, "kept": 2}
    assert len(database.group("ai-optics")["members"]) == 1
