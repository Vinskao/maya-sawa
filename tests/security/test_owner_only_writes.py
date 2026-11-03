"""A signed-in member may upload reports and take /learn, nothing else (docs/USER_PERMISSIONS.md).

Before 2026-11-03 these accepted any signed-in account, and Keycloak self-registration is open, so a new account could write the
public AI analysis of any stock, edit the industry groups and read the RunPod bill.
"""
import hashlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from maya_sawa.api import market, runpod
from maya_sawa.core.auth import keycloak

BEARER = {"Authorization": "Bearer t"}


def with_roles(monkeypatch, roles):
    monkeypatch.setattr(keycloak, "verify_bearer_token", lambda token: {"sub": "u1", "preferred_username": "someone", "_roles": roles})


def editor_app():
    app = FastAPI()

    @app.get("/editor")
    async def editor(who=Depends(market.analysis_editor)):
        return {"editor": who}

    return TestClient(app)


def test_only_the_owner_or_the_agent_key_may_write_an_ai_analysis(monkeypatch):
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(b"k").hexdigest())
    client = editor_app()
    with_roles(monkeypatch, ["member"])
    assert client.get("/editor", headers=BEARER).status_code == 403                    # a member: no
    with_roles(monkeypatch, [])
    assert client.get("/editor", headers=BEARER).status_code == 403                    # a registered account without roles: no
    assert client.get("/editor").status_code == 401                                    # signed out
    with_roles(monkeypatch, ["manage-users"])
    assert client.get("/editor", headers=BEARER).json() == {"editor": "u1"}            # the owner
    assert client.get("/editor", headers={"x-market-agent-key": "k"}).json() == {"editor": market.AGENT_EDITOR}   # the routine
    assert client.get("/editor", headers={"x-market-agent-key": "wrong"}).status_code == 401


def test_a_member_cannot_edit_industry_groups_or_read_the_runpod_cost(monkeypatch):
    app = FastAPI()
    app.include_router(market.router)
    app.include_router(runpod.router)
    client = TestClient(app)
    with_roles(monkeypatch, ["member"])
    assert client.put("/market/dashboard/industries/any", json={"name": "x"}, headers=BEARER).status_code == 403
    cost_paths = [route.path for route in runpod.router.routes if "cost" in route.path]
    assert cost_paths
    assert client.get(cost_paths[0], headers=BEARER).status_code == 403
    with_roles(monkeypatch, [])
    assert client.put("/market/dashboard/industries/any", json={"name": "x"}, headers=BEARER).status_code == 403
