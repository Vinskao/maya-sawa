"""Routine notifications are kept so the owner can re-read them on the site, not only in Telegram."""
import hashlib

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.core.auth.keycloak import require_manage_users_request
from maya_sawa.databases.market_notification_db import MarketNotificationDatabase


@pytest.fixture
def db():
    return MarketNotificationDatabase(create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool))  # the API calls it from worker threads


def client_for(db, monkeypatch, owner=True, sent=None):
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_notification_db", db)
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", hashlib.sha256(b"k").hexdigest())
    monkeypatch.setattr(market.telegram_notify, "send",
                        lambda kind, title, body="": (sent if sent is not None else []).append(title) or {"sent": False, "reason": "not configured"})
    app = FastAPI()
    app.include_router(market.router)

    def deny():
        raise HTTPException(status_code=401, detail="no token")
    app.dependency_overrides[require_manage_users_request] = (lambda: {"sub": "owner"}) if owner else deny
    app.dependency_overrides[market.optional_owner] = (lambda: {"sub": "owner"}) if owner else (lambda: None)
    return TestClient(app)


def test_recent_returns_newest_first_with_a_stable_id_and_limit(db):
    first = db.add("update", "台股收盤後", "3008 賣→買")
    second = db.add("attention", "IB 斷線", "請重新登入")
    rows = db.recent(limit=10)
    assert [row["title"] for row in rows] == ["IB 斷線", "台股收盤後"]
    assert rows[0] == {"id": second, "kind": "attention", "title": "IB 斷線", "body": "請重新登入", "createdAt": rows[0]["createdAt"]}
    assert first != second and rows[0]["createdAt"].endswith("+00:00")
    assert len(db.recent(limit=1)) == 1


def test_keeps_only_the_latest_rows(db):
    for index in range(7):
        db.add("update", f"n{index}", "", keep=5)
    assert [row["title"] for row in db.recent(limit=50)] == ["n6", "n5", "n4", "n3", "n2"]


def test_notify_is_stored_even_when_telegram_is_not_configured(db, monkeypatch):
    sent = []
    client = client_for(db, monkeypatch, sent=sent)
    body = {"kind": "update", "title": "台股收盤後", "body": "3008 賣→買：營收年增轉正"}
    assert client.post("/market/notify", json=body).status_code == 401
    assert db.recent() == []  # an unauthenticated call stores nothing
    ok = client.post("/market/notify", json=body, headers={"x-market-agent-key": "k"})
    assert ok.status_code == 200 and sent == ["台股收盤後"]
    assert [row["body"] for row in db.recent()] == ["3008 賣→買：營收年增轉正"]


def test_stored_text_is_masked_like_the_telegram_text(db, monkeypatch):
    client = client_for(db, monkeypatch)
    secret = "123456789:" + "A" * 30
    client.post("/market/notify", json={"kind": "update", "title": "t", "body": f"key {secret}"}, headers={"x-market-agent-key": "k"})
    assert secret not in db.recent()[0]["body"]


def test_anyone_reads_routine_updates_but_only_the_owner_reads_attention(db, monkeypatch):
    """2026-10-29: the owner wants the bell readable without signing in. 'attention' rows (IB login needed, a stuck run)
    are about the owner's accounts, so they stay owner-only."""
    db.add("update", "台股收盤後", "x")
    db.add("attention", "IB 斷線", "請重新登入")
    public = client_for(db, monkeypatch, owner=False).get("/market/notifications?limit=5")
    assert public.status_code == 200
    assert [row["title"] for row in public.json()["notifications"]] == ["台股收盤後"]
    data = client_for(db, monkeypatch).get("/market/notifications?limit=5").json()
    assert [row["title"] for row in data["notifications"]] == ["IB 斷線", "台股收盤後"]


def test_the_public_list_still_returns_the_limit_of_updates(db):
    for index in range(3):
        db.add("update", f"u{index}", "")
        db.add("attention", f"a{index}", "")
    assert [row["title"] for row in db.recent(limit=2, kinds=("update",))] == ["u2", "u1"]


def test_messages_sent_before_history_was_kept_are_backfilled_once(db):
    """2026-10-28: the two Telegram messages the owner had already read (the test message and the first 台股收盤後 summary)
    were sent before notifications were stored, so the bell said "no notifications"."""
    from maya_sawa.databases.market_notification_db import HISTORY_BEFORE_STORAGE
    assert db.seed_if_empty(HISTORY_BEFORE_STORAGE) == 2
    rows = db.recent()
    assert [row["title"] for row in rows] == ["市場 AI 分析｜台股收盤後", "Telegram 通知測試"]
    assert rows[0]["createdAt"] == "2026-10-27T13:25:00+00:00" and rows[1]["createdAt"] == "2026-10-27T12:17:00+00:00"
    assert "更新 17 檔" in rows[0]["body"] and "日月光 美銀 900" in rows[0]["body"]
    assert db.seed_if_empty(HISTORY_BEFORE_STORAGE) == 0            # a second start adds nothing
    other = MarketNotificationDatabase(db.sessions.kw["bind"])
    other.add("update", "新的", "")
    assert other.seed_if_empty(HISTORY_BEFORE_STORAGE) == 0         # nor does it touch a table that already has rows
