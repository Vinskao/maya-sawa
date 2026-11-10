"""Anonymous reader events for the north star metric: weekly returning research readers (docs/NORTH_STAR_METRIC.md).

A reader is a random id the browser made up; no account, IP address, user agent or page address is stored. One row is one
reader's count of one event on one target on one Taipei day, so repeats add to a number instead of adding rows.
"""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Column, Integer, Text, UniqueConstraint, func, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
TAIPEI = timezone(timedelta(hours=8))
# Opening research, an AI analysis or a report's claims is reading research; the other events are secondary numbers.
READING_EVENTS = ("research_open", "analysis_open", "claims_open")
EVENTS = READING_EVENTS + ("hero_search", "topic_pick")
VISITOR_PATTERN = r"^[A-Za-z0-9_-]{16,64}$"
TARGET_LIMIT = 80
RETURN_WINDOW_DAYS = 28


class ReaderEvent(Base):
    __tablename__ = "maya_sawa_reader_event"
    __table_args__ = (UniqueConstraint("visitor", "day", "event", "target", name="uq_reader_event_visitor_day_event_target"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    visitor = Column(Text, nullable=False)
    day = Column(Text, nullable=False, index=True)  # Taipei calendar day, YYYY-MM-DD
    event = Column(Text, nullable=False)
    target = Column(Text, nullable=False, default="")
    count = Column(Integer, nullable=False, default=1)


def _taipei_day(now: datetime | None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(TAIPEI).date()


class ReaderEventDatabase:
    DAILY_ROW_LIMIT = 200  # rows one reader can add in a day; later events that day are dropped

    def __init__(self, engine):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def _require(self):
        if not self.sessions:
            raise RuntimeError("Reader event database unavailable")

    def record(self, visitor: str, event: str, target: str = "", now: datetime | None = None) -> bool:
        """Count one event. Returns False when the reader has reached the daily row limit and nothing was stored."""
        self._require()
        if not re.match(VISITOR_PATTERN, visitor or ""):
            raise ValueError("Visitor id must be 16 to 64 letters, digits, hyphens or underscores")
        if event not in EVENTS:
            raise ValueError("Unknown reader event")
        target = target or ""
        if len(target) > TARGET_LIMIT:
            raise ValueError("Target is too long")
        day = _taipei_day(now).isoformat()
        with self.sessions.begin() as session:
            row = session.query(ReaderEvent).filter_by(visitor=visitor, day=day, event=event, target=target).one_or_none()
            if row is not None:
                row.count += 1
                return True
            rows_today = session.query(func.count(ReaderEvent.id)).filter_by(visitor=visitor, day=day).scalar() or 0
            if rows_today >= self.DAILY_ROW_LIMIT:
                return False
            session.add(ReaderEvent(visitor=visitor, day=day, event=event, target=target, count=1))
            return True

    def north_star(self, weeks: int = 8, now: datetime | None = None) -> list[dict]:
        """Newest week first. Weeks run Monday to Sunday in Taipei time; the current week is still filling."""
        self._require()
        weeks = max(1, min(weeks, 26))
        today = _taipei_day(now)
        this_monday = today - timedelta(days=today.weekday())
        first_monday = this_monday - timedelta(weeks=weeks - 1)
        earliest = first_monday - timedelta(days=RETURN_WINDOW_DAYS)
        with self.sessions() as session:
            rows = session.query(ReaderEvent.visitor, ReaderEvent.day, ReaderEvent.event, ReaderEvent.count).filter(
                ReaderEvent.day >= earliest.isoformat(), ReaderEvent.day <= (this_monday + timedelta(days=6)).isoformat()).all()
        reading_days: dict[str, set[date]] = defaultdict(set)
        for visitor, day, event, _count in rows:
            if event in READING_EVENTS:
                reading_days[visitor].add(date.fromisoformat(day))
        result = []
        for offset in range(weeks):
            start = this_monday - timedelta(weeks=offset)
            end = start + timedelta(days=6)
            window_start = start - timedelta(days=RETURN_WINDOW_DAYS)
            active = {visitor for visitor, days in reading_days.items() if any(start <= day <= end for day in days)}
            returning = {visitor for visitor in active if any(window_start <= day < start for day in reading_days[visitor])}
            events: dict[str, int] = defaultdict(int)
            for _visitor, day, event, count in rows:
                if start.isoformat() <= day <= end.isoformat():
                    events[event] += int(count)
            result.append({"weekStart": start.isoformat(), "weekEnd": end.isoformat(), "activeReaders": len(active),
                           "returningReaders": len(returning), "events": dict(sorted(events.items()))})
        return result

    def row_count(self) -> int:
        self._require()
        with self.sessions() as session:
            return int(session.query(func.count(ReaderEvent.id)).scalar() or 0)

    def columns(self) -> list[str]:
        self._require()
        return [column["name"] for column in inspect(self.engine).get_columns(ReaderEvent.__tablename__)]


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return ReaderEventDatabase(market_dashboard_db.engine)


reader_events_db = _default_db()
