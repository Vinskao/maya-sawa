"""Time-series history of the merged (Taiwan + overseas) portfolio.

Snapshots are written periodically so the dashboard has a historical record
beyond the volatile Redis cache. The full merged payload is stored as JSON for
replay, alongside scalar region columns for easy charting/aggregation.

DB target follows the rest of maya-sawa: the main DB connection (DB_* env),
which is Neon locally and the in-cluster Postgres in OKE.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Numeric,
    Text,
    create_engine,
    pool,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from ..core.config.config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()


class PortfolioHistory(Base):
    __tablename__ = "maya_sawa_portfolio_history"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    captured_at = Column(DateTime(timezone=True), nullable=False, index=True)
    usd_twd_rate = Column(Numeric, nullable=True)

    total_cash = Column(Numeric, nullable=True)
    total_assets = Column(Numeric, nullable=True)
    total_pnl = Column(Numeric, nullable=True)
    total_leverage = Column(Numeric, nullable=True)

    tw_cash = Column(Numeric, nullable=True)
    tw_assets = Column(Numeric, nullable=True)
    tw_pnl = Column(Numeric, nullable=True)

    os_cash = Column(Numeric, nullable=True)
    os_assets = Column(Numeric, nullable=True)
    os_pnl = Column(Numeric, nullable=True)

    snapshot = Column(Text, nullable=False)  # full merged portfolio (JSON)
    created_at = Column(DateTime(timezone=True), nullable=False)


class PortfolioHistoryDatabase:
    _instance = None
    _engine = None
    _session_factory = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    _last_write_monotonic: float = 0.0

    def __init__(self) -> None:
        if self._engine is None:
            self._initialize_engine()
        self._interval_seconds = int(
            os.getenv("PORTFOLIO_HISTORY_INTERVAL_SECONDS", "3600")
        )

    def _initialize_engine(self) -> None:
        db_url = Config.DB_CONNECTION_STRING  # main Postgres: Neon local / in-cluster
        if not db_url:
            logger.warning("Portfolio history database URL not configured")
            return
        self._engine = create_engine(
            db_url,
            poolclass=pool.QueuePool,
            pool_size=2,
            max_overflow=5,
            pool_timeout=30,
            pool_recycle=1800,
            echo=False,
        )
        self._session_factory = sessionmaker(bind=self._engine)
        try:
            Base.metadata.create_all(self._engine)
        except Exception:
            logger.exception("Failed to ensure portfolio_history table")
        logger.info("Portfolio history database initialized")

    def is_available(self) -> bool:
        return self._engine is not None

    @contextmanager
    def get_session(self):
        if self._session_factory is None:
            raise RuntimeError("Portfolio history database not initialized")
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def record(self, portfolio: dict[str, Any]) -> bool:
        """Insert one snapshot row. Returns False if the DB is unavailable."""
        if not self.is_available():
            return False
        regions = portfolio.get("regions") or {}
        tw = regions.get("taiwan") or {}
        os_ = regions.get("overseas") or {}
        total = regions.get("total") or {}
        ibkr = portfolio.get("ibkr") or {}
        now = datetime.now(timezone.utc)
        row = PortfolioHistory(
            captured_at=now,
            usd_twd_rate=ibkr.get("usdTwdRate"),
            total_cash=total.get("cash"),
            total_assets=total.get("totalAssets"),
            total_pnl=total.get("totalPnl"),
            total_leverage=total.get("leverage"),
            tw_cash=tw.get("cash"),
            tw_assets=tw.get("totalAssets"),
            tw_pnl=tw.get("totalPnl"),
            os_cash=os_.get("cash"),
            os_assets=os_.get("totalAssets"),
            os_pnl=os_.get("totalPnl"),
            snapshot=json.dumps(portfolio, ensure_ascii=True, default=str),
            created_at=now,
        )
        with self.get_session() as session:
            session.add(row)
        return True

    def record_if_due(self, portfolio: dict[str, Any]) -> bool:
        """Record a snapshot at most once per PORTFOLIO_HISTORY_INTERVAL_SECONDS."""
        if not self.is_available():
            return False
        now = time.monotonic()
        if self._last_write_monotonic and (
            now - self._last_write_monotonic < self._interval_seconds
        ):
            return False
        try:
            recorded = self.record(portfolio)
        except Exception:
            logger.exception("Failed to record portfolio history")
            return False
        if recorded:
            self._last_write_monotonic = now
        return recorded

    def latest_snapshot(self) -> Optional[dict[str, Any]]:
        """Return the most recent merged portfolio payload, or None."""
        if not self.is_available():
            return None
        with self.get_session() as session:
            row = (
                session.query(PortfolioHistory)
                .order_by(PortfolioHistory.captured_at.desc())
                .first()
            )
            if row is None:
                return None
            return json.loads(row.snapshot)

    def history(self, limit: int = 90) -> list[dict[str, Any]]:
        """Return recent scalar history rows (newest first) for charting."""
        limit = min(max(limit, 1), 1000)
        with self.get_session() as session:
            rows = (
                session.query(PortfolioHistory)
                .order_by(PortfolioHistory.captured_at.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "capturedAt": r.captured_at.isoformat() if r.captured_at else None,
                    "usdTwdRate": float(r.usd_twd_rate) if r.usd_twd_rate is not None else None,
                    "total": {
                        "cash": float(r.total_cash) if r.total_cash is not None else None,
                        "totalAssets": float(r.total_assets) if r.total_assets is not None else None,
                        "totalPnl": float(r.total_pnl) if r.total_pnl is not None else None,
                        "leverage": float(r.total_leverage) if r.total_leverage is not None else None,
                    },
                    "taiwan": {
                        "cash": float(r.tw_cash) if r.tw_cash is not None else None,
                        "totalAssets": float(r.tw_assets) if r.tw_assets is not None else None,
                        "totalPnl": float(r.tw_pnl) if r.tw_pnl is not None else None,
                    },
                    "overseas": {
                        "cash": float(r.os_cash) if r.os_cash is not None else None,
                        "totalAssets": float(r.os_assets) if r.os_assets is not None else None,
                        "totalPnl": float(r.os_pnl) if r.os_pnl is not None else None,
                    },
                }
                for r in rows
            ]


portfolio_history_db = PortfolioHistoryDatabase()
