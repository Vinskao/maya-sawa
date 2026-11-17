"""Insiders' pre-filed share transfers, kept past the one day the OpenAPI lists them (docs/INSIDER_TRANSFERS.md)."""
from datetime import date, timedelta

from sqlalchemy import Boolean, Column, Date, Integer, Text, delete, select
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
