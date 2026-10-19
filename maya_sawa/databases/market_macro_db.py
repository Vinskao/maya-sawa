"""Persistent macroeconomic observations, event calendar, revisions and fetch budget."""
from __future__ import annotations

import json
import logging
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, Column, Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, create_engine, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config.config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()


class MacroSeries(Base):
    __tablename__ = "maya_sawa_macro_series"
    code = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    unit = Column(Text, nullable=False)
    frequency = Column(Text, nullable=False)
    source = Column(Text, nullable=False)


class MacroObservation(Base):
    __tablename__ = "maya_sawa_macro_observations"
    __table_args__ = (UniqueConstraint("series_code", "reference_period", name="uq_macro_observation_period"),)
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    series_code = Column(Text, ForeignKey("maya_sawa_macro_series.code"), nullable=False, index=True)
    reference_period = Column(Text, nullable=False)
    value = Column(Text, nullable=False)
    preliminary = Column(Integer, nullable=False, default=0)
    source_published_at = Column(DateTime(timezone=True))
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(Text, nullable=False)


class MacroObservationRevision(Base):
    __tablename__ = "maya_sawa_macro_observation_revisions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    series_code = Column(Text, nullable=False, index=True)
    reference_period = Column(Text, nullable=False)
    old_value = Column(Text)
    new_value = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False)
    source = Column(Text, nullable=False)


class MacroEvent(Base):
    __tablename__ = "maya_sawa_macro_events"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_macro_event_source_id"),)
    id = Column(Text, primary_key=True)
    source_id = Column(Text, nullable=False)
    group_id = Column(Text, nullable=False, index=True)
    event_type = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    reference_period = Column(Text)
    scheduled_date = Column(Date, nullable=False, index=True)
    scheduled_at = Column(DateTime(timezone=True))
    time_precision = Column(Text, nullable=False, default="date")
    schedule_verification = Column(Text, nullable=False, default="expected")
    published_at = Column(DateTime(timezone=True))
    consensus_value = Column(Text)
    actual_value = Column(Text)
    surprise_value = Column(Text)
    expectation_source = Column(Text)
    status = Column(Text, nullable=False, default="scheduled")
    source = Column(Text, nullable=False)
    source_url = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MacroEventRevision(Base):
    __tablename__ = "maya_sawa_macro_event_revisions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_id = Column(Text, nullable=False, index=True)
    changed_at = Column(DateTime(timezone=True), nullable=False)
    old_payload = Column(Text, nullable=False)
    new_payload = Column(Text, nullable=False)


class MacroFetchRun(Base):
    __tablename__ = "maya_sawa_macro_fetch_runs"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    finished_at = Column(DateTime(timezone=True))
    status = Column(Text, nullable=False)
    http_status = Column(Integer)
    record_count = Column(Integer, nullable=False, default=0)
    detail = Column(Text, nullable=False, default="")


class MarketMacroDatabase:
    def __init__(self) -> None:
        self.engine = create_engine(Config.DB_CONNECTION_STRING, pool_size=1, max_overflow=2) if Config.DB_CONNECTION_STRING else None
        self.sessions = sessionmaker(bind=self.engine) if self.engine else None
        if self.engine:
            try:
                Base.metadata.create_all(self.engine)
                # SQLAlchemy create_all does not add columns to an existing table.
                with self.engine.begin() as connection:
                    connection.execute(text("ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS consensus_value text"))
                    connection.execute(text("ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS actual_value text"))
                    connection.execute(text("ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS surprise_value text"))
                    connection.execute(text("ALTER TABLE maya_sawa_macro_events ADD COLUMN IF NOT EXISTS expectation_source text"))
            except Exception:
                logger.exception("Market macro schema initialization failed")

    def is_ready(self) -> bool:
        return bool(self.sessions)

    def acquire_refresh_lock(self):
        if not self.engine:
            return None
        connection = self.engine.connect()
        try:
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(812750318)")).scalar()
            if acquired:
                return connection
            connection.close()
            return None
        except Exception:
            connection.close()
            raise

    def release_refresh_lock(self, connection) -> None:
        if connection is None:
            return
        try:
            connection.execute(text("SELECT pg_advisory_unlock(812750318)"))
        finally:
            connection.close()

    def acquire_refresh_lock(self):
        if not self.engine:
            return None
        connection = self.engine.connect()
        try:
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(812750318)")).scalar()
            if acquired:
                return connection
            connection.close()
            return None
        except Exception:
            connection.close()
            raise

    def release_refresh_lock(self, connection) -> None:
        if connection is None:
            return
        try:
            connection.execute(text("SELECT pg_advisory_unlock(812750318)"))
        finally:
            connection.close()

    def reserve_source_call(self, source: str, daily_limit: int, minute_limit: int = 10) -> int | None:
        """Cross-worker provider budget. Reserved attempts count even when the upstream fails."""
        if not self.sessions:
            return None
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.execute(text("SELECT pg_advisory_xact_lock(812750319)"))
            day_count = session.query(MacroFetchRun).filter(MacroFetchRun.source.like(f"{source}%"),
                MacroFetchRun.started_at >= now - timedelta(hours=24), MacroFetchRun.status.in_(["reserved", "success", "error"])).count()
            minute_count = session.query(MacroFetchRun).filter(MacroFetchRun.source.like(f"{source}%"),
                MacroFetchRun.started_at >= now - timedelta(minutes=1), MacroFetchRun.status.in_(["reserved", "success", "error"])).count()
            if day_count >= daily_limit or minute_count >= minute_limit:
                return None
            run = MacroFetchRun(source=source, started_at=now, status="reserved", record_count=0, detail="")
            session.add(run); session.flush()
            return run.id

    def finish_source_call(self, run_id: int, status: str, count: int = 0, detail: str = "", http_status: int | None = None) -> None:
        if not self.sessions:
            return
        with self.sessions.begin() as session:
            run = session.get(MacroFetchRun, run_id)
            if run:
                run.finished_at, run.status, run.record_count = datetime.now(timezone.utc), status, count
                run.detail, run.http_status = detail[:80], http_status

    def cleanup_fetch_runs(self, retention_days: int = 90) -> int:
        """Expire diagnostic run rows only; never delete observations or calendar history."""
        if not self.sessions:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        with self.sessions.begin() as session:
            return session.query(MacroFetchRun).filter(MacroFetchRun.started_at < cutoff).delete(synchronize_session=False)

    def save_observations(self, source: str, rows: list[dict]) -> int:
        if not self.sessions or not rows:
            return 0
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            for row in rows:
                code, period, value = row["code"], row["period"], str(row["value"])
                old = session.query(MacroObservation).filter_by(series_code=code, reference_period=period).one_or_none()
                if old and old.value != value:
                    session.add(MacroObservationRevision(series_code=code, reference_period=period,
                        old_value=old.value, new_value=value, changed_at=now, source=source))
                if old:
                    old.value, old.preliminary, old.source_published_at, old.fetched_at, old.source = value, int(row.get("preliminary", False)), row.get("publishedAt"), now, source
                else:
                    session.add(MacroObservation(series_code=code, reference_period=period, value=value,
                        preliminary=int(row.get("preliminary", False)), source_published_at=row.get("publishedAt"),
                        fetched_at=now, source=source))
        return len(rows)

    def latest_period(self, code: str) -> str | None:
        if not self.sessions:
            return None
        with self.sessions() as session:
            row = session.query(MacroObservation.reference_period).filter_by(series_code=code).order_by(MacroObservation.reference_period.desc()).first()
            return row[0] if row else None

    def record_observed_release(self, group_id: str, reference_period: str, source_url: str) -> None:
        """Record the first observation of a new release period; initial history is never flagged as new."""
        if not self.sessions:
            return
        now = datetime.now(timezone.utc)
        event_day = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        with self.sessions.begin() as session:
            event = session.query(MacroEvent).filter(MacroEvent.group_id == group_id,
                MacroEvent.status == "scheduled", MacroEvent.scheduled_date >= event_day - timedelta(days=2),
                MacroEvent.scheduled_date <= event_day + timedelta(days=1)).order_by(MacroEvent.scheduled_date).first()
            if event:
                old_payload = json.dumps({"status": event.status, "published_at": event.published_at.isoformat() if event.published_at else None,
                    "reference_period": event.reference_period}, sort_keys=True)
                new_payload = json.dumps({"status": "published", "published_at": now.isoformat(), "reference_period": reference_period}, sort_keys=True)
                session.add(MacroEventRevision(event_id=event.id, changed_at=now, old_payload=old_payload, new_payload=new_payload))
                event.status, event.published_at, event.reference_period = "published", now, reference_period
                return
            source_id = f"{group_id}:{reference_period}"
            event_id = f"observed:{source_id}"
            if session.get(MacroEvent, event_id):
                return
            session.add(MacroEvent(id=event_id, source_id=source_id, group_id=group_id,
                event_type=group_id, title="Employment Situation" if group_id == "employment" else "Consumer Price Index",
                reference_period=reference_period, scheduled_date=event_day, scheduled_at=None, time_precision="date",
                schedule_verification="detected", published_at=now, status="published", source="BLS",
                source_url=source_url, updated_at=now))

    def save_events(self, source: str, events: list[dict]) -> int:
        if not self.sessions or not events:
            return 0
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            for item in events:
                values = {"id": item["id"], "source_id": item["sourceId"], "group_id": item["groupId"],
                    "event_type": item["type"], "title": item["title"], "reference_period": item.get("referencePeriod"),
                    "scheduled_date": item["scheduledDate"], "scheduled_at": item.get("scheduledAt"),
                    "time_precision": item.get("timePrecision", "date"), "schedule_verification": item.get("scheduleVerification", "expected"),
                    "published_at": item.get("publishedAt"), "status": item.get("status", "scheduled"), "source": source,
                    "consensus_value": item.get("consensusValue"), "actual_value": item.get("actualValue"),
                    "surprise_value": item.get("surpriseValue"), "expectation_source": item.get("expectationSource"),
                    "source_url": item["sourceUrl"], "updated_at": now}
                if values["surprise_value"] is None and values["consensus_value"] is not None and values["actual_value"] is not None:
                    delta = _expectation_delta(values["actual_value"], values["consensus_value"])
                    values["surprise_value"] = str(delta) if delta is not None else None
                old = session.get(MacroEvent, item["id"])
                if old and old.status == "published" and values["scheduled_date"] == old.scheduled_date:
                    # Re-fetching the source calendar must not erase a locally detected publication.
                    values["status"] = "published"
                    values["published_at"] = old.published_at
                    values["reference_period"] = values["reference_period"] or old.reference_period
                if old:
                    # Schedule-only refreshes must not erase a previously collected consensus/result.
                    for field in ("consensus_value", "actual_value", "surprise_value", "expectation_source"):
                        values[field] = values[field] or getattr(old, field)
                revision_values = {key: value for key, value in values.items() if key != "updated_at"}
                payload = json.dumps(revision_values, default=lambda v: v.isoformat() if hasattr(v, "isoformat") else v, sort_keys=True)
                if old:
                    old_payload = json.dumps({k: getattr(old, k) for k in values if k != "updated_at"}, default=lambda v: v.isoformat() if hasattr(v, "isoformat") else v, sort_keys=True)
                    if old_payload != payload:
                        session.add(MacroEventRevision(event_id=old.id, changed_at=now, old_payload=old_payload, new_payload=payload))
                    for key, value in values.items():
                        setattr(old, key, value)
                else:
                    session.add(MacroEvent(**values))
        return len(events)

    def update_event_expectations(self, items: list[dict]) -> int:
        """Merge third-party consensus/actual values into existing canonical release events."""
        if not self.sessions or not items:
            return 0
        now = datetime.now(timezone.utc)
        updated = 0
        with self.sessions.begin() as session:
            for item in items:
                row = session.query(MacroEvent).filter_by(group_id=item["groupId"], scheduled_date=item["scheduledDate"]).first()
                if not row:
                    row = MacroEvent(id=item["id"], source_id=item["sourceId"], group_id=item["groupId"],
                        event_type=item["type"], title=item["title"], reference_period=item.get("referencePeriod"),
                        scheduled_date=item["scheduledDate"], scheduled_at=item.get("scheduledAt"),
                        time_precision=item.get("timePrecision", "date"),
                        schedule_verification=item.get("scheduleVerification", "expected"),
                        published_at=now if item.get("actualValue") is not None else None,
                        status="published" if item.get("actualValue") is not None else "scheduled",
                        source="FinanceCalendar", source_url=item["sourceUrl"], updated_at=now)
                    session.add(row)
                    session.flush()
                old_payload = json.dumps({"consensus": row.consensus_value, "actual": row.actual_value,
                    "surprise": row.surprise_value, "source": row.expectation_source}, sort_keys=True)
                consensus = item.get("consensusValue") or row.consensus_value
                actual = item.get("actualValue") or row.actual_value
                surprise = item.get("surpriseValue")
                if surprise is None and consensus is not None and actual is not None:
                    delta = _expectation_delta(actual, consensus)
                    surprise = str(delta) if delta is not None else row.surprise_value
                new_payload = json.dumps({"consensus": consensus, "actual": actual, "surprise": surprise,
                    "source": item.get("expectationSource") or row.expectation_source}, sort_keys=True)
                if old_payload == new_payload:
                    continue
                session.add(MacroEventRevision(event_id=row.id, changed_at=now, old_payload=old_payload, new_payload=new_payload))
                row.consensus_value, row.actual_value, row.surprise_value = consensus, actual, surprise
                row.expectation_source = item.get("expectationSource") or row.expectation_source
                if item.get("actualValue") is not None:
                    row.status, row.published_at = "published", row.published_at or now
                row.updated_at = now
                updated += 1
        return updated

    def snapshot(self, history_months: int = 24) -> dict:
        if not self.sessions:
            return {"status": "unavailable", "indicators": [], "events": [], "sources": []}
        now = datetime.now(timezone.utc)
        start_period = (now.year * 12 + now.month - history_months - 2)
        start_year, start_month = divmod(start_period, 12)
        with self.sessions() as session:
            observations = session.query(MacroObservation).filter(MacroObservation.reference_period >= f"{start_year:04d}-{start_month + 1:02d}").order_by(MacroObservation.series_code, MacroObservation.reference_period).all()
            event_rows = session.query(MacroEvent).filter(
                MacroEvent.scheduled_date >= (now - timedelta(days=7)).date(),
                MacroEvent.scheduled_date <= (now + timedelta(days=90)).date()).order_by(MacroEvent.scheduled_date).all()
            cpi_history_rows = session.query(MacroEvent).filter(
                MacroEvent.group_id == "cpi",
                MacroEvent.scheduled_date >= (now - timedelta(days=730)).date(),
                MacroEvent.scheduled_date <= (now + timedelta(days=90)).date()).order_by(MacroEvent.scheduled_date).all()
            runs = session.query(MacroFetchRun).order_by(MacroFetchRun.started_at.desc()).all()
            series = {row.code: row for row in session.query(MacroSeries).all()}
        by_code: dict[str, list] = {}
        for row in observations:
            by_code.setdefault(row.series_code, []).append(row)
        indicators = []
        for code, rows in by_code.items():
            meta = series.get(code)
            # Daily and weekly series need higher point limits than monthly series.
            row_limit = max(history_months, 24) * (32 if meta and meta.frequency == "daily" else 5 if meta and meta.frequency == "weekly" else 1)
            rows = rows[-row_limit:]
            latest = rows[-1]
            previous = rows[-2] if len(rows) > 1 else None
            indicator = {"code": code, "name": meta.name if meta else code, "unit": meta.unit if meta else "",
                "frequency": meta.frequency if meta else "monthly", "value": latest.value, "referencePeriod": latest.reference_period,
                "previousValue": previous.value if previous else None, "previousPeriod": previous.reference_period if previous else None,
                "change": float(latest.value) - float(previous.value) if previous else None,
                "preliminary": bool(latest.preliminary), "source": latest.source, "fetchedAt": latest.fetched_at.isoformat(),
                "sourcePublishedAt": latest.source_published_at.isoformat() if latest.source_published_at else None,
                "history": [{"period": row.reference_period, "value": row.value} for row in rows]}
            if code == "ICSA":
                indicator["source"] = "U.S. Department of Labor ETA (via FRED)"
                indicator["sourceUrl"] = "https://oui.doleta.gov/unemploy/claims.asp/wkclaims/report.asp"
            elif code == "WPUFD4":
                indicator["sourceUrl"] = "https://www.bls.gov/ppi/data-retrieval-guide/home.htm"
            elif code == "RSAFS":
                indicator["sourceUrl"] = "https://api.census.gov/data/timeseries/eits/mrts.html"
            if code == "CUUR0000SA0":
                forecasts = []
                for event in cpi_history_rows:
                    raw = event.consensus_value or ""
                    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*%?\s*(?:yoy|y/y|year[- ]over[- ]year)", raw, re.I)
                    if not match:
                        continue
                    period_date = event.scheduled_date.replace(day=1) - timedelta(days=1)
                    forecasts.append({"period": period_date.strftime("%Y-%m"), "value": match.group(1),
                        "source": event.expectation_source or "Economic Calendar", "sourceUrl": event.source_url})
                indicator["consensusHistory"] = forecasts
            indicators.append(indicator)
        latest_observed = {group: by_code[code][-1].reference_period
            for group, code in RELEASE_SERIES.items() if by_code.get(code)}
        events = []
        for row in event_rows:
            events.append({"id": row.id, "groupId": row.group_id, "type": row.event_type, "title": row.title,
                "referencePeriod": row.reference_period, "scheduledDate": row.scheduled_date.isoformat(),
                "scheduledAt": row.scheduled_at.isoformat() if row.scheduled_at else None,
                "timePrecision": row.time_precision, "scheduleVerification": row.schedule_verification,
                "publishedAt": row.published_at.isoformat() if row.published_at else None, "status": row.status,
                "consensusValue": row.consensus_value, "actualValue": row.actual_value,
                "surpriseValue": row.surprise_value,
                "surpriseStatus": _surprise_status(row.consensus_value, row.actual_value),
                "expectationSource": row.expectation_source,
                "highlightLevel": _highlight(row, now, latest_observed.get(row.group_id)), "source": row.source, "sourceUrl": row.source_url})
        latest_runs: dict[str, dict[str, MacroFetchRun]] = {}
        for run in runs:
            state = latest_runs.setdefault(run.source, {})
            state.setdefault("latest", run)
            if run.status == "success": state.setdefault("success", run)
        source_status = []
        for name, state in latest_runs.items():
            latest, success = state["latest"], state.get("success")
            last_success = success.finished_at if success else None
            source_status.append({"source": name, "availability": latest.status,
                "lastSuccessAt": last_success.isoformat() if last_success else None,
                "stale": not last_success or (now - last_success).total_seconds() > 36 * 3600,
                "errorCode": latest.detail if latest.status != "success" else None})
        return {"status": "ready" if indicators or events else "no_data", "asOf": now.isoformat(),
            "displayTimezone": "Asia/Taipei", "indicators": indicators, "events": events, "sources": source_status,
            "nextRefreshAt": (now + timedelta(minutes=5)).isoformat()}


# Series whose stored observations prove a release group has published.
RELEASE_SERIES = {"employment": "CES0000000001", "claims": "ICSA", "cpi": "CUSR0000SA0", "ppi": "WPUFD4", "retail_sales": "RSAFS", "fed": "DFEDTARU"}


def _release_observed(event: MacroEvent, observed_period: str | None) -> bool:
    """A past-due release counts as published once its data is stored, even if the data
    arrived with the initial history load and no new-period transition was ever seen."""
    if not observed_period:
        return False
    if len(observed_period) == 7:
        # Monthly releases report the previous month: the 10-14 CPI release carries 2026-09.
        first_of_month = event.scheduled_date.replace(day=1)
        expected = (first_of_month - timedelta(days=1)).strftime("%Y-%m")
        return observed_period >= expected
    if event.group_id == "claims":
        # Thursday's claims report covers the week ending the previous Saturday (5 days earlier);
        # the prior report's week ends 12 days earlier, so 6 days separates the two.
        return observed_period >= (event.scheduled_date - timedelta(days=6)).isoformat()
    # Daily series (Fed target) are posted for the day after the decision.
    return observed_period > event.scheduled_date.isoformat()


def _highlight(event: MacroEvent, now: datetime, observed_period: str | None = None) -> str:
    if event.status == "published":
        if event.published_at and (now - event.published_at).total_seconds() <= 24 * 3600:
            return "published"
        return "none"
    if not event.scheduled_at:
        days = (event.scheduled_date - now.astimezone(ZoneInfo("Asia/Taipei")).date()).days
        if days < 0: return "none" if _release_observed(event, observed_period) else "waiting"
        if days <= 7: return "upcoming"
        return "none"
    delta = (event.scheduled_at - now).total_seconds()
    if delta < 0:
        if _release_observed(event, observed_period):
            return "published" if delta >= -24 * 3600 else "none"
        return "waiting"
    if delta <= 24 * 3600: return "urgent"
    if delta <= 72 * 3600: return "soon"
    if delta <= 7 * 86400: return "upcoming"
    return "none"


def _surprise_status(consensus: str | None, actual: str | None) -> str | None:
    """Compare like-for-like numeric values; missing or non-numeric data stays unclassified."""
    if consensus is None or actual is None:
        return None
    expected_number, actual_number = _numeric_expectation(consensus), _numeric_expectation(actual)
    if expected_number is None or actual_number is None:
        return None
    if actual_number > expected_number:
        return "above"
    if actual_number < expected_number:
        return "below"
    return "in_line"


def _numeric_expectation(value: str | None) -> Decimal | None:
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?\s*([KMB])?\s*%?", cleaned, re.I)
    if not match:
        return None
    number = match.group(0).upper().replace("%", "").replace("K", "").replace("M", "").replace("B", "").strip()
    try:
        parsed = Decimal(number)
        suffix = (match.group(1) or "").upper()
        return parsed * {"": 1, "K": 1000, "M": 1000000, "B": 1000000000}[suffix]
    except (InvalidOperation, KeyError):
        return None


def _expectation_delta(actual: str | None, consensus: str | None) -> Decimal | None:
    actual_number, expected_number = _numeric_expectation(actual), _numeric_expectation(consensus)
    return actual_number - expected_number if actual_number is not None and expected_number is not None else None


market_macro_db = MarketMacroDatabase()
