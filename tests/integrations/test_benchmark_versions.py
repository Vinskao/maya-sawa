from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa import benchmark_versions as versions
from maya_sawa.api import tw_benchmark


def test_every_version_is_a_complete_lineup():
    assert [v["version"] for v in versions.VERSIONS] == [1, 2]
    for version in versions.VERSIONS:
        rows = versions.members(version)
        codes = [row["code"] for row in rows]
        assert len(codes) == len(set(codes))
        assert all(len(row["significance"]) >= 10 and row["segment"] for row in rows)
        keys = {layer["key"] for layer in versions.definition(version)["layers"]}
        assert all(flow["from"] in keys and flow["to"] in keys for flow in version["flows"])
    assert len(versions.members(versions.VERSIONS[0])) == 16


def test_version_two_pairs_a_leader_with_a_peer_in_every_stage():
    stages = [stage for layer in versions.definition(versions.VERSIONS[1])["layers"] for stage in layer["stages"]]
    assert len(stages) == 11
    for stage in stages:
        assert [company["role"] for company in stage["companies"]] == [versions.LEADER, versions.PEER]
    titles = {stage["title"] for stage in stages}
    assert {"記憶體", "矽智財與 ASIC 設計服務", "測試介面", "IC 載板"} <= titles


def _sync(monkeypatch, applied):
    conn = Mock()
    conn.scalar.side_effect = [True, applied]
    conn.begin_nested.return_value = _connection(Mock())
    active = Mock()
    active.mappings.return_value.all.return_value = []
    conn.execute.side_effect = lambda query, *args, **kwargs: (
        active if "SELECT code FROM benchmark WHERE is_active=TRUE" in str(query) else Mock())
    engine = Mock()
    engine.connect.return_value = _connection(conn)
    monkeypatch.setattr(tw_benchmark.market_dashboard_db, "engine", engine)
    monkeypatch.setattr(tw_benchmark, "process_annual_filings", Mock())
    tw_benchmark.sync()
    return [(str(call.args[0]), call.args[1] if len(call.args) > 1 else {}) for call in conn.execute.call_args_list]


def test_a_new_version_is_applied_once_and_retires_companies_it_drops(monkeypatch):
    calls = _sync(monkeypatch, 1)
    recorded = [params["version"] for sql, params in calls if "INSERT INTO benchmark_version" in sql]
    assert recorded == [1, 2]
    upserted = {params["code"] for sql, params in calls if "INSERT INTO benchmark\n" in sql}
    assert upserted == {row["code"] for row in versions.members(versions.VERSIONS[1])}
    retire = [params for sql, params in calls if "SET is_active=FALSE" in sql]
    assert len(retire) == 1 and "6937" not in retire[0]["codes"] and "2330" in retire[0]["codes"]


def test_an_applied_version_is_left_alone_so_manual_selection_survives(monkeypatch):
    calls = _sync(monkeypatch, 2)
    assert not any("INSERT INTO benchmark" in sql or "SET is_active=FALSE" in sql for sql, _ in calls)


def test_versions_endpoint_lists_newest_first_and_marks_the_current_one(monkeypatch):
    conn = Mock()
    conn.scalar.return_value = "benchmark_version"
    conn.execute.return_value.mappings.return_value = [
        {"version": 2, "name": "b", "rationale": "r2", "definition": {"layers": [], "flows": []}, "adopted_at": None},
        {"version": 1, "name": "a", "rationale": "r1", "definition": {"layers": [], "flows": []}, "adopted_at": None},
    ]
    monkeypatch.setattr(tw_benchmark.market_dashboard_db, "engine", SimpleNamespace(connect=lambda: _connection(conn)))
    app = FastAPI()
    app.include_router(tw_benchmark.router)
    body = TestClient(app).get("/market/benchmark/versions").json()
    assert [(v["version"], v["is_current"]) for v in body] == [(2, True), (1, False)]
    assert body[0]["layers"] == [] and body[0]["rationale"] == "r2"


def test_public_list_shows_only_the_current_lineup():
    import inspect
    assert "WHERE b.is_active" in inspect.getsource(tw_benchmark.benchmark_list)


class _connection:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_):
        pass
