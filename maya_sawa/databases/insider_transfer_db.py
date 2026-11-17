"""Insiders' pre-filed share transfers, kept past the one day the OpenAPI lists them (docs/INSIDER_TRANSFERS.md)."""
import json
from datetime import date, timedelta

from sqlalchemy import BigInteger, Boolean, Column, Date, Integer, Text, delete, select
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
FIELDS = ("market", "code", "name", "role", "holder", "method", "sale", "shares", "held", "filed", "start", "end")


class InsiderTransfer(Base):
    __tablename__ = "maya_sawa_insider_transfer"
    market = Column(Text, primary_key=True)
    code = Column(Text, primary_key=True)
    holder = Column(Text, primary_key=True)
    method = Column(Text, primary_key=True)
    filed = Column(Date, primary_key=True)
    start = Column(Date, primary_key=True)
    name = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    sale = Column(Boolean, nullable=False)
    shares = Column(Integer, nullable=False)
    held = Column(Integer, nullable=False)
    end = Column(Date, nullable=False)


class InsiderUntransferred(Base):
    __tablename__ = "maya_sawa_insider_untransferred"
    market = Column(Text, primary_key=True)
    code = Column(Text, primary_key=True)
    holder = Column(Text, primary_key=True)
    filed = Column(Date, primary_key=True)
    name = Column(Text, nullable=False)
    role = Column(Text, nullable=False)
    shares = Column(BigInteger, nullable=False)
    planned = Column(BigInteger, nullable=False)
    reason = Column(Text, nullable=False)


class InsiderHoldingSnapshot(Base):
    """One row per market: the latest month's holdings as JSON ({code: {name, persons}}), kept for next month's comparison."""
    __tablename__ = "maya_sawa_insider_holding_snapshot"
    market = Column(Text, primary_key=True)
    month = Column(Text, nullable=False)
    data = Column(Text, nullable=False)


class InsiderHoldingChange(Base):
    __tablename__ = "maya_sawa_insider_holding_change"
    market = Column(Text, primary_key=True)
    code = Column(Text, primary_key=True)
    month = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    net = Column(BigInteger, nullable=False)
    increased = Column(Integer, nullable=False)
    compared = Column(Integer, nullable=False)
    uniform = Column(Boolean, nullable=False)


UNTRANSFERRED_FIELDS = ("market", "code", "name", "role", "holder", "shares", "planned", "reason", "filed")
CHANGE_FIELDS = ("market", "code", "month", "name", "net", "increased", "compared", "uniform")


class InsiderTransferDatabase:
    # Closed windows are kept a while for reference, then dropped so the table stays a few hundred rows.
    KEEP_DAYS = 120

    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def save(self, filings: list[dict]) -> None:
        if not self.sessions:
            return
        with self.sessions.begin() as session:
            for filing in filings:
                session.merge(InsiderTransfer(**{field: filing[field] for field in FIELDS}))
            session.execute(delete(InsiderTransfer).where(InsiderTransfer.end < date.today() - timedelta(days=self.KEEP_DAYS)))

    def open_on(self, day: date) -> list[dict]:
        """Filings whose transfer window has not closed by `day`."""
        if not self.sessions:
            return []
        with self.sessions() as session:
            rows = session.execute(select(InsiderTransfer).where(InsiderTransfer.end >= day)).scalars()
            return [{field: getattr(row, field) for field in FIELDS} for row in rows]

    def save_untransferred(self, rows: list[dict]) -> None:
        if not self.sessions or not rows:
            return
        with self.sessions.begin() as session:
            for row in rows:
                session.merge(InsiderUntransferred(**{field: row[field] for field in UNTRANSFERRED_FIELDS}))
            session.execute(delete(InsiderUntransferred).where(InsiderUntransferred.filed < date.today() - timedelta(days=self.KEEP_DAYS)))

    def untransferred_since(self, day: date) -> list[dict]:
        if not self.sessions:
            return []
        with self.sessions() as session:
            rows = session.execute(select(InsiderUntransferred).where(InsiderUntransferred.filed >= day)).scalars()
            return [{field: getattr(row, field) for field in UNTRANSFERRED_FIELDS} for row in rows]

    def latest_snapshot(self, market: str):
        """(month, {code: {name, persons}}) last stored for the market, or None."""
        if not self.sessions:
            return None
        with self.sessions() as session:
            row = session.get(InsiderHoldingSnapshot, market)
            return (row.month, json.loads(row.data)) if row else None

    def save_holdings(self, market: str, month: str, snapshot: dict, changes: list[dict]) -> None:
        if not self.sessions:
            return
        with self.sessions.begin() as session:
            session.merge(InsiderHoldingSnapshot(market=market, month=month, data=json.dumps(snapshot, ensure_ascii=False)))
            for change in changes:
                session.merge(InsiderHoldingChange(**{field: change[field] for field in CHANGE_FIELDS}))

    def latest_changes(self) -> list[dict]:
        """Each market's most recent month of holding changes."""
        if not self.sessions:
            return []
        with self.sessions() as session:
            rows = list(session.execute(select(InsiderHoldingChange)).scalars())
            latest: dict[str, str] = {}
            for row in rows:
                latest[row.market] = max(latest.get(row.market, ""), row.month)
            return [{field: getattr(row, field) for field in CHANGE_FIELDS} for row in rows if row.month == latest[row.market]]
