"""2026-11-19: the Maya v2 API was removed with the v2 chat UI; only /qa/query answers questions."""
from maya_sawa.main import app


def test_no_maya_v2_routes_remain_and_the_qa_flow_does():
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not [path for path in paths if path.startswith("/maya-v2")]
    assert "/qa/query" in paths or any(path.endswith("/qa/query") for path in paths)
