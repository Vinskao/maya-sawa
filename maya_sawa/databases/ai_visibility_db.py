"""Inbox and history for AI-search visibility runs (docs/AI_VISIBILITY.md).

Anyone can post a run without a key, so a row is untrusted: it stays `pending` and off the dashboard until the keyed Claude
routine accepts it. Fixes the routine then makes to the site are attached to the run they answer.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class InboxFull(Exception):
    pass


class AiVisibilityRun(Base):
    __tablename__ = "maya_sawa_ai_visibility_run"
    id = Column(Text, primary_key=True)
    week = Column(Text, nullable=False, index=True)
    digest = Column(Text, nullable=False)
    results = Column(Text, nullable=False)
    status = Column(Text, nullable=False)  # pending | accepted | rejected
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    reviewed_at = Column(DateTime(timezone=True))
    note = Column(Text)
    fixes = Column(Text)


def _iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def _row(row: AiVisibilityRun) -> dict:
    return {"id": row.id, "week": row.week, "status": row.status, "results": json.loads(row.results),
            "submittedAt": _iso(row.submitted_at), "reviewedAt": _iso(row.reviewed_at), "note": row.note or "",
            "fixes": json.loads(row.fixes) if row.fixes else []}


class AiVisibilityDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def _require(self):
        if not self.sessions:
            raise RuntimeError("AI visibility database unavailable")

    def submit(self, week: str, results: list[dict], now: datetime, limit: int) -> tuple[dict, bool]:
        self._require()
        text = json.dumps(results, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.sessions.begin() as session:
            existing = session.query(AiVisibilityRun).filter_by(week=week, digest=digest).first()
            if existing:
                return _row(existing), False
            if session.query(AiVisibilityRun).filter_by(week=week).count() >= limit:
                raise InboxFull(week)
            row = AiVisibilityRun(id=str(uuid.uuid4()), week=week, digest=digest, results=text, status="pending", submitted_at=now)
            session.add(row)
            session.flush()
            return _row(row), True

    def list(self, status: str | None = "pending", limit: int = 12) -> list[dict]:
        self._require()
        with self.sessions() as session:
            query = session.query(AiVisibilityRun)
            if status:
                query = query.filter_by(status=status)
            return [_row(r) for r in query.order_by(AiVisibilityRun.submitted_at.desc()).limit(limit).all()]

    def count(self, status: str) -> int:
        self._require()
        with self.sessions() as session:
            return session.query(AiVisibilityRun).filter_by(status=status).count()

    def get(self, run_id: str) -> dict | None:
        self._require()
        with self.sessions() as session:
            row = session.get(AiVisibilityRun, run_id)
            return _row(row) if row else None

    def review(self, run_id: str, action: str, note: str, now: datetime) -> dict | None:
        """Accept or reject a pending run once; None when it is not pending (or unknown)."""
        self._require()
        with self.sessions.begin() as session:
            row = session.get(AiVisibilityRun, run_id)
            if not row or row.status != "pending":
                return None
            row.status = "accepted" if action == "accept" else "rejected"
            row.reviewed_at, row.note = now, note
            session.flush()
            return _row(row)

    def add_fixes(self, run_id: str, fixes: "list[str]") -> dict | None:
        self._require()
        with self.sessions.begin() as session:
            row = session.get(AiVisibilityRun, run_id)
            if not row or row.status != "accepted":
                return None
            row.fixes = json.dumps(fixes, ensure_ascii=False)
            session.flush()
            return _row(row)


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return AiVisibilityDatabase(market_dashboard_db.engine)


ai_visibility_db = _default_db()
