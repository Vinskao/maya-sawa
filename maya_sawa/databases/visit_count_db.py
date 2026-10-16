"""Durable daily visit totals stored in the service's PostgreSQL database."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, Column, DateTime, Text, create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import QueuePool

from ..core.config.config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()
BASELINE_ID = "legacy-baseline"
TAIPEI = timezone(timedelta(hours=8))


class VisitCountBucket(Base):
    __tablename__ = "maya_sawa_visit_count_history"
    period = Column(Text, primary_key=True)
    kind = Column(Text, nullable=False)
    visits = Column(BigInteger, nullable=False, default=0)
    captured_at = Column(DateTime(timezone=True), nullable=False)


class VisitCountDatabase:
    def __init__(self) -> None:
        self.sessions = None
        if not Config.DB_CONNECTION_STRING:
            logger.error("Visit history PostgreSQL URL is not configured")
            return
        try:
            engine = create_engine(
                Config.DB_CONNECTION_STRING,
                poolclass=QueuePool,
                pool_size=2,
                max_overflow=2,
                pool_recycle=1800,
            )
            Base.metadata.create_all(engine)
            self.sessions = sessionmaker(bind=engine)
        except Exception:
            logger.exception("Visit history PostgreSQL initialization failed")

    def _require_sessions(self):
        if self.sessions is None:
            raise RuntimeError("Persistent visit storage unavailable")
        return self.sessions

    def ensure_baseline(self, legacy_total: int) -> None:
        sessions = self._require_sessions()
        now = datetime.now(TAIPEI)
        with sessions.begin() as session:
            session.execute(insert(VisitCountBucket).values(
                period=BASELINE_ID,
                kind="baseline",
                visits=max(0, int(legacy_total)),
                captured_at=now,
            ).on_conflict_do_nothing(index_elements=[VisitCountBucket.period]))

    def increment(self, now: datetime, legacy_total: int) -> int:
        sessions = self._require_sessions()
        period = now.astimezone(TAIPEI).date().isoformat()
        with sessions.begin() as session:
            session.execute(insert(VisitCountBucket).values(
                period=BASELINE_ID,
                kind="baseline",
                visits=max(0, int(legacy_total)),
                captured_at=now,
            ).on_conflict_do_nothing(index_elements=[VisitCountBucket.period]))
            statement = insert(VisitCountBucket).values(
                period=period, kind="daily", visits=1, captured_at=now
            )
            session.execute(statement.on_conflict_do_update(
                index_elements=[VisitCountBucket.period],
                set_={
                    "visits": VisitCountBucket.visits + 1,
                    "captured_at": statement.excluded.captured_at,
                },
            ))
            total = session.execute(select(func.coalesce(func.sum(VisitCountBucket.visits), 0))).scalar_one()
            return int(total)

    def history(self, days: int) -> dict:
        sessions = self._require_sessions()
        with sessions() as session:
            rows = session.execute(select(
                VisitCountBucket.period,
                VisitCountBucket.kind,
                VisitCountBucket.visits,
                VisitCountBucket.captured_at,
            ).order_by(VisitCountBucket.period)).all()
        total = sum(int(row.visits) for row in rows)
        cumulative = 0
        points = []
        for row in rows:
            if row.kind == "baseline":
                cumulative = int(row.visits)
                points.append({
                    "timestamp": row.captured_at.isoformat(),
                    "date": row.captured_at.astimezone(TAIPEI).date().isoformat(),
                    "visits": 0,
                    "cumulative": cumulative,
                })
            else:
                cumulative += int(row.visits)
                points.append({
                    "timestamp": row.captured_at.isoformat(),
                    "date": row.period,
                    "visits": int(row.visits),
                    "cumulative": cumulative,
                })
        cutoff = (datetime.now(TAIPEI).date() - timedelta(days=days - 1)).isoformat()
        prior = [point for point in points if point["date"] < cutoff]
        visible = [point for point in points if point["date"] >= cutoff]
        if prior:
            visible.insert(0, prior[-1])
        return {"totalCount": total, "days": days, "points": visible, "persisted": True}


visit_count_db = VisitCountDatabase()
