"""Material news events whose post-event relative performance is tracked day by day (services/relative_strength.py).

Routines record the event once; the daily gaps are recomputed from stored closes on every read, so a run that spans
many days never depends on an analysis text carrying it forward."""
import hashlib
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class MarketSignalEvent(Base):
    __tablename__ = "maya_sawa_market_signal_events"
    id = Column(Text, primary_key=True)                 # hash of code + publishedAt + title: re-posting is idempotent
    code = Column(Text, nullable=False, index=True)
    published_at = Column(Text, nullable=False)          # Taipei local ISO minute, e.g. 2026-11-10T14:05
    direction = Column(Text, nullable=False)             # positive | negative
    title = Column(Text, nullable=False)
    source_url = Column(Text, nullable=False)
    reason = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False)


class MarketSignalEventsDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def record(self, code: str, published_at: str, direction: str, title: str, source_url: str, reason: str = "") -> dict:
        if not self.sessions:
            raise RuntimeError("Signal events database unavailable")
        event_id = hashlib.sha256(f"{code}|{published_at}|{title}".encode()).hexdigest()[:16]
        with self.sessions.begin() as session:
            created = session.get(MarketSignalEvent, event_id) is None
            if created:
                session.add(MarketSignalEvent(id=event_id, code=code, published_at=published_at, direction=direction,
                    title=title, source_url=source_url, reason=reason, created_at=datetime.now(timezone.utc)))
        return {"id": event_id, "created": created}

    def since(self, day: str, code: str | None = None) -> list[dict]:
        if not self.sessions:
            return []
        with self.sessions() as session:
            query = session.query(MarketSignalEvent).filter(MarketSignalEvent.published_at >= day)
            if code:
                query = query.filter(MarketSignalEvent.code == code)
            return [{"id": row.id, "code": row.code, "publishedAt": row.published_at, "direction": row.direction,
                     "title": row.title, "sourceUrl": row.source_url, "reason": row.reason}
                    for row in query.order_by(MarketSignalEvent.published_at.desc()).limit(200).all()]


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return MarketSignalEventsDatabase(market_dashboard_db.engine)


market_signal_events_db = _default_db()
