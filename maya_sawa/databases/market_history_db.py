"""Persistent daily market history for the public market dashboard."""

from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, Text, UniqueConstraint, create_engine, pool, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config.config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()


class MarketDailyHistory(Base):
    __tablename__ = "maya_sawa_market_daily_history"
    __table_args__ = (UniqueConstraint("source_key", "product_type", "code", "trading_date",
                                        name="uq_market_daily_history_identity"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_key = Column(Text, nullable=False)
    product_type = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    trading_date = Column(Date, nullable=False)
    values_json = Column(Text, nullable=False)
    unit = Column(Text, nullable=False, default="")
    source_url = Column(Text, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)


class MarketHistoryCoverage(Base):
    __tablename__ = "maya_sawa_market_history_coverage"
    __table_args__ = (UniqueConstraint("source_key", "code", "trading_date",
                                        name="uq_market_history_coverage_identity"),)

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_key = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    trading_date = Column(Date, nullable=False)
    status = Column(Text, nullable=False)
    record_count = Column(Integer, nullable=False, default=0)
    detail = Column(Text, nullable=False, default="")
    checked_at = Column(DateTime(timezone=True), nullable=False)


class MarketHistoryDatabase:
    def __init__(self) -> None:
        self.engine = None
        self.sessions = None
        if Config.DB_CONNECTION_STRING:
            self.engine = create_engine(
                Config.DB_CONNECTION_STRING, poolclass=pool.QueuePool, pool_size=2,
                max_overflow=3, pool_recycle=1800,
            )
            self.sessions = sessionmaker(bind=self.engine)
            try:
                Base.metadata.create_all(self.engine)
            except Exception:
                logger.exception("Market history schema initialization failed")

    def write_source_day(self, source_key: str, trading_date: date, product_type: str,
                         rows: list[dict[str, Any]], codes: list[str], *, status: str,
                         detail: str = "", source_url: str = "", unit: str = "") -> int:
        """Upsert the rows for a source/date and record per-code coverage, including no-data."""
        if not self.sessions:
            return 0
        now = datetime.now(timezone.utc)
        by_code = {str(row.get("code", "")).strip().upper(): row for row in rows}
        wanted = {str(code).strip().upper() for code in codes if str(code).strip()}
        records = []
        coverages = []
        for code in sorted(wanted):
            row = by_code.get(code)
            if row:
                records.append({
                    "source_key": source_key, "product_type": product_type, "code": code,
                    "name": str(row.get("name") or code), "trading_date": trading_date,
                    "values_json": json.dumps(row.get("values") or {}, ensure_ascii=False),
                    "unit": unit, "source_url": source_url, "fetched_at": now, "recorded_at": now,
                })
                coverage_status, count = "ok", 1
            else:
                coverage_status, count = status, 0
            coverages.append({
                "source_key": source_key, "code": code, "trading_date": trading_date,
                "status": coverage_status, "record_count": count, "detail": detail,
                "checked_at": now,
            })
        try:
            with self.sessions.begin() as session:
                if records:
                    statement = insert(MarketDailyHistory).values(records)
                    session.execute(statement.on_conflict_do_update(
                        constraint="uq_market_daily_history_identity",
                        set_={key: getattr(statement.excluded, key) for key in
                              ("name", "values_json", "unit", "source_url", "fetched_at", "recorded_at")},
                    ))
                if coverages:
                    statement = insert(MarketHistoryCoverage).values(coverages)
                    session.execute(statement.on_conflict_do_update(
                        constraint="uq_market_history_coverage_identity",
                        set_={key: getattr(statement.excluded, key) for key in
                              ("status", "record_count", "detail", "checked_at")},
                    ))
            return len(records)
        except Exception:
            logger.exception("Failed to persist market history for %s on %s", source_key, trading_date)
            raise

    def history(self, code: str, from_date: date, to_date: date,
                sources: list[str] | None = None) -> dict[str, Any]:
        if not self.sessions:
            return {"points": [], "coverage": []}
        code = code.strip().upper()
        with self.sessions() as session:
            query = session.query(MarketDailyHistory).filter(
                MarketDailyHistory.code == code,
                MarketDailyHistory.trading_date >= from_date,
                MarketDailyHistory.trading_date <= to_date,
            )
            coverage_query = session.query(MarketHistoryCoverage).filter(
                MarketHistoryCoverage.code == code,
                MarketHistoryCoverage.trading_date >= from_date,
                MarketHistoryCoverage.trading_date <= to_date,
            )
            if sources:
                query = query.filter(MarketDailyHistory.source_key.in_(sources))
                coverage_query = coverage_query.filter(MarketHistoryCoverage.source_key.in_(sources))
            elif code in {"TXF", "QFF"} or code.startswith(("TXF", "QFF")):
                futures_sources = ["taifex:daily-futures-price", "taifex:futures-institutional"]
                query = query.filter(MarketDailyHistory.source_key.in_(futures_sources))
                coverage_query = coverage_query.filter(MarketHistoryCoverage.source_key.in_(futures_sources))
            records = query.order_by(MarketDailyHistory.trading_date, MarketDailyHistory.source_key).all()
            coverage = coverage_query.order_by(MarketHistoryCoverage.trading_date, MarketHistoryCoverage.source_key).all()
        points_by_date: dict[str, dict[str, Any]] = {}
        for row in records:
            day = row.trading_date.isoformat()
            point = points_by_date.setdefault(day, {"date": day, "code": code, "name": row.name, "sources": {}})
            point["sources"][row.source_key] = json.loads(row.values_json)
        return {
            "points": list(points_by_date.values()),
            "coverage": [{"date": row.trading_date.isoformat(), "source": row.source_key,
                          "status": row.status, "detail": row.detail} for row in coverage],
        }

    def covered_codes(self, source_keys: list[str], codes: list[str], trading_dates: list[date]) -> set[tuple[str, str, date]]:
        if not self.sessions or not source_keys or not codes or not trading_dates:
            return set()
        with self.sessions() as session:
            rows = session.query(MarketHistoryCoverage.source_key, MarketHistoryCoverage.code,
                                 MarketHistoryCoverage.trading_date).filter(
                MarketHistoryCoverage.source_key.in_(source_keys),
                MarketHistoryCoverage.code.in_([code.upper() for code in codes]),
                MarketHistoryCoverage.trading_date.in_(trading_dates),
            ).all()
        return {(row[0], row[1], row[2]) for row in rows}

    @contextmanager
    def collection_lock(self):
        """Run only one backfill/daily collector across all Maya Sawa pods."""
        if not self.engine:
            yield False
            return
        connection = self.engine.connect()
        acquired = False
        try:
            acquired = bool(connection.execute(
                text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": 731041014}
            ).scalar())
            yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": 731041014})
                except Exception:
                    logger.exception("Failed to release market history collection lock")
            connection.close()


market_history_db = MarketHistoryDatabase()
