"""Durable IBKR source data, identified by market + code + conid.

`latest` is the last successful result; `attempt` also records failures. Dated
records preserve source history without duplicating a yearly backfill each poll.
Private portfolio snapshots use a reserved PRIVATE identity and have no public API.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache

from sqlalchemy import Column, DateTime, Integer, Text, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..core.config.config import Config

Base = declarative_base()


class IbkrDataset(Base):
    __tablename__ = 'maya_sawa_ibkr_datasets'
    code = Column(Text, primary_key=True)
    market = Column(Text, primary_key=True)
    kind = Column(Text, primary_key=True)
    period = Column(Text, primary_key=True)
    conid = Column(Integer, nullable=False)
    payload_json = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False)


class IbkrResearchDatabase:
    def __init__(self, engine=None):
        self.engine = engine or create_engine(Config.DB_CONNECTION_STRING, pool_pre_ping=True,
                                               pool_size=2, max_overflow=2)
        self.sessions = sessionmaker(bind=self.engine)
        Base.metadata.create_all(self.engine)

    def save(self, code, market, conid, kind, payload, *, period=None, status='ok'):
        now = datetime.now(timezone.utc)
        periods = ['attempt']
        if status == 'ok':
            periods += ['latest'] + ([period] if period else [])
        insert = sqlite_insert if self.engine.dialect.name == 'sqlite' else pg_insert
        with self.sessions.begin() as session:
            for key in periods:
                stmt = insert(IbkrDataset).values(code=code.upper(), market=market.upper(), conid=conid,
                    kind=kind, period=key, payload_json=json.dumps(payload, ensure_ascii=False),
                    status=status, fetched_at=now)
                session.execute(stmt.on_conflict_do_update(
                    index_elements=['code', 'market', 'kind', 'period'],
                    set_={k: getattr(stmt.excluded, k) for k in ('conid', 'payload_json', 'status', 'fetched_at')}))

    @staticmethod
    def _expose(row):
        stamp = row.fetched_at
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return {'code': row.code, 'market': row.market, 'conid': row.conid, 'kind': row.kind,
                'period': row.period, 'status': row.status, 'fetchedAt': stamp.isoformat(),
                'payload': json.loads(row.payload_json)}

    def latest(self, code, market, kind, *, successful=True):
        with self.sessions() as session:
            row = session.get(IbkrDataset, (code.upper(), market.upper(), kind, 'latest' if successful else 'attempt'))
            return self._expose(row) if row else None

    def history(self, code, market, kind, limit=1000):
        with self.sessions() as session:
            rows = session.scalars(select(IbkrDataset).where(
                IbkrDataset.code == code.upper(), IbkrDataset.market == market.upper(),
                IbkrDataset.kind == kind, IbkrDataset.period.notin_(['latest', 'attempt'])
            ).order_by(IbkrDataset.period.desc()).limit(limit)).all()
            return [self._expose(row) for row in reversed(rows)]


@lru_cache(maxsize=1)
def get_ibkr_research_db():
    return IbkrResearchDatabase()
