from types import SimpleNamespace
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import tw_benchmark
from maya_sawa.services import benchmark_analysis


def test_sync_seeds_once_and_uses_active_database_selection(monkeypatch):
    conn = Mock()
    conn.scalar.side_effect = [True, False]
    conn.begin_nested.return_value = _connection(Mock())
    active_rows = Mock()
    active_rows.mappings.return_value.all.return_value = [{"code": "2330"}]
    conn.execute.side_effect = lambda query, *args, **kwargs: (
        active_rows if "SELECT code FROM benchmark WHERE is_active=TRUE" in str(query) else Mock()
    )
    engine = Mock()
    engine.connect.return_value = _connection(conn)
    monkeypatch.setattr(tw_benchmark.market_dashboard_db, "engine", engine)
    monkeypatch.setattr(tw_benchmark, "process_annual_filings", Mock())
    monkeypatch.setattr(tw_benchmark, "listing", lambda code, year, kind: ("source", []))

    tw_benchmark.sync()

    statements = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert any("SELECT code FROM benchmark WHERE is_active=TRUE" in sql for sql in statements)
    assert not any("ON CONFLICT (code) DO UPDATE" in sql for sql in statements)


def test_analysis_queue_only_selects_current_benchmarks(monkeypatch):
    monkeypatch.setattr(benchmark_analysis.Config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(benchmark_analysis, "OpenAI", Mock())
    conn = Mock()
    conn.execute.return_value.mappings.return_value.all.return_value = []

    benchmark_analysis.process_annual_filings(conn)

    query = str(conn.execute.call_args.args[0])
    assert "b.is_active=TRUE" in query


def test_selection_endpoint_requires_agent_and_updates_database(monkeypatch):
    app = FastAPI()
    app.include_router(tw_benchmark.router)
    conn = Mock()
    conn.execute.return_value.rowcount = 1
    engine = SimpleNamespace(begin=lambda: _connection(conn))
    monkeypatch.setattr(tw_benchmark.market_dashboard_db, "engine", engine)
    monkeypatch.setattr(tw_benchmark, "_verify_agent", lambda key: _verify(key))
    client = TestClient(app)

    assert client.put("/market/benchmark/2330/selection", json={"active": False}).status_code == 401
    response = client.put("/market/benchmark/2330/selection", headers={"X-Market-Agent-Key": "valid"},
                          json={"active": False})
    assert response.status_code == 200
    assert response.json() == {"code": "2330", "is_active": False}


class _connection:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_):
        pass


def _verify(key):
    from fastapi import HTTPException

    if key != "valid":
        raise HTTPException(401)
