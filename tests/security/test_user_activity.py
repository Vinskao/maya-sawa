"""Who is this person and what did they create, read, update or delete (docs/USER_PERMISSIONS.md).

The identity is the Keycloak `sub`; the user table keeps only the user name and when they were first and last seen (no
email, no password, no token). The activity table is append-only: rows are never updated or deleted by the application.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.databases.user_activity_db import UserActivityDatabase

T0 = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def db():
    return UserActivityDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))


def test_a_user_is_remembered_by_sub_with_first_and_last_seen_and_the_latest_name(db):
    db.touch_user("sub-1", "alice", now=T0)
    db.touch_user("sub-1", "alice2", now=T0 + timedelta(days=2))
    db.touch_user("sub-2", "bob", now=T0 + timedelta(days=1))
    users = {u["sub"]: u for u in db.users()}
    assert users["sub-1"]["username"] == "alice2"
    assert users["sub-1"]["firstSeenAt"] == T0.isoformat() and users["sub-1"]["lastSeenAt"] == (T0 + timedelta(days=2)).isoformat()
    assert [u["sub"] for u in db.users()] == ["sub-1", "sub-2"]               # most recently seen first
    assert set(users["sub-1"]) == {"sub", "username", "firstSeenAt", "lastSeenAt", "activityCount"}      # nothing else is stored


def test_activity_is_recorded_per_user_newest_first_and_counted(db):
    db.touch_user("sub-1", "alice", now=T0)
    db.record("sub-1", "alice", "C", "report", "r1", {"title": "TSMC"}, request_id="req-1", now=T0)
    db.record("sub-1", "alice", "D", "report", "r1", now=T0 + timedelta(minutes=5))
    db.record("sub-2", "bob", "C", "learn-attempt", "q9", now=T0 + timedelta(minutes=1))
    mine = db.activity("sub-1")
    assert [(a["action"], a["resourceType"], a["resourceId"]) for a in mine] == [("D", "report", "r1"), ("C", "report", "r1")]
    assert mine[1]["detail"] == {"title": "TSMC"} and mine[1]["requestId"] == "req-1" and mine[1]["username"] == "alice"
    assert [a["sub"] for a in db.activity()] == ["sub-1", "sub-2", "sub-1"]       # everyone, newest first
    db.touch_user("sub-2", "bob", now=T0)
    assert {u["sub"]: u["activityCount"] for u in db.users()} == {"sub-1": 2, "sub-2": 1}
    assert len(db.activity("sub-1", limit=1)) == 1


def test_only_create_read_update_delete_are_accepted_and_bad_input_is_bounded(db):
    with pytest.raises(ValueError):
        db.record("sub-1", "alice", "X", "report", "r1")
    with pytest.raises(ValueError):
        db.record("", "alice", "C", "report", "r1")
    db.record("sub-1", "alice" * 100, "U", "report" * 50, "r" * 500, {"note": "x" * 5000}, now=T0)
    row = db.activity("sub-1")[0]
    assert len(row["username"]) <= 120 and len(row["resourceType"]) <= 60 and len(row["resourceId"]) <= 200
    assert len(str(row["detail"])) <= 1100


def test_a_page_of_activity_can_continue_before_an_id(db):
    for number in range(5):
        db.record("sub-1", "alice", "R", "learn-attempt", f"q{number}", now=T0 + timedelta(minutes=number))
    first = db.activity("sub-1", limit=2)
    second = db.activity("sub-1", limit=2, before_id=first[-1]["id"])
    assert [a["resourceId"] for a in first] == ["q4", "q3"] and [a["resourceId"] for a in second] == ["q2", "q1"]


def test_the_application_has_no_way_to_change_or_remove_an_activity_row(db):
    assert not any(name in dir(db) for name in ("update_activity", "delete_activity", "clear_activity", "purge"))
