"""Routine notifications, kept so the owner can re-read them on the site after Telegram has scrolled past."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
KEEP = 500

# Sent to Telegram (and read) before notifications were stored; added once so the bell shows them too.
HISTORY_BEFORE_STORAGE = [
    {"kind": "update", "title": "Telegram 通知測試", "body": "排程到 Telegram 的串接正常。", "at": "2026-10-27T12:17:00+00:00"},
    {"kind": "update", "title": "市場 AI 分析｜台股收盤後", "at": "2026-10-27T13:25:00+00:00",
     "body": "更新 17 檔（結論皆維持）：TXF 10→11 買；2330 13→14 買；3008 13→14 賣；3081 15→16 買；3017 13→14 買；3105 13→14 中立；"
             "3324 13→14 中立；8996 12→13 買；3711 11→12 買；6187 11→12 買；6442 12→13 買；6213 12→13 買；3443 12→13 買；3167 13→14 買；"
             "2408 13→14 賣；6857-JP 4→5 買；6524-JP 6→7 中立。新增券商目標價 2 筆（日月光 美銀 900、奇鋐 高盛 4,736）。"
             "原因：10/27 新交易日資料＋Gooaye 報告新主張；語意搜尋 503 略過。"},
]


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

    def add(self, kind: str, title: str, body: str = "", keep: int = KEEP, at: datetime | None = None) -> int:
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        with self.sessions.begin() as session:
            row = MarketNotification(kind=kind, title=title, body=body or "", created_at=at or datetime.now(timezone.utc))
            session.add(row)
            session.flush()
            row_id = row.id
            stale = session.query(MarketNotification.id).order_by(MarketNotification.id.desc()).offset(keep).all()
            if stale:
                session.query(MarketNotification).filter(MarketNotification.id.in_([r.id for r in stale])).delete(synchronize_session=False)
            return row_id

    def seed_if_empty(self, rows: list[dict]) -> int:
        """Add history that predates storage, once: only into an empty table, oldest first."""
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        with self.sessions() as session:
            if session.query(MarketNotification.id).first() is not None:
                return 0
        for row in sorted(rows, key=lambda item: item["at"]):
            self.add(row["kind"], row["title"], row["body"], at=datetime.fromisoformat(row["at"]))
        return len(rows)

    def recent(self, limit: int = 100) -> list[dict]:
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        with self.sessions() as session:
            rows = session.query(MarketNotification).order_by(MarketNotification.id.desc()).limit(limit).all()
            return [{"id": row.id, "kind": row.kind, "title": row.title, "body": row.body,
                     "createdAt": row.created_at.replace(tzinfo=row.created_at.tzinfo or timezone.utc).isoformat()} for row in rows]


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    db = MarketNotificationDatabase(market_dashboard_db.engine)
    try:
        if db.sessions:
            db.seed_if_empty(HISTORY_BEFORE_STORAGE)
    except Exception:  # the bell simply starts empty; nothing else depends on this
        import logging
        logging.getLogger(__name__).exception("Notification history backfill failed")
    return db


market_notification_db = _default_db()
