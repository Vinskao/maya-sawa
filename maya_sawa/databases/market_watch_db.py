"""Storage for the AI watch list (see services/market_watch.py for the rules)."""
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

from ..services import market_watch

Base = declarative_base()


class MarketWatch(Base):
    __tablename__ = "maya_sawa_market_watch"
    code = Column(Text, primary_key=True)
    market = Column(Text, primary_key=True)
    name = Column(Text, nullable=False, default="")
    status = Column(Text, nullable=False)  # candidate | watching | expired | held
    mentions = Column(Text, nullable=False, default="[]")
    promoted_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False)


def _as_utc(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


class MarketWatchDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def load(self) -> list[dict]:
        if not self.sessions:
            raise RuntimeError("Watch list database unavailable")
        with self.sessions() as session:
            return [{"code": row.code, "market": row.market, "name": row.name, "status": row.status,
                     "mentions": json.loads(row.mentions),
                     "promotedAt": _as_utc(row.promoted_at).isoformat() if row.promoted_at else None}
                    for row in session.query(MarketWatch).order_by(MarketWatch.code).all()]

    def _save(self, rows: list[dict], now: datetime) -> None:
        with self.sessions.begin() as session:
            session.query(MarketWatch).delete()
            for row in rows:
                session.add(MarketWatch(code=row["code"], market=row["market"], name=row.get("name") or "", status=row["status"],
                                        mentions=json.dumps(row["mentions"], ensure_ascii=False), updated_at=now,
                                        promoted_at=datetime.fromisoformat(row["promotedAt"]) if row.get("promotedAt") else None))

    def current(self, now: datetime | None = None, held: set[str] | None = None) -> list[dict]:
        """The watched stocks right now. Expiry and purchases are applied here, so the list is right without a timer."""
        now = now or datetime.now(timezone.utc)
        before = self.load()
        after = market_watch.evaluate(before, set(held or ()), now)
        if after != before:
            self._save(after, now)
        return market_watch.visible(after)

    def candidates(self) -> list[dict]:
        return [{"code": row["code"], "market": row["market"], "name": row["name"], "reports": len({m["source"] for m in row["mentions"]}),
                 "lastMentioned": market_watch.last_mentioned(row).isoformat(), "reason": max(row["mentions"], key=lambda m: m["at"])["reason"]}
                for row in self.load() if row["status"] == "candidate"]

    def nominate(self, code: str, market: str, name: str, mentions: list[dict], now: datetime | None = None,
                 held: set[str] | None = None) -> tuple[list[dict], list[str]]:
        now = now or datetime.now(timezone.utc)
        rows = self.load()
        was_watching = {row["code"] for row in rows if row["status"] == "watching"}
        for mention in mentions:
            rows = market_watch.nominate(rows, code, market, name, mention, now, held=set(held or ()))
        self._save(rows, now)
        promoted = [row["code"] for row in rows if row["status"] == "watching" and row["code"] not in was_watching]
        return rows, promoted


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return MarketWatchDatabase(market_dashboard_db.engine)


market_watch_db = _default_db()
