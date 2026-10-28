"""The API page lists the routes that say they are public, by themselves; these tests keep that opt-in honest."""
import inspect

import pytest
from fastapi import Depends, FastAPI, Header
from fastapi.routing import APIRoute

from maya_sawa.core import public_api
from maya_sawa.core.public_api import public_data


@pytest.fixture(scope="module")
def app():
    from maya_sawa.main import app as application
    return application


def marked_routes(app):
    return [route for route in app.routes if isinstance(route, APIRoute) and (route.openapi_extra or {}).get(public_api.MARK)]


def dependency_names(dependant):
    names = []
    for sub in dependant.dependencies:
        names.append(getattr(sub.call, "__name__", str(sub.call)))
        names += dependency_names(sub)
    return names


def test_a_marked_route_appears_by_itself_and_an_unmarked_one_never_does():
    tiny = FastAPI()

    @tiny.get("/market/new-thing/{code}", **public_data("新的公開資料", "行情與標的"))
    async def new_thing(code: str, since: str | None = None):
        return {}

    @tiny.get("/market/portfolio")
    async def portfolio():
        return {}

    @tiny.post("/market/notify", **public_data("寫入不能公開", "x"))
    async def notify():
        return {}
    spec = public_api.build_public_openapi(tiny)
    assert list(spec["paths"]) == ["/market/new-thing/{code}"]
    operation = spec["paths"]["/market/new-thing/{code}"]["get"]
    assert operation["summary"] == "新的公開資料" and operation["x-group"] == "行情與標的" and operation["tags"] == ["行情與標的"]
    assert {(p["name"], p["in"]) for p in operation["parameters"]} == {("code", "path"), ("since", "query")}


def test_every_marked_route_in_the_real_app_is_a_get_with_no_login_or_key(app):
    routes = marked_routes(app)
    assert len(routes) >= 15
    for route in routes:
        assert route.methods == {"GET"}, f"{route.path} is public but not read-only"
        summary = route.summary or ""
        assert any("一" <= ch <= "鿿" for ch in summary), f"{route.path} needs a Chinese summary"
        names = " ".join(dependency_names(route.dependant)).lower()
        assert not any(word in names for word in ("require", "verify", "authenticated", "internal")), f"{route.path} depends on {names}"
        source = inspect.getsource(route.endpoint).lower()
        # An inline agent-key / secret check does not show up as a dependency, so look at the handler itself.
        # (a mention of the key in a description of the write route is fine; reading a header or comparing a digest is not)
        assert not any(marker in source for marker in ("headers.get(", "header(", "_verify_agent(", "require_internal", "compare_digest")), f"{route.path} checks a key inline"


def test_the_guard_would_catch_a_route_that_is_marked_by_mistake():
    guarded = FastAPI()

    def require_owner(authorization: str | None = Header(None)):
        return authorization

    @guarded.get("/market/portfolio", **public_data("持股", "x"), dependencies=[Depends(require_owner)])
    async def portfolio():
        return {}
    route = marked_routes(guarded)[0]
    assert "require_owner" in dependency_names(route.dependant)          # what the real-app test above would reject


def test_nothing_that_writes_or_belongs_to_the_owner_is_marked(app):
    paths = [route.path for route in marked_routes(app)]
    assert len(paths) == len(set(paths))
    for forbidden in ("/market/portfolio", "/market/ibkr", "/market/usage", "/market/notifications", "/market/auth-status", "/market/internal",
                      "/market/reports/pending", "/market/dashboard/custom", "/market/dashboard/candidates", "/market/dashboard/search",
                      "/market/reports/search", "/market/routine-usage"):
        assert not any(path.startswith(forbidden) for path in paths), forbidden


def test_the_public_spec_has_only_marked_gets_and_no_schemas(app):
    spec = public_api.build_public_openapi(app)
    assert set(spec["paths"]) == {route.path for route in marked_routes(app)}
    assert spec["servers"] == [{"url": "/maya-sawa"}] and "components" not in spec
    for operations in spec["paths"].values():
        assert list(operations) == ["get"]
        operation = operations["get"]
        assert "requestBody" not in operation and "security" not in operation and operation["x-group"]
        assert all("$ref" not in parameter for parameter in operation["parameters"])
        assert all(set(r) == {"description"} for r in operation["responses"].values())
    history = spec["paths"]["/market/dashboard/history/{code}"]["get"]
    assert {(p["name"], p["in"]) for p in history["parameters"]} >= {("code", "path"), ("start", "query"), ("end", "query")}


def test_the_spec_endpoint_is_public_and_not_listed_in_the_full_schema(app):
    from fastapi.testclient import TestClient
    client = TestClient(app)
    reply = client.get("/public-openapi.json")
    assert reply.status_code == 200 and reply.json()["info"]["title"].startswith("TY 市場研究室")
    assert "/public-openapi.json" not in client.get("/openapi.json").json()["paths"]
