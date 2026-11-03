"""Members may upload reports, but the owner decides what becomes public (docs/USER_PERMISSIONS.md).

A member's upload is private to its uploader until the owner approves it; until then it never reaches the claim extraction
routine, the public report list, the public claims or the watch-list nominations. Members are limited to 5 uploads a day (Taipei).
Every create / update / delete is written to the user activity log.
"""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api import market_reports
from maya_sawa.databases.market_reports_db import MarketReportsDatabase
from maya_sawa.databases.user_activity_db import UserActivityDatabase

_spec = importlib.util.spec_from_file_location("tmr", Path(__file__).parent / "test_market_reports.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
text_pdf = _module.text_pdf

ALICE = {"sub": "alice-sub", "preferred_username": "alice", "_roles": ["member"]}
BOB = {"sub": "bob-sub", "preferred_username": "bob", "_roles": ["member"]}
OWNER = {"sub": "owner-sub", "preferred_username": "vinskao", "_roles": ["manage-users"]}
NOBODY = {"sub": "nobody-sub", "preferred_username": "nobody", "_roles": ["offline_access"]}
TEXT = "Memory makers expect tight supply through 2027."
NOON = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)   # 12:00 Taipei


class Site:
    def __init__(self, monkeypatch):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.reports, self.activity = MarketReportsDatabase(engine), UserActivityDatabase(engine)
        monkeypatch.setattr(market_reports, "market_reports_db", self.reports)
        monkeypatch.setattr(market_reports, "user_activity_db", self.activity)
        monkeypatch.setattr(market_reports, "_now", lambda: self.now)
        monkeypatch.setattr(market_reports, "get_embedding_service", lambda: type("E", (), {"embed_documents": lambda self, texts: [[0.0] * 1536 for _ in texts]})())
        self.now, self.user = NOON, ALICE
        self.app = FastAPI()
        self.app.include_router(market_reports.router)

        def owner_only():
            if "manage-users" not in self.user["_roles"]:
                raise HTTPException(status_code=403, detail="Requires manage-users role")
            return self.user

        def member_or_owner():
            if not set(self.user["_roles"]) & {"member", "manage-users"}:
                raise HTTPException(status_code=403, detail="Requires member role")
            return self.user

        self.app.dependency_overrides[market_reports.require_manage_users_request] = owner_only
        self.app.dependency_overrides[market_reports.require_member_request] = member_or_owner
        self.app.dependency_overrides[market_reports._optional_owner] = lambda: self.user
        self.client = TestClient(self.app)

    def as_user(self, claims):
        self.user = claims
        return self

    def upload(self, text=TEXT, visibility="public", title=None):
        return self.client.post("/market/reports", data={"title": title or text[:40], "visibility": visibility, "publisher": "Broker"},
                                files={"file": ("r.pdf", text_pdf([text]), "application/pdf")})

    def listing(self):
        return [row["title"] for row in self.client.get("/market/reports").json()["reports"]]


@pytest.fixture
def site(monkeypatch):
    return Site(monkeypatch)


def test_a_member_upload_is_private_to_the_uploader_and_waits_for_review(site):
    response = site.as_user(ALICE).upload(visibility="public")             # a member cannot choose "public"
    assert response.status_code == 200 and response.json()["duplicate"] is False
    stored = site.reports.find_by_digest(market_reports.report_digest(text_pdf([TEXT])))
    assert stored["visibility"] == "owner" and stored["status"] == "awaiting_review"      # processed, but held
    assert site.listing() == [TEXT[:40]]           # alice sees her own upload
    assert site.as_user(BOB).listing() == []                                                # nobody else does
    assert site.reports.pending_claims() == []                                              # the claim routine never sees it
    assert site.reports.list_claims() == []                                                 # nor do the public claims


def test_the_owner_upload_is_unchanged_public_and_straight_to_claim_extraction(site):
    assert site.as_user(OWNER).upload().status_code == 200
    stored = site.reports.find_by_digest(market_reports.report_digest(text_pdf([TEXT])))
    assert stored["visibility"] == "public" and stored["status"] == "claims_pending"
    assert site.as_user(BOB).listing() == [TEXT[:40]]
    assert len(site.reports.pending_claims()) == 1
    assert site.as_user(OWNER).upload(visibility="owner").status_code == 422               # the owner still cannot upload a private one


def test_a_signed_in_user_without_the_member_role_cannot_upload(site):
    assert site.as_user(NOBODY).upload().status_code == 403
    assert site.reports.list_reports("nobody-sub") == []


def test_a_member_may_upload_five_reports_a_day_and_the_sixth_is_refused(site):
    for number in range(5):
        assert site.as_user(ALICE).upload(text=f"Report number {number} about packaging capacity.").status_code == 200
    sixth = site.upload(text="Report number 5 about packaging capacity.")
    assert sixth.status_code == 429 and "5" in sixth.json()["detail"]
    assert site.as_user(BOB).upload(text="Bob report about optical modules.").status_code == 200     # the limit is per person
    assert site.as_user(OWNER).upload(text="Owner report about foundry pricing.").status_code == 200   # the owner has none
    site.now = NOON + timedelta(hours=14)                                                                # 02:00 the next Taipei day
    assert site.as_user(ALICE).upload(text="Report number 6 about packaging capacity.").status_code == 200


def test_the_day_is_a_taipei_day_not_a_utc_day(site):
    site.now = datetime(2026, 11, 3, 15, 30, tzinfo=timezone.utc)                                        # 23:30 Taipei
    for number in range(5):
        assert site.as_user(ALICE).upload(text=f"Late report {number} on memory.").status_code == 200
    assert site.upload(text="Late report 5 on memory.").status_code == 429
    site.now = datetime(2026, 11, 3, 16, 30, tzinfo=timezone.utc)                                        # 00:30 Taipei, new day, still 16:30 UTC
    assert site.upload(text="Late report 5 on memory.").status_code == 200


def test_the_review_queue_is_owner_only_and_names_the_uploader(site):
    site.as_user(ALICE).upload(text="Alice report on thermal design.")
    site.activity.touch_user("alice-sub", "alice")
    assert site.as_user(ALICE).client.get("/market/reports/review-queue").status_code == 403
    queue = site.as_user(OWNER).client.get("/market/reports/review-queue").json()["reports"]
    assert len(queue) == 1 and queue[0]["uploadedBy"] == "alice" and queue[0]["status"] == "awaiting_review"
    assert "text" not in queue[0] and "pdf" not in queue[0]


def test_approving_publishes_the_report_and_queues_claim_extraction(site):
    site.as_user(ALICE).upload(text="Alice report on thermal design.")
    report_id = site.as_user(OWNER).client.get("/market/reports/review-queue").json()["reports"][0]["id"]
    assert site.as_user(ALICE).client.post(f"/market/reports/{report_id}/review", json={"action": "approve"}).status_code == 403
    approved = site.as_user(OWNER).client.post(f"/market/reports/{report_id}/review", json={"action": "approve", "note": "ok"})
    assert approved.status_code == 200 and approved.json()["status"] == "claims_pending"
    assert site.as_user(BOB).listing() == ["Alice report on thermal design."]                              # public now
    assert [r["id"] for r in site.reports.pending_claims()] == [report_id]
    assert site.as_user(OWNER).client.post(f"/market/reports/{report_id}/review", json={"action": "approve"}).status_code == 409
    assert site.client.post("/market/reports/missing/review", json={"action": "approve"}).status_code == 404
    assert site.client.get("/market/reports/review-queue").json()["reports"] == []


def test_rejecting_keeps_the_report_private_and_the_uploader_sees_the_outcome(site):
    site.as_user(ALICE).upload(text="Alice report on thermal design.")
    report_id = site.as_user(OWNER).client.get("/market/reports/review-queue").json()["reports"][0]["id"]
    assert site.client.post(f"/market/reports/{report_id}/review", json={"action": "reject", "note": "not a research report"}).json()["status"] == "rejected"
    assert site.as_user(BOB).listing() == [] and site.reports.pending_claims() == []
    mine = site.as_user(ALICE).client.get("/market/reports").json()["reports"]
    assert [row["status"] for row in mine] == ["rejected"]
    assert site.as_user(OWNER).client.post(f"/market/reports/{report_id}/review", json={"action": "approve"}).status_code == 409


def test_review_input_is_validated(site):
    site.as_user(ALICE).upload(text="Alice report on thermal design.")
    report_id = site.as_user(OWNER).client.get("/market/reports/review-queue").json()["reports"][0]["id"]
    assert site.client.post(f"/market/reports/{report_id}/review", json={"action": "delete"}).status_code == 422
    assert site.client.post(f"/market/reports/{report_id}/review", json={"action": "reject", "note": "x" * 400}).status_code == 422


def test_every_upload_and_review_is_written_to_the_activity_log_under_the_right_person(site):
    site.as_user(ALICE).upload(text="Alice report on thermal design.")
    report_id = site.as_user(OWNER).client.get("/market/reports/review-queue").json()["reports"][0]["id"]
    site.client.post(f"/market/reports/{report_id}/review", json={"action": "approve", "note": "ok"})
    alice = site.activity.activity("alice-sub")
    assert [(a["action"], a["resourceType"]) for a in alice] == [("C", "report")] and alice[0]["detail"]["visibility"] == "owner"
    owner = site.activity.activity("owner-sub")
    assert [(a["action"], a["resourceId"]) for a in owner] == [("U", report_id)]
    assert owner[0]["detail"]["decision"] == "approve" and owner[0]["detail"]["uploader"] == "alice-sub"
    assert {u["sub"] for u in site.activity.users()} >= {"alice-sub", "owner-sub"}                         # both were seen


def test_a_duplicate_upload_is_not_logged_as_a_second_creation_and_does_not_use_the_quota(site):
    site.as_user(ALICE).upload(text="Same report text about memory.")
    again = site.upload(text="Same report text about memory.")
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert len(site.activity.activity("alice-sub")) == 1


def test_a_member_cannot_delete_reports_and_the_owner_delete_is_logged(site):
    site.as_user(OWNER).upload(text="Owner report on foundry pricing.")
    report_id = site.reports.list_reports("owner-sub")[0]["id"]
    assert site.as_user(ALICE).client.delete(f"/market/reports/{report_id}").status_code == 403
    assert site.as_user(OWNER).client.delete(f"/market/reports/{report_id}").status_code == 200
    assert ("D", "report") in [(a["action"], a["resourceType"]) for a in site.activity.activity("owner-sub")]
