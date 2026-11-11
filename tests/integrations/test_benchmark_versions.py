from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa import benchmark_versions as versions
from maya_sawa.api import tw_benchmark


def test_every_version_is_a_complete_lineup():
    assert [v["version"] for v in versions.VERSIONS] == [1, 2, 3, 4, 5]
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


def test_version_three_keeps_only_the_leader_of_each_stage():
    # 2026-11-10: benchmarks set the guidance and cycle tone; they are not purchase candidates, so no peers.
    stages = [stage for layer in versions.definition(versions.VERSIONS[2])["layers"] for stage in layer["stages"]]
    assert len(stages) == 12
    assert all([company["role"] for company in stage["companies"]] == [versions.LEADER] for stage in stages)


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
    assert recorded == [1, 2, 3, 4, 5]
    upserted = {params["code"] for sql, params in calls if "INSERT INTO benchmark\n" in sql}
    assert upserted == {row["code"] for row in versions.members(versions.VERSIONS[-1])}
    retire = [params for sql, params in calls if "SET is_active=FALSE" in sql]
    assert len(retire) == 1 and "2379" not in retire[0]["codes"] and "2330" in retire[0]["codes"]


def test_an_applied_version_is_left_alone_so_manual_selection_survives(monkeypatch):
    calls = _sync(monkeypatch, 5)
    assert not any("INSERT INTO benchmark\n" in sql or "SET is_active=FALSE" in sql for sql, _ in calls)
    # the drawing of a version still follows the code, so a corrected diagram reaches the page
    refreshed = [sql for sql, _ in calls if "INSERT INTO benchmark_version" in sql]
    assert len(refreshed) == 5 and all("DO UPDATE SET" in sql for sql in refreshed)


def test_version_three_says_how_every_company_connects_to_another():
    # 2026-11-10: leaders sat side by side with no line between them; the picture has to show why each matters.
    drawing = versions.definition(versions.VERSIONS[2])
    codes = {row["code"] for row in versions.members(versions.VERSIONS[2])}
    ends = codes | {terminal["key"] for terminal in drawing["terminals"]}
    assert all(link["from"] in ends and link["to"] in ends and link["label"] for link in drawing["links"])
    assert codes <= {link["from"] for link in drawing["links"]} | {link["to"] for link in drawing["links"]}
    pairs = {(link["from"], link["to"]) for link in drawing["links"]}
    assert ("2454", "3443") not in pairs and ("3443", "2454") not in pairs
    assert versions.definition(versions.VERSIONS[0])["links"] == []


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


def test_version_four_adds_the_demand_side_and_overseas_leaders_each_with_its_own_annual_report():
    """2026-11-11: four CSPs are separate nodes because each one's annual report is read on its own."""
    from maya_sawa import overseas_benchmark_filings as overseas
    v4 = versions.VERSIONS[3]
    codes = [row["code"] for row in versions.members(v4)]
    added = {"GOOGL-US", "META-US", "MSFT-US", "AMZN-US", "NVDA-US", "000660-KR", "6857-JP"}
    assert added <= set(codes) and len(codes) == 19
    assert all(overseas.is_overseas(code) for code in added)
    assert all(code.isdigit() or overseas.is_overseas(code) for code in codes)  # every member has a report source
    demand = next(layer for layer in versions.definition(v4)["layers"] if layer["key"] == "demand")
    assert [len(stage["companies"]) for stage in demand["stages"]] == [4]
    stages = [stage for layer in versions.definition(v4)["layers"] for stage in layer["stages"] if stage["title"] != "雲端服務商"]
    assert all(len(stage["companies"]) == 1 for stage in stages)  # one leader per supply-chain stage


def test_version_four_connects_every_company():
    drawing = versions.definition(versions.VERSIONS[3])
    codes = {row["code"] for row in versions.members(versions.VERSIONS[3])}
    ends = codes | {terminal["key"] for terminal in drawing["terminals"]}
    assert all(link["from"] in ends and link["to"] in ends and link["label"] for link in drawing["links"])
    assert codes <= {link["from"] for link in drawing["links"]} | {link["to"] for link in drawing["links"]}


def test_version_five_adds_rack_components_each_with_an_annual_report_source():
    """2026-11-11: CCL, data-centre power, optical interconnect and passives; copper interconnect stays out."""
    from maya_sawa import overseas_benchmark_filings as overseas
    v5 = versions.VERSIONS[4]
    codes = [row["code"] for row in versions.members(v5)]
    assert len(codes) == 23 and len(set(codes)) == 23
    assert {"2383", "2308", "LITE-US", "6981-JP"} <= set(codes)
    assert set(row["code"] for row in versions.members(versions.VERSIONS[3])) <= set(codes)
    assert all(code.isdigit() or overseas.is_overseas(code) for code in codes)
    drawing = versions.definition(v5)
    ends = set(codes) | {terminal["key"] for terminal in drawing["terminals"]}
    assert all(link["from"] in ends and link["to"] in ends for link in drawing["links"])
    assert set(codes) <= {link["from"] for link in drawing["links"]} | {link["to"] for link in drawing["links"]}
    assert [layer["key"] for layer in drawing["layers"]][-2:] == ["rack", "demand"]
    assert "3665" not in codes  # copper cable: direction contested by copper-to-optics
