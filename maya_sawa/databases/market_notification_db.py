"""Routine notifications, kept so the owner can re-read them on the site after Telegram has scrolled past."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
KEEP = 500
# Read receipts kept per user (newest first). Never below KEEP: a user can see that many notifications, and diary receipts
# cannot be matched to a stored notification here, so this cap is what bounds them.
RECEIPTS_PER_USER = 1000

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


class NotificationReceipt(Base):
    """One read notification for one user. The user is the Keycloak `sub` only: the token issuer is a URL (it changed with the
    2026-10-31 domain move) and the backend accepts exactly one issuer at a time, so keying on it only risks orphaning receipts."""
    __tablename__ = "maya_sawa_notification_receipt"
    subject = Column(Text, primary_key=True)
    notification_id = Column(Text, primary_key=True)
    read_at = Column(DateTime(timezone=True), nullable=False)


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
                stale_ids = [r.id for r in stale]
                session.query(MarketNotification).filter(MarketNotification.id.in_(stale_ids)).delete(synchronize_session=False)
                # A receipt for a notification that no longer exists is dead weight (diary receipts cannot be checked here; the cap bounds them).
                session.query(NotificationReceipt).filter(
                    NotificationReceipt.notification_id.in_([f"routine:{row_id}" for row_id in stale_ids])).delete(synchronize_session=False)
            return row_id

    def read_ids(self, subject: str) -> list[str]:
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        with self.sessions() as session:
            rows = session.query(NotificationReceipt.notification_id).filter_by(subject=subject).all()
            return sorted(row[0] for row in rows)

    def mark_read(self, subject: str, ids: list[str], now: datetime | None = None, cap: int = RECEIPTS_PER_USER) -> None:
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        with self.sessions.begin() as session:
            insert = pg_insert if session.bind.dialect.name == 'postgresql' else sqlite_insert
            read_at = now or datetime.now(timezone.utc)
            for notification_id in set(ids):
                statement = insert(NotificationReceipt).values(subject=subject, notification_id=notification_id, read_at=read_at)
                session.execute(statement.on_conflict_do_nothing())
            # Keep only this user's newest `cap` receipts.
            excess = (session.query(NotificationReceipt.notification_id).filter_by(subject=subject)
                      .order_by(NotificationReceipt.read_at.desc(), NotificationReceipt.notification_id.desc()).offset(cap).all())
            if excess:
                session.query(NotificationReceipt).filter(NotificationReceipt.subject == subject,
                    NotificationReceipt.notification_id.in_([row[0] for row in excess])).delete(synchronize_session=False)

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

    def recent(self, limit: int = 100, kinds: tuple[str, ...] | None = None) -> list[dict]:
        if not self.sessions:
            raise RuntimeError("Notification database unavailable")
        with self.sessions() as session:
            query = session.query(MarketNotification)
            if kinds is not None:
                query = query.filter(MarketNotification.kind.in_(kinds))
            rows = query.order_by(MarketNotification.id.desc()).limit(limit).all()
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
