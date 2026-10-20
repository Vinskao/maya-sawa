"""Current AI commentary and immutable revision history, stored in Postgres."""
from datetime import datetime, timezone
import re

from sqlalchemy import Column, DateTime, Integer, Text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declarative_base, sessionmaker

from .market_dashboard_db import market_dashboard_db

Base = declarative_base()


class MarketAiAnalysis(Base):
    __tablename__ = "maya_sawa_market_ai_analysis"
    product_type = Column(Text, primary_key=True)
    code = Column(Text, primary_key=True)
    revision = Column(Integer, nullable=False)
    model = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    updated_by = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MarketAiAnalysisRevision(Base):
    __tablename__ = "maya_sawa_market_ai_analysis_revision"
    product_type = Column(Text, primary_key=True)
    code = Column(Text, primary_key=True)
    revision = Column(Integer, primary_key=True)
    model = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    updated_by = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class AnalysisConflict(Exception):
    pass


def public_analysis(row):
    return {"code": row.code, "productType": row.product_type, "revision": row.revision,
            "model": row.model, "content": row.content, "updatedAt": row.updated_at.isoformat()}


class MarketAiAnalysisDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def read(self, product_type, code):
        if not self.sessions:
            raise RuntimeError("Analysis database unavailable")
        with self.sessions() as session:
            current = session.get(MarketAiAnalysis, (product_type, code))
            history = session.query(MarketAiAnalysisRevision).filter_by(product_type=product_type, code=code).order_by(
                MarketAiAnalysisRevision.revision.desc()).limit(20).all()
            return {"analysis": public_analysis(current) if current else None,
                    "history": [public_analysis(row) for row in history]}

    def last_editor(self, product_type, code):
        if not self.sessions:
            raise RuntimeError("Analysis database unavailable")
        with self.sessions() as session:
            current = session.get(MarketAiAnalysis, (product_type, code))
            return current.updated_by if current else None

    def list(self, product_type):
        if not self.sessions:
            raise RuntimeError("Analysis database unavailable")
        with self.sessions() as session:
            rows = session.query(MarketAiAnalysis).filter_by(product_type=product_type).order_by(MarketAiAnalysis.code).all()
            return [public_analysis(row) for row in rows]

    def save(self, product_type, code, model, content, expected_revision, editor):
        if not self.sessions:
            raise RuntimeError("Analysis database unavailable")
        # Some scheduled clients serialize literal ``\\n`` at the end of each
        # markdown line before writing it as multiline text. Remove only those
        # line-ending escape tokens; preserve intentional ``\\n`` inside lines.
        content = re.sub(r"(?:\\n)+(?=\r?$)", "", content, flags=re.MULTILINE)
        now = datetime.now(timezone.utc)
        values = dict(model=model, content=content, updated_by=editor, updated_at=now,
                      revision=expected_revision + 1)
        with self.sessions.begin() as session:
            if expected_revision == 0:
                saved = session.execute(insert(MarketAiAnalysis).values(
                    product_type=product_type, code=code, created_at=now, **values
                ).on_conflict_do_nothing(index_elements=["product_type", "code"]).returning(MarketAiAnalysis.code)).first()
            else:
                saved = session.execute(update(MarketAiAnalysis).where(
                    MarketAiAnalysis.product_type == product_type, MarketAiAnalysis.code == code,
                    MarketAiAnalysis.revision == expected_revision,
                ).values(**values).returning(MarketAiAnalysis.code)).first()
            if not saved:
                current = session.get(MarketAiAnalysis, (product_type, code))
                # A retry of an already committed request does not create a duplicate revision.
                if (current and current.revision == expected_revision + 1 and current.model == model
                        and current.content == content and current.updated_by == editor):
                    return public_analysis(current)
                raise AnalysisConflict("Analysis changed; reload the current revision before updating")
            session.add(MarketAiAnalysisRevision(product_type=product_type, code=code, **values))
            session.flush()
            return public_analysis(session.get(MarketAiAnalysis, (product_type, code)))


market_ai_analysis_db = MarketAiAnalysisDatabase(market_dashboard_db.engine)
