"""One OpenTimestamps proof per Taipei day of AI analysis revisions (see services/analysis_timestamps.py)."""
from sqlalchemy import Column, DateTime, Integer, LargeBinary, Text
from sqlalchemy.orm import declarative_base, sessionmaker

from .market_ai_analysis_db import MarketAiAnalysisRevision
from .market_dashboard_db import market_dashboard_db

Base = declarative_base()


class AnalysisTimestamp(Base):
    __tablename__ = "maya_sawa_analysis_timestamp"
    day = Column(Text, primary_key=True)              # YYYY-MM-DD, Asia/Taipei
    digest = Column(Text, nullable=False)             # SHA-256 of manifest, hex
    manifest = Column(Text, nullable=False)           # the exact stamped bytes, UTF-8
    revision_count = Column(Integer, nullable=False)
    proof = Column(LargeBinary, nullable=False)       # .ots file
    status = Column(Text, nullable=False)             # pending | confirmed
    bitcoin_height = Column(Integer)
    calendars = Column(Integer, nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    checked_at = Column(DateTime(timezone=True))


COLUMNS = {"revisionCount": "revision_count", "bitcoinHeight": "bitcoin_height", "submittedAt": "submitted_at", "checkedAt": "checked_at"}


def as_record(row: AnalysisTimestamp) -> dict:
    return {"day": row.day, "digest": row.digest, "manifest": row.manifest, "revisionCount": row.revision_count, "proof": bytes(row.proof),
            "status": row.status, "bitcoinHeight": row.bitcoin_height, "calendars": row.calendars,
            "submittedAt": row.submitted_at, "checkedAt": row.checked_at}


class AnalysisTimestampDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def revisions_between(self, start, end) -> list[dict]:
        with self.sessions() as session:
            rows = session.query(MarketAiAnalysisRevision).filter(MarketAiAnalysisRevision.updated_at >= start,
                                                                  MarketAiAnalysisRevision.updated_at < end).all()
            # updatedAt is rendered exactly as the public analysis API renders it, so anyone can recompute the hashes.
            return [{"productType": row.product_type, "code": row.code, "revision": row.revision, "model": row.model,
                     "content": row.content, "updatedAt": row.updated_at.isoformat()} for row in rows]

    def get(self, day: str) -> dict | None:
        with self.sessions() as session:
            row = session.get(AnalysisTimestamp, day)
            return as_record(row) if row else None

    def save(self, record: dict) -> None:
        with self.sessions.begin() as session:
            session.merge(AnalysisTimestamp(**{COLUMNS.get(key, key): value for key, value in record.items()}))

    def pending(self) -> list[dict]:
        with self.sessions() as session:
            return [as_record(row) for row in session.query(AnalysisTimestamp).filter_by(status="pending").all()]

    def update(self, day: str, **fields) -> None:
        with self.sessions.begin() as session:
            row = session.get(AnalysisTimestamp, day)
            for key, value in fields.items():
                setattr(row, COLUMNS.get(key, key), value)

    def recent(self, limit: int = 90) -> list[dict]:
        if not self.sessions:
            raise RuntimeError("Timestamp database unavailable")
        with self.sessions() as session:
            return [as_record(row) for row in session.query(AnalysisTimestamp).order_by(AnalysisTimestamp.day.desc()).limit(limit).all()]


analysis_timestamp_db = AnalysisTimestampDatabase(market_dashboard_db.engine)
