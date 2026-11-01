"""Broker target prices: one row per broker action, and one consensus snapshot per day, stored in Postgres."""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Column, Date, DateTime, Float, Integer, Text, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class PriceTargetAction(Base):
    __tablename__ = "maya_sawa_market_price_target"
    code = Column(Text, primary_key=True)
    market = Column(Text, primary_key=True)
    firm = Column(Text, primary_key=True)
    action_date = Column(Date, primary_key=True)
    source = Column(Text, primary_key=True)  # yahoo | ai-routine
    action = Column(Text)
    rating = Column(Text)
    previous_rating = Column(Text)
    target = Column(Float)  # None: a rating change without a target
    previous_target = Column(Float)
    currency = Column(Text, nullable=False)
    source_url = Column(Text, nullable=False)
    thesis = Column(Text)  # the broker's reasoning, from the article or report
    report_id = Column(Text)  # maya_sawa_market_reports.id when the target came from a stored report
    recorded_at = Column(DateTime(timezone=True), nullable=False)


class PriceTargetConsensus(Base):
    __tablename__ = "maya_sawa_market_price_target_consensus"
    code = Column(Text, primary_key=True)
    market = Column(Text, primary_key=True)
    snapshot_date = Column(Date, primary_key=True)
    source = Column(Text, primary_key=True)
    mean = Column(Float)
    median = Column(Float)
    high = Column(Float)
    low = Column(Float)
    analysts = Column(Integer)
    currency = Column(Text, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)


class EpsEstimate(Base):
    """Daily consensus EPS for the current and next fiscal year (forward P/E). source yahoo is that day's snapshot;
    yahoo-trend is backfilled from Yahoo's 7/30/60/90-days-ago figures and never replaces a real snapshot."""
    __tablename__ = "maya_sawa_market_eps_estimate"
    code = Column(Text, primary_key=True)
    market = Column(Text, primary_key=True)
    snapshot_date = Column(Date, primary_key=True)
    source = Column(Text, primary_key=True)
    fy0_end = Column(Date, nullable=False)
    fy0_eps = Column(Float, nullable=False)
    fy0_analysts = Column(Integer)
    fy1_end = Column(Date, nullable=False)
    fy1_eps = Column(Float, nullable=False)
    fy1_analysts = Column(Integer)
    currency = Column(Text, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)


class MarketPriceTargetDatabase:
    def __init__(self, engine):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)
            if engine.dialect.name == "postgresql":  # create_all does not add columns to an existing table
                with engine.begin() as connection:
                    connection.execute(text("ALTER TABLE maya_sawa_market_price_target ADD COLUMN IF NOT EXISTS thesis text"))
                    connection.execute(text("ALTER TABLE maya_sawa_market_price_target ADD COLUMN IF NOT EXISTS report_id text"))

    def _upsert(self, session, table, values, keys):
        insert = sqlite_insert if self.engine.dialect.name == "sqlite" else pg_insert
        stmt = insert(table).values(**values)
        session.execute(stmt.on_conflict_do_update(index_elements=keys,
            set_={key: getattr(stmt.excluded, key) for key in values if key not in keys}))

    def save_actions(self, code, market, currency, actions, *, source, source_url=None) -> int:
        if not self.sessions:
            raise RuntimeError("Price target database unavailable")
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            for row in actions:
                self._upsert(session, PriceTargetAction, {
                    "code": code.upper(), "market": market.upper(), "firm": row["firm"],
                    "action_date": date.fromisoformat(row["date"]), "source": source, "action": row.get("action"),
                    "rating": row.get("rating"), "previous_rating": row.get("previousRating"), "target": row.get("target"),
                    "previous_target": row.get("previousTarget"), "currency": currency,
                    "source_url": row.get("sourceUrl") or source_url or "", "thesis": row.get("thesis"),
                    "report_id": row.get("reportId"), "recorded_at": now,
                }, ["code", "market", "firm", "action_date", "source"])
        return len(actions)

    def save_consensus(self, code, market, day: date, consensus, *, source) -> None:
        if not self.sessions:
            raise RuntimeError("Price target database unavailable")
        with self.sessions.begin() as session:
            self._upsert(session, PriceTargetConsensus, {
                "code": code.upper(), "market": market.upper(), "snapshot_date": day, "source": source,
                **{key: consensus.get(key) for key in ("mean", "median", "high", "low", "analysts")},
                "currency": consensus["currency"], "recorded_at": datetime.now(timezone.utc),
            }, ["code", "market", "snapshot_date", "source"])

    def save_eps_estimates(self, code, market, day: date, estimates, *, source) -> None:
        if not self.sessions:
            raise RuntimeError("Price target database unavailable")
        fy0, fy1 = estimates["years"]
        fy0_end, fy1_end = date.fromisoformat(fy0["end"]), date.fromisoformat(fy1["end"])
        base = {"code": code.upper(), "market": market.upper(), "fy0_end": fy0_end, "fy1_end": fy1_end,
                "currency": estimates["currency"], "recorded_at": datetime.now(timezone.utc)}
        insert = sqlite_insert if self.engine.dialect.name == "sqlite" else pg_insert
        with self.sessions.begin() as session:
            self._upsert(session, EpsEstimate, {**base, "snapshot_date": day, "source": source,
                "fy0_eps": fy0["eps"], "fy0_analysts": fy0["analysts"], "fy1_eps": fy1["eps"], "fy1_analysts": fy1["analysts"]},
                ["code", "market", "snapshot_date", "source"])
            fiscal_start = fy0_end - timedelta(days=364)  # avoids replace(year=...) on a Feb 29 year end
            for days, old_fy0 in fy0["trend"].items():
                old_fy1, then = fy1["trend"].get(days), day - timedelta(days=days)
                # Before this fiscal year began the "0y" estimate was not the current year: no backfill there.
                if old_fy0 is None or old_fy1 is None or then < fiscal_start:
                    continue
                session.execute(insert(EpsEstimate).values(**base, snapshot_date=then, source=f"{source}-trend",
                    fy0_eps=old_fy0, fy0_analysts=None, fy1_eps=old_fy1, fy1_analysts=None).on_conflict_do_nothing(
                    index_elements=["code", "market", "snapshot_date", "source"]))

    def read(self, code, market) -> dict:
        if not self.sessions:
            raise RuntimeError("Price target database unavailable")
        with self.sessions() as session:
            actions = session.query(PriceTargetAction).filter_by(code=code.upper(), market=market.upper()).order_by(
                PriceTargetAction.action_date, PriceTargetAction.firm).all()
            consensus = session.query(PriceTargetConsensus).filter_by(code=code.upper(), market=market.upper()).order_by(
                PriceTargetConsensus.snapshot_date).all()
            return {
                "actions": [{"firm": row.firm, "date": row.action_date.isoformat(), "action": row.action, "rating": row.rating,
                             "previousRating": row.previous_rating, "target": row.target, "previousTarget": row.previous_target,
                             "currency": row.currency, "source": row.source, "sourceUrl": row.source_url,
                             "thesis": row.thesis, "reportId": row.report_id} for row in actions],
                "consensus": [{"date": row.snapshot_date.isoformat(), "mean": row.mean, "median": row.median, "high": row.high,
                               "low": row.low, "analysts": row.analysts, "currency": row.currency, "source": row.source}
                              for row in consensus],
                "epsEstimates": self._eps_rows(session, code, market),
            }

    @staticmethod
    def _eps_rows(session, code, market) -> list[dict]:
        rows = session.query(EpsEstimate).filter_by(code=code.upper(), market=market.upper()).order_by(
            EpsEstimate.snapshot_date, EpsEstimate.source).all()
        by_date = {}
        for row in rows:  # a real snapshot wins over a trend backfill of the same day
            if row.snapshot_date not in by_date or by_date[row.snapshot_date].source.endswith("-trend"):
                by_date[row.snapshot_date] = row
        return [{"date": day.isoformat(), "source": row.source, "currency": row.currency, "years": [
                    {"end": row.fy0_end.isoformat(), "eps": row.fy0_eps, "analysts": row.fy0_analysts},
                    {"end": row.fy1_end.isoformat(), "eps": row.fy1_eps, "analysts": row.fy1_analysts}]}
                for day, row in sorted(by_date.items())]


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return MarketPriceTargetDatabase(market_dashboard_db.engine)


market_price_target_db = _default_db()
