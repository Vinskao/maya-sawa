"""Persistent, privacy-safe market dashboard selections."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import BigInteger, Column, DateTime, Integer, Text, UniqueConstraint, create_engine, pool
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config.config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()


def public_selection_from_portfolio(portfolio: dict[str, Any], fixed_futures_code: str | None = None) -> list[dict[str, str]] | None:
    """Return label-only top holdings for a complete snapshot, or None if invalid."""
    if not portfolio.get("balanceAvailable") or portfolio.get("accountErrors"):
        return None
    positions = portfolio.get("positions")
    if not isinstance(positions, list):
        return None
    rows = []
    for position in positions:
        kind = position.get("productType")
        code = str(position.get("code") or "").strip().upper()
        name = str(position.get("name") or "").strip()
        try:
            # A portfolio may include multiple currencies. Normalize USD notional
            # using the snapshot's conversion rate before comparing with TWD.
            raw_weight = abs(float(position.get("allocationValue") or position.get("marketValue") or 0))
            currency = str(position.get("currency") or "TWD").upper()
            rate = portfolio.get("usdTwdRate") or portfolio.get("usdTwdExchangeRate") or portfolio.get("fxRateUsdTwd")
            fx = float(rate) if rate else None
            if currency not in {"TWD", "NTD"} and fx is None:
                continue
            weight = raw_weight * fx if currency not in {"TWD", "NTD"} and fx else raw_weight
        except (ValueError, TypeError):
            continue
        if (kind not in {"stock", "futures"} or not code or not name or weight <= 0
                or (kind == "futures" and fixed_futures_code and code == fixed_futures_code.upper())):
            continue
        rows.append({"code": code, "name": name, "productType": kind, "weight": weight})
    if not rows:
        return None
    rows.sort(key=lambda row: (-row["weight"], row["code"], row["productType"]))
    return [{k: row[k] for k in ("code", "name", "productType")} for row in rows[:5]]


class MarketDashboardSnapshot(Base):
    __tablename__ = "maya_sawa_market_dashboard_snapshot"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False)
    snapshot_at = Column(DateTime(timezone=True), nullable=False)
    positions = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("source", "snapshot_at", name="uq_market_dashboard_snapshot"),)


class MarketDashboardSetting(Base):
    __tablename__ = "maya_sawa_market_dashboard_setting"
    id = Column(Integer, primary_key=True)
    custom_symbols = Column(Text, nullable=False, default="[]")
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MarketCandidate(Base):
    """Historical universe of instruments seen in configured source lists."""
    __tablename__ = "maya_sawa_market_candidate"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    product_type = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    delivery_month = Column(Text, nullable=False, default="")
    name = Column(Text, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("product_type", "code", "delivery_month", name="uq_market_candidate_identity"),)


class MarketCandidateSource(Base):
    """Membership history, one row per source and canonical instrument."""
    __tablename__ = "maya_sawa_market_candidate_source"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_key = Column(Text, nullable=False)
    product_type = Column(Text, nullable=False)
    code = Column(Text, nullable=False)
    delivery_month = Column(Text, nullable=False, default="")
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("source_key", "product_type", "code", "delivery_month", name="uq_market_candidate_source_identity"),)


class MarketDashboardDatabase:
    def __init__(self) -> None:
        self.engine = None
        self.sessions = None
        if Config.DB_CONNECTION_STRING:
            self.engine = create_engine(
                Config.DB_CONNECTION_STRING, poolclass=pool.QueuePool,
                pool_size=2, max_overflow=3, pool_recycle=1800,
            )
            self.sessions = sessionmaker(bind=self.engine)
            try:
                Base.metadata.create_all(self.engine)
                with self.engine.begin() as connection:
                    connection.execute(insert(MarketDashboardSetting).values(
                        id=1, custom_symbols="[]", updated_at=datetime.now(timezone.utc)
                    ).on_conflict_do_nothing(index_elements=[MarketDashboardSetting.id]))
            except Exception:
                logger.exception("Market dashboard schema initialization failed")

    def record_portfolio(self, portfolio: dict[str, Any], fixed_futures_code: str | None = None) -> bool:
        """Replace the public auto list only from a complete valid account snapshot."""
        if not self.sessions:
            return False
        selected = public_selection_from_portfolio(portfolio, fixed_futures_code)
        if selected is None:
            return False
        # Only labels are stored. No quantities, values, direction, account IDs, or raw snapshot.
        try:
            snapshot_at = datetime.fromisoformat(str(portfolio["fetchedAt"]).replace("Z", "+00:00"))
            if snapshot_at.tzinfo is None:
                return False
            with self.sessions.begin() as session:
                session.execute(insert(MarketDashboardSnapshot).values(
                    source="shioaji", snapshot_at=snapshot_at,
                    positions=json.dumps(selected, ensure_ascii=False), created_at=datetime.now(timezone.utc),
                ).on_conflict_do_nothing(constraint="uq_market_dashboard_snapshot"))
            return True
        except Exception:
            logger.exception("Failed to persist market dashboard selection")
            return False

    def latest_auto(self) -> dict[str, Any]:
        if not self.sessions:
            return {"positions": [], "snapshotAt": None}
        with self.sessions() as session:
            row = session.query(MarketDashboardSnapshot).order_by(MarketDashboardSnapshot.snapshot_at.desc()).first()
            if not row:
                return {"positions": [], "snapshotAt": None}
            return {"positions": json.loads(row.positions), "snapshotAt": row.snapshot_at.isoformat()}

    def custom_symbols(self) -> list[dict[str, str]]:
        if not self.sessions:
            return []
        with self.sessions() as session:
            row = session.get(MarketDashboardSetting, 1)
            return json.loads(row.custom_symbols) if row else []

    def save_custom_symbols(self, symbols: list[dict[str, str]]) -> None:
        if not self.sessions:
            raise RuntimeError("Market dashboard database is unavailable")
        with self.sessions.begin() as session:
            row = session.get(MarketDashboardSetting, 1)
            if row is None:
                row = MarketDashboardSetting(id=1, custom_symbols="[]", updated_at=datetime.now(timezone.utc))
                session.add(row)
            row.custom_symbols = json.dumps(symbols, ensure_ascii=False)
            row.updated_at = datetime.now(timezone.utc)

    def record_candidates(self, source_key: str, symbols: list[dict[str, str]]) -> int:
        """Upsert a source-list observation, retaining absent history for 90 days."""
        if not self.sessions:
            return 0
        now = datetime.now(timezone.utc)
        count = 0
        with self.sessions.begin() as session:
            for item in symbols:
                kind = str(item.get("productType") or "").strip()
                code = str(item.get("code") or "").strip().upper()
                month = str(item.get("deliveryMonth") or "").strip()
                name = str(item.get("name") or "").strip()
                if kind not in {"stock", "futures"} or not code or not name:
                    continue
                identity = (kind, code, month if kind == "futures" else "")
                candidate = session.query(MarketCandidate).filter_by(
                    product_type=identity[0], code=identity[1], delivery_month=identity[2]
                ).one_or_none()
                if candidate is None:
                    session.add(MarketCandidate(product_type=identity[0], code=identity[1],
                        delivery_month=identity[2], name=name, first_seen_at=now, last_seen_at=now,
                        expires_at=now + timedelta(days=90)))
                else:
                    candidate.name = name
                    candidate.last_seen_at = now
                    candidate.expires_at = now + timedelta(days=90)
                membership = session.query(MarketCandidateSource).filter_by(
                    source_key=source_key, product_type=identity[0], code=identity[1], delivery_month=identity[2]
                ).one_or_none()
                if membership is None:
                    session.add(MarketCandidateSource(source_key=source_key,
                        product_type=identity[0], code=identity[1], delivery_month=identity[2],
                        first_seen_at=now, last_seen_at=now,
                        expires_at=now + timedelta(days=90)))
                else:
                    membership.last_seen_at = now
                    membership.expires_at = now + timedelta(days=90)
                count += 1
        return count

    def list_candidates(self, query: str = "", limit: int = 100) -> list[dict[str, str]]:
        if not self.sessions:
            return []
        now = datetime.now(timezone.utc)
        with self.sessions() as session:
            rows = session.query(MarketCandidate).filter(
                (MarketCandidate.expires_at.is_(None)) | (MarketCandidate.expires_at > now)
            ).order_by(MarketCandidate.product_type, MarketCandidate.code, MarketCandidate.delivery_month).all()
            term = query.strip().casefold()
            return [{"code": row.code, "name": row.name, "productType": row.product_type,
                     **({"deliveryMonth": row.delivery_month} if row.delivery_month else {})}
                    for row in rows if not term or term in row.code.casefold() or term in row.name.casefold()][:limit]


market_dashboard_db = MarketDashboardDatabase()
