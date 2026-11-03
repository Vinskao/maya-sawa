"""The owner reads who the users are and what they did; the Java backend reports /learn activity into the same log."""
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api import admin_users
from maya_sawa.databases.user_activity_db import UserActivityDatabase

OWNER = {"sub": "owner-sub", "_roles": ["manage-users"]}
MEMBER = {"sub": "alice-sub", "_roles": ["member"]}


@pytest.fixture
def web(monkeypatch):
    db = UserActivityDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))
    monkeypatch.setattr(admin_users, "user_activity_db", db)
    monkeypatch.setenv("MARKET_INTERNAL_SECRET", "s3cret")
    app = FastAPI()
    app.include_router(admin_users.router)
    state = {"user": OWNER}

    def owner_only():
        if "manage-users" not in state["user"]["_roles"]:
            raise HTTPException(status_code=403, detail="Requires manage-users role")
        return state["user"]

    app.dependency_overrides[admin_users.require_manage_users_request] = owner_only
    client = TestClient(app)
    client.state, client.db = state, db
    return client


GOOD = {"sub": "alice-sub", "username": "alice", "action": "C", "resourceType": "learn-attempt", "resourceId": "toeic-1:q7",
        "detail": {"correct": True, "setId": "toeic-1"}}
INTERNAL = {"X-Internal-Secret": "s3cret"}


def test_the_learn_backend_reports_activity_with_the_internal_secret_only(web):
    assert web.post("/market/internal/activity", json=GOOD).status_code == 422                       # header missing
    assert web.post("/market/internal/activity", json=GOOD, headers={"X-Internal-Secret": "nope"}).status_code == 401
    ok = web.post("/market/internal/activity", json=GOOD, headers=INTERNAL)
    assert ok.status_code == 200 and ok.json()["recorded"] is True
    row = web.db.activity("alice-sub")[0]
    assert (row["action"], row["resourceType"], row["resourceId"], row["detail"]["correct"]) == ("C", "learn-attempt", "toeic-1:q7", True)
    assert [u["sub"] for u in web.db.users()] == ["alice-sub"]                                          # first seen through /learn


def test_internal_activity_input_is_validated(web):
    for bad in ({**GOOD, "action": "X"}, {**GOOD, "sub": ""}, {**GOOD, "resourceType": ""}, {**GOOD, "resourceId": "r" * 300},
                {**GOOD, "username": "u" * 200}):
        assert web.post("/market/internal/activity", json=bad, headers=INTERNAL).status_code == 422
    assert web.db.activity() == []


def test_only_the_owner_can_list_users_and_read_their_activity(web):
    web.post("/market/internal/activity", json=GOOD, headers=INTERNAL)
    web.post("/market/internal/activity", json={**GOOD, "action": "R", "resourceId": "toeic-1:q8"}, headers=INTERNAL)
    users = web.get("/market/admin/users").json()["users"]
    assert users[0]["sub"] == "alice-sub" and users[0]["activityCount"] == 2 and "email" not in users[0]
    activity = web.get("/market/admin/users/alice-sub/activity?limit=1").json()
    assert len(activity["activity"]) == 1 and activity["activity"][0]["action"] == "R"
    older = web.get(f"/market/admin/users/alice-sub/activity?limit=5&before_id={activity['activity'][0]['id']}").json()["activity"]
    assert [a["resourceId"] for a in older] == ["toeic-1:q7"]
    web.state["user"] = MEMBER
    assert web.get("/market/admin/users").status_code == 403
    assert web.get("/market/admin/users/alice-sub/activity").status_code == 403


def test_the_owner_can_read_all_recent_activity_across_users(web):
    web.post("/market/internal/activity", json=GOOD, headers=INTERNAL)
    web.post("/market/internal/activity", json={**GOOD, "sub": "bob-sub", "username": "bob"}, headers=INTERNAL)
    recent = web.get("/market/admin/activity").json()["activity"]
    assert [a["sub"] for a in recent] == ["bob-sub", "alice-sub"]
