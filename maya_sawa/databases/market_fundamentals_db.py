"""Persistent low-frequency fundamentals fallback data (FinMind only)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import BigInteger, Column, Date, DateTime, Text, UniqueConstraint, create_engine, pool, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config.config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()


class FinMindFundamental(Base):
    __tablename__ = "maya_sawa_market_fundamental_history"
    __table_args__ = (UniqueConstraint("dataset", "code", "period", "item", name="uq_market_fundamental_identity"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dataset = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    period = Column(Text, nullable=False)
    item = Column(Text, nullable=False)
    value = Column(Text, nullable=False)
    unit = Column(Text, nullable=False, default="")
    source_url = Column(Text, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)


class FinMindUsage(Base):
    __tablename__ = "maya_sawa_finmind_usage"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    requested_at = Column(DateTime(timezone=True), nullable=False)
    dataset = Column(Text, nullable=False)
    code = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False)
    detail = Column(Text, nullable=False, default="")


class MarketQuoteSnapshot(Base):
    __tablename__ = "maya_sawa_market_quote_snapshot"
    __table_args__ = (UniqueConstraint("product_type", "code", name="uq_market_quote_snapshot_identity"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_type = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    payload = Column(Text, nullable=False)
    observed_at = Column(DateTime(timezone=True), nullable=False)


class FinMindCheckpoint(Base):
    __tablename__ = "maya_sawa_finmind_checkpoint"
    __table_args__ = (UniqueConstraint("dataset", "code", name="uq_finmind_checkpoint_identity"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dataset = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    checked_at = Column(DateTime(timezone=True), nullable=False)
    status = Column(Text, nullable=False)


class FundamentalReleaseSeen(Base):
    """When this site first saw each reported period; stands in for a publication date the sources lack.

    The first collection of a (code, dataset) is a baseline (baseline=1) so existing history is not flagged as new.
    """
    __tablename__ = "maya_sawa_fundamental_release_seen"
    __table_args__ = (UniqueConstraint("dataset", "code", "period", name="uq_fundamental_release_seen"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    dataset = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    period = Column(Text, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    baseline = Column(BigInteger, nullable=False, default=0)


class MarketFundamentalsDatabase:
    def __init__(self) -> None:
        self.engine = None
        self.sessions = None
        if Config.DB_CONNECTION_STRING:
            self.engine = create_engine(Config.DB_CONNECTION_STRING, poolclass=pool.QueuePool, pool_size=1, max_overflow=2)
            self.sessions = sessionmaker(bind=self.engine)
            try:
                Base.metadata.create_all(self.engine)
            except Exception:
                logger.exception("Market fundamentals schema initialization failed")

    def rows(self, code: str, dataset: str) -> list[dict]:
        if not self.sessions:
            return []
        with self.sessions() as session:
            found = session.query(FinMindFundamental).filter_by(code=code.upper(), dataset=dataset).order_by(FinMindFundamental.period, FinMindFundamental.item).all()
        return [{"period": row.period, "item": row.item, "value": row.value, "unit": row.unit, "source": "FinMind", "fetchedAt": row.fetched_at.isoformat()} for row in found]

    def replace_dataset(self, dataset: str, code: str, records: list[dict], source_url: str) -> int:
        if not self.sessions or not records:
            return 0
        now = datetime.now(timezone.utc)
        values = [{"dataset": dataset, "code": code.upper(), "period": str(row["period"]), "item": str(row["item"]), "value": json.dumps(row.get("value"), ensure_ascii=False), "unit": str(row.get("unit", "")), "source_url": source_url, "fetched_at": now} for row in records]
        with self.sessions.begin() as session:
            statement = insert(FinMindFundamental).values(values)
            session.execute(statement.on_conflict_do_update(constraint="uq_market_fundamental_identity", set_={key: getattr(statement.excluded, key) for key in ("value", "unit", "source_url", "fetched_at")}))
        return len(values)

    def record_periods_seen(self, dataset: str, code: str, periods: list[str]) -> None:
        if not self.sessions or not periods:
            return
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            baseline = session.query(FundamentalReleaseSeen.id).filter_by(dataset=dataset, code=code.upper()).first() is None
            values = [{"dataset": dataset, "code": code.upper(), "period": period, "first_seen_at": now,
                       "baseline": 1 if baseline else 0} for period in sorted(set(periods))]
            session.execute(insert(FundamentalReleaseSeen).values(values).on_conflict_do_nothing(constraint="uq_fundamental_release_seen"))

    def releases_seen_since(self, code: str, since: datetime) -> list[dict]:
        if not self.sessions:
            return []
        with self.sessions() as session:
            rows = session.query(FundamentalReleaseSeen).filter(
                FundamentalReleaseSeen.code == code.upper(), FundamentalReleaseSeen.baseline == 0,
                FundamentalReleaseSeen.first_seen_at >= since).all()
        return [{"dataset": row.dataset, "period": row.period, "firstSeenAt": row.first_seen_at.isoformat()} for row in rows]

    def claim_finmind_slot(self, dataset: str, code: str, hourly_limit: int = 120, min_gap_seconds: int = 30) -> int | None:
        """DB serialized account-wide throttle; retain 480 of the free 600 calls."""
        if not self.sessions:
            return None
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(741928410)"))
            checkpoint = session.query(FinMindCheckpoint).filter_by(dataset=dataset, code=code.upper()).first()
            if checkpoint and (now - checkpoint.checked_at).total_seconds() < 24 * 60 * 60:
                return None
            count = session.query(FinMindUsage).filter(FinMindUsage.requested_at >= now - timedelta(hours=1), FinMindUsage.status.in_(["reserved", "success", "error"])).count()
            if count >= hourly_limit:
                return None
            last_request = session.query(FinMindUsage.requested_at).order_by(FinMindUsage.requested_at.desc()).first()
            if last_request and (now - last_request[0]).total_seconds() < min_gap_seconds:
                return None
            reservation = FinMindUsage(requested_at=now, dataset=dataset, code=code.upper(), status="reserved", detail="")
            session.add(reservation)
            if checkpoint:
                checkpoint.checked_at, checkpoint.status = now, "reserved"
            else:
                session.add(FinMindCheckpoint(dataset=dataset, code=code.upper(), checked_at=now, status="reserved"))
            session.flush()
            reservation_id = reservation.id
        return reservation_id

    def record_finmind_result(self, reservation_id: int, status: str, detail: str = "") -> None:
        if not self.sessions:
            return
        with self.sessions.begin() as session:
            row = session.get(FinMindUsage, reservation_id)
            if row:
                row.status, row.detail = status, detail[:300]
                checkpoint = session.query(FinMindCheckpoint).filter_by(dataset=row.dataset, code=row.code).first()
                if checkpoint:
                    checkpoint.status = status

    def save_quote_snapshots(self, rows: list[dict]) -> None:
        if not self.sessions or not rows:
            return
        now = datetime.now(timezone.utc)
        values = [{"product_type": str(row["productType"]), "code": str(row["symbol"]).upper(),
                   "payload": json.dumps(row, ensure_ascii=False), "observed_at": now} for row in rows]
        with self.sessions.begin() as session:
            statement = insert(MarketQuoteSnapshot).values(values)
            session.execute(statement.on_conflict_do_update(constraint="uq_market_quote_snapshot_identity",
                set_={"payload": statement.excluded.payload, "observed_at": statement.excluded.observed_at}))

    def quote_snapshots(self, instruments: list[dict]) -> list[dict]:
        if not self.sessions or not instruments:
            return []
        codes = {(str(row.get("productType", "")).lower(), str(row.get("code", "")).upper()) for row in instruments}
        with self.sessions() as session:
            rows = session.query(MarketQuoteSnapshot).filter(
                MarketQuoteSnapshot.code.in_([code for _, code in codes])
            ).all()
        result = []
        for row in rows:
            if (row.product_type, row.code) in codes:
                try:
                    item = json.loads(row.payload)
                    item.setdefault("snapshotAt", row.observed_at.isoformat())
                    result.append(item)
                except (TypeError, json.JSONDecodeError):
                    continue
        return result


market_fundamentals_db = MarketFundamentalsDatabase()
