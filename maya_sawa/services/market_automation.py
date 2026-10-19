"""Fire the scheduled AI-analysis routines once the IBKR data they need is in.

IBKR has no headless login: the owner signs in to the Client Portal Gateway by hand, and the session lapses after
about a day. Japan, Korea and US holdings only get new bars while that session is alive. So besides the fixed
schedules, each routine is fired once per trading day as soon as its markets have closed and the overseas bars
were collected after that close. Checks run after every IBKR collection pass and when the owner opens the site.

Routines are fired through the Claude Code routine API (POST .../routines/{id}/fire) with a per-routine token
from the environment (MARKET_ROUTINE_TAIWAN_TOKEN, MARKET_ROUTINE_US_TOKEN). Without a token nothing is fired.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import Column, Date, DateTime, Text
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)
TAIPEI = ZoneInfo("Asia/Taipei")
FIRE_URL = "https://api.anthropic.com/v1/claude_code/routines/{routine}/fire"
IB_STALE_AFTER = timedelta(minutes=15)  # the gateway is polled every 4 minutes while the session is alive


@dataclass(frozen=True)
class RoutineRun:
    key: str
    routine_id: str
    token_env: str
    markets: tuple[str, ...]  # overseas markets whose bars must be collected after the close
    weekdays: tuple[int, ...]  # Taipei weekdays (Mon=0) that follow a trading session
    ready: time  # Taipei time the session is closed; overseas bars must be collected after it
    fire_after: time  # Taipei time the day's local data is in, so the run may start


RUNS = (
    # Taiwan, Tokyo and Seoul all close by 14:30 Taipei. Margin balances and securities lending publish around
    # 20:45 (measured 2026-10-19) and are collected at 21:00, so the run waits until 21:10.
    RoutineRun("taiwan", "trig_01ECP68tWfgM749sJa3gBiN9", "MARKET_ROUTINE_TAIWAN_TOKEN", ("JP", "KR"), (0, 1, 2, 3, 4), time(14, 30), time(21, 10)),
    # New York closes 04:00 (EDT) / 05:00 (EST) Taipei, Tuesday to Saturday.
    RoutineRun("us", "trig_01NETQT5DCSHj4TKwv45nbJR", "MARKET_ROUTINE_US_TOKEN", ("US",), (1, 2, 3, 4, 5), time(5, 30), time(5, 30)),
)


def session_date(run: RoutineRun, now: datetime) -> date | None:
    """The Taipei date of the session this run covers, or None when no closed session is waiting."""
    local = now.astimezone(TAIPEI)
    if local.weekday() in run.weekdays and local.time() >= run.fire_after:
        return local.date()
    return None


def ib_authenticated(last_portfolio_at: datetime | None, now: datetime) -> bool:
    return last_portfolio_at is not None and now - last_portfolio_at <= IB_STALE_AFTER


def due_runs(now: datetime, fired: dict[str, date], collected_at: dict[str, datetime | None]) -> list[RoutineRun]:
    """Runs whose session closed, whose overseas bars were collected after that close, and that have not fired yet.

    collected_at maps a market to the oldest latest-successful bar collection among its holdings (None when a holding
    was never collected). A market without holdings is simply absent and does not block the run.
    """
    due = []
    for run in RUNS:
        day = session_date(run, now)
        if day is None or fired.get(run.key) == day:
            continue
        closed_at = datetime.combine(day, run.ready, TAIPEI)
        if all(collected_at[m] is not None and collected_at[m] >= closed_at for m in run.markets if m in collected_at):
            due.append(run)
    return due


Base = declarative_base()


class AutomationFire(Base):
    __tablename__ = "maya_sawa_market_routine_fire"
    run = Column(Text, primary_key=True)
    session_date = Column(Date, primary_key=True)
    fired_at = Column(DateTime(timezone=True), nullable=False)
    session_url = Column(Text, nullable=False, default="")


class AutomationStore:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def last_fired(self) -> dict[str, date]:
        if not self.sessions:
            return {}
        with self.sessions() as session:
            rows = session.query(AutomationFire).all()
        latest: dict[str, date] = {}
        for row in rows:
            latest[row.run] = max(latest.get(row.run, row.session_date), row.session_date)
        return latest

    def record(self, run: str, day: date, session_url: str) -> bool:
        """Claim a run for a session date; False when another pod or check already did."""
        if not self.sessions:
            return False
        with self.sessions.begin() as session:
            if session.get(AutomationFire, (run, day)) is not None:
                return False
            session.add(AutomationFire(run=run, session_date=day, fired_at=datetime.now(timezone.utc), session_url=session_url))
        return True

    def release(self, run: str, day: date) -> None:
        """Drop a claim whose fire failed, so the next check retries."""
        if not self.sessions:
            return
        with self.sessions.begin() as session:
            row = session.get(AutomationFire, (run, day))
            if row is not None:
                session.delete(row)


_store: AutomationStore | None = None


def automation_store() -> AutomationStore:
    global _store
    if _store is None:
        from ..databases.market_dashboard_db import market_dashboard_db
        _store = AutomationStore(market_dashboard_db.engine)
    return _store


class IbkrSource:
    """What the checks need from the persisted IBKR data (never the live gateway)."""

    def __init__(self, db=None):
        self._db = db

    @property
    def db(self):
        if self._db is None:
            from ..databases.ibkr_research_db import get_ibkr_research_db
            self._db = get_ibkr_research_db()
        return self._db

    def last_portfolio_at(self) -> datetime | None:
        row = self.db.latest("ACCOUNT", "PRIVATE", "portfolio")
        return datetime.fromisoformat(row["fetchedAt"]) if row else None

    def overseas_positions(self) -> list[tuple[str, str]]:
        from .ibkr_research import MARKETS
        row = self.db.latest("ACCOUNT", "PRIVATE", "portfolio")
        positions = (row or {}).get("payload", {}).get("positions", [])
        return [(p["code"], MARKETS.get(p.get("currency"), "UNKNOWN")) for p in positions
                if p.get("assetClass") == "STK" and MARKETS.get(p.get("currency")) not in (None, "UNKNOWN", "TW")]

    def bars_collected_at(self, code: str, market: str) -> datetime | None:
        row = self.db.latest(code, market, "history_raw")
        return datetime.fromisoformat(row["fetchedAt"]) if row else None


async def check(store: AutomationStore, source, now: datetime | None = None) -> dict:
    """Report the IBKR session and each routine's state for today, firing the ones that are due."""
    now = now or datetime.now(timezone.utc)
    last_seen = source.last_portfolio_at()
    authenticated = ib_authenticated(last_seen, now)
    collected: dict[str, datetime | None] = {}
    for code, market in source.overseas_positions():  # a market is as fresh as its stalest holding
        at = source.bars_collected_at(code, market)
        if market not in collected:
            collected[market] = at
        elif collected[market] is not None:
            collected[market] = None if at is None else min(at, collected[market])
    fired = store.last_fired()
    due = {run.key for run in due_runs(now, fired, collected)}
    runs = []
    for run in RUNS:
        day = session_date(run, now)
        entry = {"key": run.key, "sessionDate": day.isoformat() if day else None}
        if day is None:
            entry["state"] = "no-session"
        elif fired.get(run.key) == day:
            entry["state"] = "done"
        elif run.key not in due:
            entry["state"] = "waiting-ib"
        elif not os.environ.get(run.token_env, "").strip():
            entry["state"] = "not-configured"
        elif not store.record(run.key, day, ""):
            entry["state"] = "done"
        else:
            try:
                entry["sessionUrl"] = await fire_routine(run, f"自動觸發：{', '.join(run.markets)} 收盤後的 IB 資料已收集（{now.astimezone(TAIPEI):%Y-%m-%d %H:%M} 台北）。")
                entry["state"] = "fired"
            except Exception as exc:  # token missing, routine API down: retry on the next check
                store.release(run.key, day)
                logger.warning("Routine %s not fired: %s", run.key, type(exc).__name__)
                entry["state"] = "error"
        runs.append(entry)
    return {"ib": {"authenticated": authenticated, "lastSeenAt": last_seen.isoformat() if last_seen else None,
                   "loginUrl": os.environ.get("IBKR_LOGIN_URL", "")},
            "runs": runs}


async def fire_routine(run: RoutineRun, text: str) -> str:
    token = os.environ.get(run.token_env, "").strip()
    if not token:
        raise RuntimeError(f"{run.token_env} is not configured")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(FIRE_URL.format(routine=run.routine_id), json={"text": text}, headers={
            "Authorization": f"Bearer {token}", "anthropic-beta": "experimental-cc-routine-2026-04-01",
            "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
    response.raise_for_status()
    return str(response.json().get("claude_code_session_url", ""))
