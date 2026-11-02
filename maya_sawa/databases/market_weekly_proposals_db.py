"""Inbox for the weekly GPT cloud job's proposals (see docs/GPT_WEEKLY_OPPORTUNITIES.md).

Anyone may post here without a key, so a row is untrusted input: storing it changes nothing on the site. Only the
keyed Claude routine reviews a row, and applying it re-validates the evidence and goes through the normal nomination.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Text, update
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class InboxFull(Exception):
    pass


class WeeklyProposal(Base):
    __tablename__ = "maya_sawa_market_weekly_proposal"
    id = Column(Text, primary_key=True)
    week = Column(Text, nullable=False, index=True)
    digest = Column(Text, nullable=False)
    proposals = Column(Text, nullable=False)
    status = Column(Text, nullable=False)  # pending | applying | applied | rejected | failed
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    reviewed_at = Column(DateTime(timezone=True))
    review = Column(Text)


def _iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def _row(row: WeeklyProposal) -> dict:
    return {"id": row.id, "week": row.week, "status": row.status, "proposals": json.loads(row.proposals),
            "submittedAt": _iso(row.submitted_at), "reviewedAt": _iso(row.reviewed_at),
            "review": json.loads(row.review) if row.review else None}


class WeeklyProposalDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def _require(self):
        if not self.sessions:
            raise RuntimeError("Weekly proposal database unavailable")

    def submit(self, week: str, proposals: list[dict], now: datetime, limit: int) -> tuple[dict, bool]:
        """Store a batch once per week (a re-run sends the same text); at most `limit` batches a week."""
        self._require()
        text = json.dumps(proposals, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(text.encode()).hexdigest()
        with self.sessions.begin() as session:
            existing = session.query(WeeklyProposal).filter_by(week=week, digest=digest).first()
            if existing:
                return _row(existing), False
            if session.query(WeeklyProposal).filter_by(week=week).count() >= limit:
                raise InboxFull(week)
            row = WeeklyProposal(id=str(uuid.uuid4()), week=week, digest=digest, proposals=text,
                                 status="pending", submitted_at=now)
            session.add(row)
            session.flush()
            return _row(row), True

    def list(self, status: str | None = "pending", limit: int = 50) -> list[dict]:
        self._require()
        with self.sessions() as session:
            query = session.query(WeeklyProposal)
            if status:
                query = query.filter_by(status=status)
            return [_row(row) for row in query.order_by(WeeklyProposal.submitted_at.desc()).limit(limit).all()]

    def get(self, proposal_id: str) -> dict | None:
        self._require()
        with self.sessions() as session:
            row = session.get(WeeklyProposal, proposal_id)
            return _row(row) if row else None

    def claim(self, proposal_id: str) -> dict | None:
        """pending -> applying in one statement, so two reviews of the same row cannot both apply it."""
        self._require()
        with self.sessions.begin() as session:
            changed = session.execute(update(WeeklyProposal).where(WeeklyProposal.id == proposal_id,
                                                                   WeeklyProposal.status == "pending")
                                      .values(status="applying")).rowcount
            return _row(session.get(WeeklyProposal, proposal_id)) if changed == 1 else None

    def finish(self, proposal_id: str, status: str, review: dict, now: datetime) -> dict:
        self._require()
        with self.sessions.begin() as session:
            row = session.get(WeeklyProposal, proposal_id)
            row.status, row.reviewed_at = status, now
            row.review = json.dumps(review, ensure_ascii=False, default=str)
            session.flush()
            return _row(row)


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return WeeklyProposalDatabase(market_dashboard_db.engine)


market_weekly_proposals_db = _default_db()
