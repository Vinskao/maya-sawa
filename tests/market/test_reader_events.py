"""North star metric: weekly returning research readers (docs/NORTH_STAR_METRIC.md).

A reader is an anonymous random id from the browser. A reader is active in a week when they opened an instrument's
research or AI analysis, or expanded a report's claims; they are returning when they also did so in the 28 days before
that week. Weeks run Monday to Sunday in Taipei time.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api import reader_events
from maya_sawa.databases.reader_events_db import ReaderEventDatabase

# Tuesday 2026-11-10 12:00 Taipei; that week is Monday 11-09 to Sunday 11-15.
NOW = datetime(2026, 11, 10, 4, 0, tzinfo=timezone.utc)
ALICE, BOB, CAROL = "a" * 32, "b" * 32, "c" * 32


def sqlite_db():
    return ReaderEventDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))


@pytest.fixture
def db():
    return sqlite_db()


def test_a_reader_who_also_read_in_the_previous_four_weeks_is_returning(db):
    db.record(ALICE, "research_open", "2330", now=NOW - timedelta(days=8))     # last week
    db.record(ALICE, "claims_open", "report-1", now=NOW)
    db.record(BOB, "analysis_open", "2454", now=NOW)                            # first time this week
    db.record(CAROL, "research_open", "2330", now=NOW - timedelta(days=45))     # older than four weeks before this week
    db.record(CAROL, "research_open", "2330", now=NOW)
    week = db.north_star(weeks=2, now=NOW)[0]
    assert (week["weekStart"], week["weekEnd"]) == ("2026-11-09", "2026-11-15")
    assert (week["activeReaders"], week["returningReaders"]) == (3, 1)
    assert week["events"] == {"analysis_open": 1, "claims_open": 1, "research_open": 1}


def test_searching_alone_does_not_make_someone_a_research_reader(db):
    db.record(ALICE, "hero_search", now=NOW - timedelta(days=7))
    db.record(ALICE, "hero_search", now=NOW)
    db.record(ALICE, "topic_pick", "cpo", now=NOW)
    week = db.north_star(weeks=1, now=NOW)[0]
    assert (week["activeReaders"], week["returningReaders"]) == (0, 0)
    assert week["events"] == {"hero_search": 1, "topic_pick": 1}                # still counted as secondary numbers


def test_reading_twice_in_the_same_week_is_not_a_return(db):
    db.record(ALICE, "research_open", "2330", now=NOW - timedelta(days=1))     # Monday of the same week
    db.record(ALICE, "research_open", "2330", now=NOW)
    week = db.north_star(weeks=1, now=NOW)[0]
    assert (week["activeReaders"], week["returningReaders"]) == (1, 0)
    assert week["events"] == {"research_open": 2}


def test_weeks_are_listed_newest_first_and_split_at_taipei_midnight(db):
    # Sunday 2026-11-08 23:30 Taipei belongs to the previous week; half an hour later is the new week.
    db.record(ALICE, "research_open", "2330", now=datetime(2026, 11, 8, 15, 30, tzinfo=timezone.utc))
    db.record(ALICE, "research_open", "2330", now=datetime(2026, 11, 8, 16, 30, tzinfo=timezone.utc))
    weeks = db.north_star(weeks=3, now=NOW)
    assert [w["weekStart"] for w in weeks] == ["2026-11-09", "2026-11-02", "2026-10-26"]
    assert [(w["activeReaders"], w["returningReaders"]) for w in weeks] == [(1, 1), (1, 0), (0, 0)]


def test_repeats_add_to_one_row_and_bad_or_excessive_input_is_refused(db):
    for _ in range(3):
        assert db.record(ALICE, "research_open", "2330", now=NOW) is True
    assert db.row_count() == 1
    for visitor, event, target in (("short", "research_open", ""), (ALICE, "page_view", ""), (ALICE + "!", "research_open", ""),
                                   (ALICE, "research_open", "x" * 81)):
        with pytest.raises(ValueError):
            db.record(visitor, event, target, now=NOW)
    for number in range(ReaderEventDatabase.DAILY_ROW_LIMIT + 5):                # one browser cannot fill the table
        db.record(BOB, "claims_open", f"report-{number}", now=NOW)
    assert db.row_count() == 1 + ReaderEventDatabase.DAILY_ROW_LIMIT
    assert db.record(BOB, "claims_open", "one-more", now=NOW) is False


def test_nothing_but_the_random_id_the_event_and_its_target_is_stored(db):
    db.record(ALICE, "research_open", "2330", now=NOW)
    assert set(db.columns()) == {"id", "visitor", "day", "event", "target", "count"}


OWNER = {"sub": "owner-sub", "_roles": ["manage-users"]}
MEMBER = {"sub": "alice-sub", "_roles": ["member"]}
INTERNAL = {"X-Internal-Secret": "s3cret"}
GOOD = {"visitor": ALICE, "event": "research_open", "target": "2330"}


@pytest.fixture
def web(monkeypatch):
    database = sqlite_db()
    monkeypatch.setattr(reader_events, "reader_events_db", database)
    monkeypatch.setenv("MARKET_INTERNAL_SECRET", "s3cret")
    app = FastAPI()
    app.include_router(reader_events.router)
    state = {"user": OWNER}

    def owner_only():
        if "manage-users" not in state["user"]["_roles"]:
            raise HTTPException(status_code=403, detail="Requires manage-users role")
        return state["user"]

    app.dependency_overrides[reader_events.require_manage_users_request] = owner_only
    client = TestClient(app)
    client.state, client.db = state, database
    return client


def test_only_the_frontend_server_can_record_reader_events(web):
    assert web.post("/market/internal/reader-events", json=GOOD).status_code == 422                  # header missing
    assert web.post("/market/internal/reader-events", json=GOOD, headers={"X-Internal-Secret": "no"}).status_code == 401
    ok = web.post("/market/internal/reader-events", json=GOOD, headers=INTERNAL)
    assert ok.status_code == 200 and ok.json() == {"recorded": True}
    assert web.db.row_count() == 1


def test_reader_event_input_is_validated(web):
    for bad in ({**GOOD, "visitor": "short"}, {**GOOD, "event": "page_view"}, {**GOOD, "target": "x" * 81},
                {**GOOD, "visitor": "has space " + ALICE}):
        assert web.post("/market/internal/reader-events", json=bad, headers=INTERNAL).status_code == 422
    assert web.db.row_count() == 0


def test_only_the_owner_reads_the_north_star(web):
    web.post("/market/internal/reader-events", json=GOOD, headers=INTERNAL)
    body = web.get("/market/admin/north-star?weeks=2").json()
    assert body["metric"] == "weekly_returning_research_readers"
    assert len(body["weeks"]) == 2 and body["weeks"][0]["activeReaders"] == 1
    assert web.get("/market/admin/north-star?weeks=0").status_code == 422
    web.state["user"] = MEMBER
    assert web.get("/market/admin/north-star").status_code == 403
