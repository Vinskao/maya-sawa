"""Isolated GPT extraction proposals; only the keyed review routine can apply them."""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Text, UniqueConstraint, update
from sqlalchemy.orm import declarative_base, sessionmaker

from maya_sawa.benchmark_evidence import UPLOADER, validate_evidence

Base = declarative_base()


class InvalidClaimProposal(ValueError):
    pass


class ReportClaimProposal(Base):
    __tablename__ = "maya_sawa_market_report_claim_proposal"
    id = Column(Text, primary_key=True)
    report_id = Column(Text, nullable=False, index=True)
    digest = Column(Text, nullable=False)
    claims = Column(Text, nullable=False)
    status = Column(Text, nullable=False)  # pending | applying | applied | rejected | failed
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    reviewed_at = Column(DateTime(timezone=True))
    review = Column(Text)
    __table_args__ = (UniqueConstraint("report_id", "digest"),)


def _public_pending_source(report):
    if not report or report.visibility != "public" or report.status not in {"claims_pending", "failed"}:
        raise LookupError("Public pending report not found")
    if report.status == "failed" and (report.page_count <= 0 or not report.text):
        raise LookupError("Public pending report not found")
    source = {"id": report.id, "title": report.title, "publisher": report.publisher,
            "published_at": report.published_at.isoformat() if report.published_at else None,
            "page_count": report.page_count, "text": report.text}
    if report.uploaded_by == UPLOADER:
        source["analysis_profile"] = "tw-semiconductor-annual"
    return source


def _validate_proposal(claims, page_count):
    from ..services.market_reports import validate_claims

    if not isinstance(claims, list) or len(claims) > 300:
        raise InvalidClaimProposal("claims must be a list of at most 300 items")
    for claim in claims:
        if not isinstance(claim, dict):
            raise InvalidClaimProposal("each claim must be an object")
        for field in ("claim", "evidence"):
            value = claim.get(field)
            if isinstance(value, str) and len(value) > 600:
                raise InvalidClaimProposal(f"{field} must be at most 600 characters")
            # Model-written instructions, URLs and markup are not useful claim evidence.
            if isinstance(value, str) and ("ignore previous instructions" in value.lower()
                    or "忽略之前的指令" in value or "<script" in value.lower()):
                raise InvalidClaimProposal(f"{field} contains instruction-like or active markup text")
    try:
        return validate_claims(claims, page_count)
    except ValueError as exc:
        raise InvalidClaimProposal(str(exc)) from exc


class ClaimInboxDatabase:
    WEEKLY_LIMIT = 100

    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine, tables=[ReportClaimProposal.__table__])

    def _require(self):
        if not self.sessions:
            raise RuntimeError("Report claim inbox database unavailable")

    @staticmethod
    def _row(row):
        return {"id": row.id, "reportId": row.report_id, "claims": json.loads(row.claims),
                "status": row.status, "submittedAt": row.submitted_at.isoformat(),
                "reviewedAt": row.reviewed_at.isoformat() if row.reviewed_at else None,
                "review": json.loads(row.review) if row.review else None}

    def source_report(self, report_id, reports_db):
        self._require()
        from .market_reports_db import MarketReport

        with reports_db.sessions() as session:
            return _public_pending_source(session.get(MarketReport, report_id))

    def has_proposal(self, report_id):
        self._require()
        with self.sessions() as session:
            return session.query(ReportClaimProposal.id).filter_by(report_id=report_id).first() is not None

    def submit(self, report_id, claims, reports_db, now=None):
        self._require()
        from .market_reports_db import MarketReport

        with reports_db.sessions() as session:
            source = _public_pending_source(session.get(MarketReport, report_id))
        normalized = _validate_proposal(claims, source["page_count"])
        if source.get("analysis_profile") == "tw-semiconductor-annual":
            pages = re.split(r"(?m)^=====PAGE \d+=====\n", source["text"])[1:]
            try:
                validate_evidence(normalized, pages)
            except ValueError as exc:
                raise InvalidClaimProposal(str(exc)) from exc
        serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        digest = hashlib.sha256(serialized.encode()).hexdigest()
        now = now or datetime.now(timezone.utc)
        week = now.strftime("%G-%V")
        with self.sessions.begin() as session:
            duplicate = session.query(ReportClaimProposal).filter_by(report_id=report_id, digest=digest).first()
            if duplicate:
                return self._row(duplicate), False
            start = datetime.strptime(week + "-1", "%G-%V-%u").replace(tzinfo=timezone.utc)
            end = datetime.strptime(week + "-7", "%G-%V-%u").replace(tzinfo=timezone.utc)
            if session.query(ReportClaimProposal).filter(
                ReportClaimProposal.submitted_at >= start, ReportClaimProposal.submitted_at < end
            ).count() >= self.WEEKLY_LIMIT:
                raise OverflowError("Weekly report proposal limit reached")
            row = ReportClaimProposal(id=str(uuid.uuid4()), report_id=report_id, digest=digest,
                claims=serialized, status="pending", submitted_at=now)
            session.add(row)
            session.flush()
            return self._row(row), True

    def list(self, status="pending", limit=50):
        self._require()
        with self.sessions() as session:
            query = session.query(ReportClaimProposal)
            if status:
                query = query.filter_by(status=status)
            return [self._row(row) for row in query.order_by(ReportClaimProposal.submitted_at).limit(min(max(limit, 1), 100)).all()]

    def get(self, proposal_id):
        self._require()
        with self.sessions() as session:
            row = session.get(ReportClaimProposal, proposal_id)
            return self._row(row) if row else None

    def claim(self, proposal_id):
        self._require()
        with self.sessions.begin() as session:
            changed = session.execute(update(ReportClaimProposal).where(
                ReportClaimProposal.id == proposal_id, ReportClaimProposal.status == "pending"
            ).values(status="applying")).rowcount
            row = session.get(ReportClaimProposal, proposal_id)
            return self._row(row) if changed == 1 else None

    def finish(self, proposal_id, status, review):
        self._require()
        with self.sessions.begin() as session:
            changed = session.execute(update(ReportClaimProposal).where(
                ReportClaimProposal.id == proposal_id, ReportClaimProposal.status == "applying"
            ).values(status=status, reviewed_at=datetime.now(timezone.utc),
                     review=json.dumps(review, ensure_ascii=False))).rowcount
            if changed != 1:
                return None
            row = session.get(ReportClaimProposal, proposal_id)
            session.flush()
            return self._row(row)


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return ClaimInboxDatabase(market_dashboard_db.engine)


market_report_claims_inbox_db = _default_db()
