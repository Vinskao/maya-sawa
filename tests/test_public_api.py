"""The API page lists only the market-data endpoints anyone may read. The list is an explicit opt-in, and these tests keep it honest."""
import inspect

import pytest
from fastapi.routing import APIRoute

from maya_sawa.core import public_api


@pytest.fixture(scope="module")
def app():
    from maya_sawa.main import app as application
    return application


def route_for(app, path):
    return next((route for route in app.routes if isinstance(route, APIRoute) and route.path == path and "GET" in route.methods), None)


def dependency_names(dependant):
    names = []
    for sub in dependant.dependencies:
        names.append(getattr(sub.call, "__name__", str(sub.call)))
        names += dependency_names(sub)
    return names


def test_every_listed_endpoint_exists_is_a_get_and_needs_no_login(app):
    for path, summary in public_api.PUBLIC_DATA:
        route = route_for(app, path)
        assert route is not None, f"{path} is listed as public but is not a GET route"
        assert summary and any("一" <= ch <= "鿿" for ch in summary), f"{path} needs a Chinese summary"
        names = " ".join(dependency_names(route.dependant)).lower()
        assert not any(word in names for word in ("require", "verify", "authenticated", "internal")), f"{path} depends on {names}"
        source = inspect.getsource(route.endpoint).lower()
        # An inline agent-key / secret check does not show up as a dependency, so look at the handler itself.
        # (a mention of the key in a description of the write route is fine; reading a header or comparing a digest is not)
        assert not any(marker in source for marker in ("headers.get(", "header(", "_verify_agent(", "require_internal", "compare_digest")), f"{path} checks a key inline"


def test_nothing_that_writes_or_belongs_to_the_owner_is_listed():
    paths = [path for path, _ in public_api.PUBLIC_DATA]
    assert len(paths) == len(set(paths))
    for forbidden in ("/market/portfolio", "/market/ibkr", "/market/usage", "/market/notifications", "/market/auth-status", "/market/internal",
                      "/market/reports/pending", "/market/dashboard/custom", "/market/dashboard/candidates", "/market/dashboard/search",
                      "/market/reports/search", "/market/routine-usage"):
        assert not any(path.startswith(forbidden) for path in paths), forbidden


def test_the_public_spec_has_only_those_gets_with_summaries_and_no_schemas(app):
    spec = public_api.build_public_openapi(app)
    assert set(spec["paths"]) == {path for path, _ in public_api.PUBLIC_DATA}
    assert spec["servers"] == [{"url": "/maya-sawa"}]
    assert "components" not in spec
    for path, summary in public_api.PUBLIC_DATA:
        operations = spec["paths"][path]
        assert list(operations) == ["get"], path
        operation = operations["get"]
        assert operation["summary"] == summary and "requestBody" not in operation and "security" not in operation
        assert all("$ref" not in parameter for parameter in operation.get("parameters", []))
        assert set(operation["responses"]) <= {"200", "404", "422", "503"} and all(set(r) == {"description"} for r in operation["responses"].values())
    history = spec["paths"]["/market/dashboard/history/{code}"]["get"]
    assert {(p["name"], p["in"]) for p in history["parameters"]} >= {("code", "path"), ("start", "query"), ("end", "query")}


def test_the_spec_endpoint_is_public_and_not_listed_in_the_full_schema(app):
    from fastapi.testclient import TestClient
    client = TestClient(app)
    reply = client.get("/public-openapi.json")
    assert reply.status_code == 200 and reply.json()["info"]["title"].startswith("TY 市場研究室")
    assert "/public-openapi.json" not in client.get("/openapi.json").json()["paths"]
