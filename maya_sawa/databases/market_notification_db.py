"""Routine notifications, kept so the owner can re-read them on the site after Telegram has scrolled past."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
KEEP = 500


class MarketNotification(Base):
    __tablename__ = "maya_sawa_market_notification"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(Text, nullable=False)  # update | attention
    title = Column(Text, nullable=False)
    body = Column(Text, nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False)


class MarketNotificationDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def add(self, kind: str, title: str, body: str = "", keep: int = KEEP) -> int:
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        with self.sessions.begin() as session:
            row = MarketNotification(kind=kind, title=title, body=body or "", created_at=datetime.now(timezone.utc))
            session.add(row)
            session.flush()
            row_id = row.id
            stale = session.query(MarketNotification.id).order_by(MarketNotification.id.desc()).offset(keep).all()
            if stale:
                session.query(MarketNotification).filter(MarketNotification.id.in_([r.id for r in stale])).delete(synchronize_session=False)
            return row_id

    def recent(self, limit: int = 100) -> list[dict]:
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        with self.sessions() as session:
            rows = session.query(MarketNotification).order_by(MarketNotification.id.desc()).limit(limit).all()
            return [{"id": row.id, "kind": row.kind, "title": row.title, "body": row.body,
                     "createdAt": row.created_at.replace(tzinfo=row.created_at.tzinfo or timezone.utc).isoformat()} for row in rows]


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return MarketNotificationDatabase(market_dashboard_db.engine)


market_notification_db = _default_db()
