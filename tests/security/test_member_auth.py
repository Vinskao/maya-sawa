"""Roles on the site (docs/USER_PERMISSIONS.md): `manage-users` is the owner; `member` is what every self-registered
account gets and may only upload reports and take /learn; a signed-in user with neither role may do neither."""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from maya_sawa.core.auth import keycloak


def app_with(monkeypatch, roles):
    monkeypatch.setattr(keycloak, "verify_bearer_token", lambda token: {"sub": "u1", "_roles": roles})
    app = FastAPI()

    @app.get("/member")
    async def member(claims=Depends(keycloak.require_member_request)):
        return {"sub": claims["sub"]}

    @app.get("/owner")
    async def owner(claims=Depends(keycloak.require_manage_users_request)):
        return {"sub": claims["sub"]}

    return TestClient(app)


def test_the_member_role_name_is_configurable_and_defaults_to_member():
    assert keycloak.Config.MEMBER_ROLE == "member"
    assert keycloak.Config.GIT_COMMIT_REQUIRED_ROLE == "manage-users"


@pytest.mark.parametrize("roles,member_ok,owner_ok", [
    (["member"], True, False),
    (["manage-users"], True, True),       # the owner may do everything a member may, and the owner-only things too
    ([], False, False),
    (["offline_access", "uma_authorization"], False, False),
])
def test_member_and_owner_routes(monkeypatch, roles, member_ok, owner_ok):
    client = app_with(monkeypatch, roles)
    headers = {"Authorization": "Bearer t"}
    assert (client.get("/member", headers=headers).status_code == 200) is member_ok
    assert (client.get("/owner", headers=headers).status_code == 200) is (owner_ok if "manage-users" in roles else False)


def test_no_token_is_401_and_a_signed_in_user_without_the_role_is_403(monkeypatch):
    client = app_with(monkeypatch, [])
    assert client.get("/member").status_code == 401
    assert client.get("/member", headers={"Authorization": "Bearer t"}).status_code == 403


def test_a_member_cannot_reach_an_owner_route(monkeypatch):
    assert app_with(monkeypatch, ["member"]).get("/owner", headers={"Authorization": "Bearer t"}).status_code == 403
