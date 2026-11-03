"""Adding a stock to the dashboard fills its data and starts its first AI analysis right away."""
import asyncio
from datetime import date, datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from maya_sawa.api import market
from maya_sawa.services import market_automation as automation
from maya_sawa.services.market_automation import TAIPEI, AutomationStore


@pytest.fixture
def api(monkeypatch):
    saved = {"symbols": [{"code": "2330", "name": "台積電", "productType": "stock"}]}
    calls = {"stocks": [], "futures": [], "added": []}

    async def search(code, kind):
        names = {"2330": "台積電", "2408": "南亞科", "3081": "聯亞", "CDFK6": "台積電期貨"}
        return [{"code": code, "name": names[code]}] if code in names else []

    async def enqueue_codes(codes):
        calls["stocks"].append(codes)

    async def enqueue_futures(items):
        calls["futures"].append([item["code"] for item in items])

    def start(items):
        calls["added"].append([item["code"] for item in items])

    monkeypatch.setattr(market.market_dashboard_db, "latest_auto", lambda: {"positions": [{"code": "3711"}]})
    monkeypatch.setattr(market.market_dashboard_db, "custom_symbols", lambda: saved["symbols"])
    monkeypatch.setattr(market.market_dashboard_db, "save_custom_symbols", lambda rows: saved.update(symbols=rows))
    monkeypatch.setattr(market.market_dashboard_db, "find_candidate", lambda kind, code: None)
    monkeypatch.setattr(market.shioaji_market_service, "search_contracts", search)
    monkeypatch.setattr(market.market_history_collector, "enqueue_codes", enqueue_codes)
    monkeypatch.setattr(market.market_history_collector, "enqueue_futures", enqueue_futures)
    monkeypatch.setattr(market, "start_added_analysis", start, raising=False)
    app = FastAPI()
    app.include_router(market.router)
    app.dependency_overrides[market.require_manage_users_request] = lambda: {"sub": "owner"}
    return TestClient(app), saved, calls


def put(client, *items):
    return client.put("/market/dashboard/custom", json={"symbols": [
        {"code": code, "name": code, "productType": kind} for code, kind in items]})


def test_save_keeps_validated_names_and_fills_history_as_before(api):
    client, saved, calls = api
    response = put(client, ("2330", "stock"), ("2408", "stock"), ("CDFK6", "futures"))
    assert response.status_code == 200
    assert [row["name"] for row in saved["symbols"]] == ["台積電", "南亞科", "台積電期貨"]
    assert calls["stocks"] == [["2330", "2408"]] and calls["futures"] == [["CDFK6"]]
    assert put(client, ("9999", "stock")).status_code == 422  # unknown contract
    assert put(client, ("3711", "stock")).status_code == 422  # already in the automatic selection


def test_only_newly_added_instruments_start_an_analysis(api):
    client, _, calls = api
    response = put(client, ("2330", "stock"), ("2408", "stock"), ("3081", "stock"))
    assert response.json()["added"] == ["2408", "3081"]
    assert calls["added"] == [["2408", "3081"]]
    response = put(client, ("2408", "stock"))  # removing one is not an addition
    assert response.json()["added"] == [] and calls["added"] == [["2408", "3081"]]


NOW = datetime(2026, 10, 25, 10, 0, tzinfo=TAIPEI).astimezone(timezone.utc)
ADDED = [{"code": "2408", "name": "南亞科", "productType": "stock"}, {"code": "CDFK6", "name": "台積電期貨", "productType": "futures"}]


def store(tmp_path):
    return AutomationStore(create_engine(f"sqlite:///{tmp_path / 'fires.db'}"))


def test_data_is_collected_before_the_routine_is_fired_for_just_the_new_codes(tmp_path, monkeypatch):
    order = []

    async def collect(items):
        order.append(("collect", [item["code"] for item in items]))

    async def fire(run, text):
        order.append(("fire", run.key, text))
        return "https://claude.ai/code/session_x"

    monkeypatch.setattr(automation, "fire_routine", fire)
    monkeypatch.setenv("MARKET_ROUTINE_TAIWAN_TOKEN", "test-token")
    fires = store(tmp_path)
    result = asyncio.run(automation.analyze_added(fires, ADDED, collect, NOW))
    assert result == {"state": "fired", "codes": ["2408", "CDFK6"], "sessionUrl": "https://claude.ai/code/session_x"}
    assert order[0] == ("collect", ["2408", "CDFK6"])
    assert order[1][:2] == ("fire", "taiwan")
    assert "2408 南亞科（stock）" in order[1][2] and "CDFK6 台積電期貨（futures）" in order[1][2]
    assert "只" in order[1][2]  # scoped to the new codes, not a full rerun
    # Saving the list again the same day does not start another run for the same codes.
    again = asyncio.run(automation.analyze_added(fires, ADDED, collect, NOW))
    assert again["state"] == "done" and len([step for step in order if step[0] == "fire"]) == 1
    assert "taiwan" not in fires.last_fired()  # the daily schedule's own claims are untouched


def test_collection_failure_still_fires_and_fire_failure_is_retried_on_the_next_save(tmp_path, monkeypatch):
    async def broken_collect(items):
        raise RuntimeError("TWSE down")

    fired = []

    async def fire(run, text):
        fired.append(text)
        if len(fired) == 1:
            raise RuntimeError("routine API down")
        return ""

    monkeypatch.setattr(automation, "fire_routine", fire)
    monkeypatch.setenv("MARKET_ROUTINE_TAIWAN_TOKEN", "test-token")
    fires = store(tmp_path)
    assert asyncio.run(automation.analyze_added(fires, ADDED[:1], broken_collect, NOW))["state"] == "error"
    assert asyncio.run(automation.analyze_added(fires, ADDED[:1], broken_collect, NOW))["state"] == "fired"
    assert len(fired) == 2


def test_without_a_routine_token_nothing_is_claimed(tmp_path, monkeypatch):
    collected = []

    async def collect(items):
        collected.append(items)

    monkeypatch.delenv("MARKET_ROUTINE_TAIWAN_TOKEN", raising=False)
    fires = store(tmp_path)
    assert asyncio.run(automation.analyze_added(fires, ADDED, collect, NOW))["state"] == "not-configured"
    assert collected == [ADDED]  # the data is still filled in
    assert fires.last_fired() == {}
    assert asyncio.run(automation.analyze_added(fires, [], collect, NOW)) == {"state": "nothing-added", "codes": []}
