from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.daily_maya_db import DailyMayaDatabase


@pytest.fixture
def db():
    return DailyMayaDatabase(create_engine('sqlite:///:memory:'))


def test_proposal_is_private_until_reviewed_and_retry_is_idempotent(db):
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    proposal, created = db.submit('2026-11-03', '財報顯示需求改善。', ['stock:2330:2'], now)
    assert created and db.published() == []
    duplicate, created = db.submit('2026-11-03', '財報顯示需求改善。', ['stock:2330:2'], now)
    assert not created and duplicate['id'] == proposal['id']
    assert db.review(proposal['id'], 'approved', '來源已核對', now)
    assert db.published()[0]['content'] == '財報顯示需求改善。'
    assert not db.review(proposal['id'], 'approved', '再次核准', now)


def test_rejection_never_publishes_and_reviewer_must_explain(db):
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    row, _ = db.submit('2026-11-03', '未經確認的說法', ['macro:MACRO:1'], now)
    with pytest.raises(ValueError):
        db.review(row['id'], 'approved', '', now)
    assert db.review(row['id'], 'rejected', '來源不符', now)
    assert db.published() == []


def test_pending_inbox_is_bounded_and_only_lists_pending(db):
    now = datetime(2026, 11, 3, tzinfo=timezone.utc)
    first, _ = db.submit('2026-11-03', '第一份', ['stock:2330:2'], now, limit=2)
    db.submit('2026-11-03', '第二份', ['stock:2330:2'], now, limit=2)
    with pytest.raises(OverflowError):
        db.submit('2026-11-03', '第三份', ['stock:2330:2'], now, limit=2)
    assert len(db.pending()) == 2
    assert db.review(first['id'], 'rejected', '來源不符', now)
    assert len(db.pending()) == 1
