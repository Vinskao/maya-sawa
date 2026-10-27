"""PostgreSQL persistence for report PDFs, text chunks, embeddings, and extracted claims."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from .market_dashboard_db import market_dashboard_db

Base = declarative_base()

COLLECTOR_UPLOADER = "telegram-collector"  # reports made from public Telegram posts
COLLECTOR_LISTED_PER_CHANNEL = 10  # the report list shows only the latest posts of each channel; the rest stay data


class MarketReport(Base):
    __tablename__ = "maya_sawa_market_reports"
    id = Column(Text, primary_key=True, default=lambda: str(uuid4()))
    title = Column(Text, nullable=False)
    publisher = Column(Text, nullable=False, default="")
    published_at = Column(Date)
    received_at = Column(DateTime(timezone=True), nullable=False)
    uploaded_by = Column(Text, nullable=False, index=True)
    sha256 = Column(Text, nullable=False, unique=True, index=True)
    page_count = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="public")
    status = Column(Text, nullable=False, default="extracted")
    failure_reason = Column(Text)
    pdf = Column(LargeBinary, nullable=False)
    source_url = Column(Text)  # where a non-PDF source (a Telegram post) can be read, e.g. https://t.me/ieobserve/2312
    chunks = relationship(
        "MarketReportChunk", cascade="all, delete-orphan", passive_deletes=True
    )
    claims = relationship(
        "MarketReportClaim", cascade="all, delete-orphan", passive_deletes=True
    )


class MarketReportChunk(Base):
    __tablename__ = "maya_sawa_market_report_chunks"
    id = Column(Text, primary_key=True, default=lambda: str(uuid4()))
    report_id = Column(
        Text,
        ForeignKey("maya_sawa_market_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page = Column(Integer, nullable=False)
    seq = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(1536).with_variant(JSON(), "sqlite"), nullable=False)
    __table_args__ = (
        UniqueConstraint("report_id", "page", "seq"),
        Index(
            "ix_market_report_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class MarketReportClaim(Base):
    __tablename__ = "maya_sawa_market_report_claims"
    id = Column(Text, primary_key=True, default=lambda: str(uuid4()))
    report_id = Column(
        Text,
        ForeignKey("maya_sawa_market_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page = Column(Integer, nullable=False)
    segment = Column(Text, nullable=False)
    codes = Column(
        ARRAY(Text).with_variant(JSON(), "sqlite"), nullable=False, default=list
    )
    dimension = Column(Text, nullable=False)
    direction = Column(Text, nullable=False)
    claim = Column(Text, nullable=False)
    evidence = Column(Text, nullable=False)
    as_of = Column(Date)
    extracted_by = Column(Text)
    extracted_at = Column(DateTime(timezone=True))


class MarketReportsDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            # pgvector is preinstalled in production; create tables after enabling its SQLAlchemy type.
            Base.metadata.create_all(engine)
            if engine.dialect.name == "postgresql":  # create_all does not add columns to an existing table
                with engine.begin() as connection:
                    connection.execute(sql_text("ALTER TABLE maya_sawa_market_reports ADD COLUMN IF NOT EXISTS source_url text"))

    def ingest(
        self,
        *,
        title,
        publisher,
        published_at,
        visibility,
        uploaded_by,
        digest,
        pdf,
        pages,
        chunks,
        vectors,
    ):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        try:
            with self.sessions.begin() as session:
                existing = session.query(MarketReport).filter_by(sha256=digest).first()
                if existing:
                    return self.public_report(existing), True
                report = MarketReport(
                    title=title,
                    publisher=publisher,
                    published_at=published_at,
                    received_at=datetime.now(timezone.utc),
                    uploaded_by=uploaded_by,
                    sha256=digest,
                    page_count=len(pages),
                    text="\n\n".join(
                        f"=====PAGE {i}=====\n{text}" for i, text in enumerate(pages, 1)
                    ),
                    visibility=visibility,
                    status="embedded",
                    pdf=pdf,
                )
                session.add(report)
                session.flush()
                for chunk, vector in zip(chunks, vectors, strict=True):
                    session.add(
                        MarketReportChunk(
                            report_id=report.id,
                            page=chunk["page"],
                            seq=chunk["seq"],
                            text=chunk["text"],
                            embedding=vector,
                        )
                    )
                report.status = "claims_pending"
                session.flush()
                return self.public_report(report), False
        except IntegrityError:
            duplicate = self.find_by_digest(digest)
            if duplicate:
                return duplicate, True
            raise

    @staticmethod
    def _page_text(pages):
        return "\n\n".join(
            f"=====PAGE {i}=====\n{text}" for i, text in enumerate(pages, 1)
        )

    def save_extracted(
        self,
        *,
        title,
        publisher,
        published_at,
        visibility,
        uploaded_by,
        digest,
        pdf,
        pages,
        source_url=None,
        status="claims_pending",
    ):
        """Persist readable source text before optional vectorization can fail."""
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        try:
            with self.sessions.begin() as session:
                report = session.query(MarketReport).filter_by(sha256=digest).first()
                if report:
                    return {
                        **self.public_report(report),
                        "uploaded_by": report.uploaded_by,
                    }, True
                report = MarketReport(
                    title=title,
                    publisher=publisher,
                    published_at=published_at,
                    received_at=datetime.now(timezone.utc),
                    uploaded_by=uploaded_by,
                    sha256=digest,
                    page_count=len(pages),
                    text=self._page_text(pages),
                    visibility=visibility,
                    status=status,
                    pdf=pdf,
                    source_url=source_url,
                )
                session.add(report)
                session.flush()
                return self.public_report(report), False
        except IntegrityError:
            duplicate = self.find_by_digest(digest)
            if duplicate:
                return duplicate, True
            raise

    def add_chunks(self, report_id, chunks, vectors):
        """Store semantic chunks when vectors are available; claims do not depend on this."""
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            report = session.get(MarketReport, report_id)
            if not report:
                raise ValueError("Report not found")
            if len(chunks) != len(vectors):
                raise ValueError("Each semantic chunk must have one embedding")
            for chunk, vector in zip(chunks, vectors, strict=True):
                session.add(
                    MarketReportChunk(
                        report_id=report_id,
                        page=chunk["page"],
                        seq=chunk["seq"],
                        text=chunk["text"],
                        embedding=vector,
                    )
                )

    def find_by_digest(self, digest):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions() as session:
            report = session.query(MarketReport).filter_by(sha256=digest).first()
            if not report:
                return None
            return {**self.public_report(report), "uploaded_by": report.uploaded_by}

    def save_failed(
        self,
        *,
        title,
        publisher,
        published_at,
        visibility,
        uploaded_by,
        digest,
        pdf,
        reason,
        page_count=0,
        pages=None,
    ):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            report = session.query(MarketReport).filter_by(sha256=digest).first()
            if not report:
                report = MarketReport(
                    title=title,
                    publisher=publisher,
                    published_at=published_at,
                    received_at=datetime.now(timezone.utc),
                    uploaded_by=uploaded_by,
                    sha256=digest,
                    page_count=len(pages) if pages is not None else page_count,
                    text="\n\n".join(
                        f"=====PAGE {i}=====\n{text}"
                        for i, text in enumerate(pages or [], 1)
                    ),
                    visibility=visibility,
                    status="failed",
                    failure_reason=reason,
                    pdf=pdf,
                )
                session.add(report)
                session.flush()
            return {**self.public_report(report), "uploaded_by": report.uploaded_by}

    def fail_by_digest(self, digest, reason):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            report = session.query(MarketReport).filter_by(sha256=digest).first()
            if report:
                report.status = "failed"
                report.failure_reason = reason[:1000]

    def delete_owned(self, report_id, owner):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            report = session.get(MarketReport, report_id)
            if not report or report.uploaded_by != owner:
                return False
            session.delete(report)
            return True

    def delete_failed_owned(self, report_id, owner):
        """Remove an owned failed row so the same PDF can be ingested again."""
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            report = (
                session.query(MarketReport)
                .filter_by(id=report_id, uploaded_by=owner, status="failed")
                .first()
            )
            if not report:
                return False
            session.delete(report)
            return True

    def pending_claims(self):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions() as session:
            return [
                {
                    "id": row.id,
                    "title": row.title,
                    "publisher": row.publisher,
                    "published_at": (
                        row.published_at.isoformat() if row.published_at else None
                    ),
                    "page_count": row.page_count,
                    "text": row.text,
                }
                for row in session.query(MarketReport)
                .filter(
                    (MarketReport.status == "claims_pending")
                    | (
                        (MarketReport.status == "failed")
                        & (MarketReport.page_count > 0)
                        & (MarketReport.text != "")
                    )
                )
                .order_by(MarketReport.received_at)
                .all()
            ]

    def list_claims(self, code=None, segment=None, since=None):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions() as session:
            query = (
                session.query(MarketReportClaim, MarketReport)
                .join(MarketReport)
                .filter(
                    MarketReport.visibility == "public", MarketReport.status == "ready"
                )
            )
            if code:
                query = query.filter(MarketReportClaim.codes.contains([code]))
            if segment:
                query = query.filter(MarketReportClaim.segment == segment)
            if since:
                query = query.filter(MarketReportClaim.as_of >= since)
            return [
                {
                    "report_id": report.id,
                    "title": report.title,
                    "publisher": report.publisher,
                    "published_at": (
                        report.published_at.isoformat() if report.published_at else None
                    ),
                    "page": claim.page,
                    "segment": claim.segment,
                    "codes": claim.codes,
                    "dimension": claim.dimension,
                    "direction": claim.direction,
                    "claim": claim.claim,
                    "evidence": claim.evidence,
                    "as_of": claim.as_of.isoformat() if claim.as_of else None,
                    "received_at": report.received_at.isoformat(),
                    "source_url": report.source_url,
                }
                for claim, report in query.order_by(MarketReport.received_at.desc())
                .limit(500)
                .all()
            ]

    def search_chunks(
        self, vector, *, code=None, segment=None, limit=10, include_private=False
    ):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        distance = MarketReportChunk.embedding.cosine_distance(vector)
        with self.sessions() as session:
            query = (
                session.query(
                    MarketReportChunk, MarketReport, distance.label("distance")
                )
                .join(MarketReport)
                .filter(MarketReport.status == "ready")
            )
            if not include_private:
                query = query.filter(MarketReport.visibility == "public")
            if segment:
                query = query.filter(
                    MarketReport.claims.any(MarketReportClaim.segment == segment)
                )
            if code:
                query = query.filter(
                    MarketReport.claims.any(MarketReportClaim.codes.contains([code]))
                )
            return [
                {
                    "report_id": report.id,
                    "title": report.title,
                    "publisher": report.publisher,
                    "published_at": (
                        report.published_at.isoformat() if report.published_at else None
                    ),
                    "page": chunk.page,
                    "text": chunk.text,
                    "distance": float(dist),
                }
                for chunk, report, dist in query.order_by(distance).limit(limit).all()
            ]

    def page_count(self, report_id):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions() as session:
            row = session.get(MarketReport, report_id)
            if not row:
                raise ValueError("Report not found")
            return row.page_count

    def replace_claims(self, report_id, claims, extracted_by):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            report = session.get(MarketReport, report_id)
            if not report:
                return False
            report.claims.clear()
            extracted_at = datetime.now(timezone.utc)
            for claim in claims:
                report.claims.append(
                    MarketReportClaim(
                        page=claim["page"],
                        segment=claim["segment"],
                        codes=claim["codes"],
                        dimension=claim["dimension"],
                        direction=claim["direction"],
                        claim=claim["claim"],
                        evidence=claim["evidence"],
                        as_of=(
                            date.fromisoformat(claim["as_of"])
                            if claim.get("as_of")
                            else None
                        ),
                        extracted_by=extracted_by,
                        extracted_at=extracted_at,
                    )
                )
            report.status = "ready"
            report.failure_reason = None
            return True

    @staticmethod
    def public_report(report):
        return {
            "id": report.id,
            "title": report.title,
            "publisher": report.publisher,
            "published_at": (
                report.published_at.isoformat() if report.published_at else None
            ),
            "received_at": report.received_at.isoformat(),
            "source_url": report.source_url,
            "page_count": report.page_count,
            "visibility": report.visibility,
            "status": report.status,
            "failure_reason": report.failure_reason if report.status != "ready" else None,
            "text": report.text,
            "sha256": report.sha256,
            "claim_count": len(report.claims) if report.claims is not None else 0,
            "claims": [
                {
                    "page": c.page,
                    "segment": c.segment,
                    "codes": c.codes,
                    "dimension": c.dimension,
                    "direction": c.direction,
                    "claim": c.claim,
                    "evidence": c.evidence,
                }
                for c in report.claims
            ],
        }

    def list_reports(self, owner: str | None):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions() as session:
            query = session.query(MarketReport).filter(MarketReport.uploaded_by != COLLECTOR_UPLOADER)
            if owner:
                query = query.filter(
                    (MarketReport.visibility == "public")
                    | (MarketReport.uploaded_by == owner)
                )
            else:
                query = query.filter(MarketReport.visibility == "public")
            listed = [
                {**self.public_report(row), "uploaded_by": row.uploaded_by}
                for row in query.order_by(MarketReport.received_at.desc()).all()
            ]
            posts = (
                session.query(MarketReport)
                .filter(
                    MarketReport.uploaded_by == COLLECTOR_UPLOADER,
                    MarketReport.visibility == "public",
                    MarketReport.status != "failed",
                )
                .order_by(MarketReport.published_at.desc(), MarketReport.received_at.desc())
                .all()
            )
            taken: dict[str, int] = {}
            for row in posts:  # newest first, whatever their status or claim count, so a channel is never silently absent
                if taken.get(row.publisher, 0) >= COLLECTOR_LISTED_PER_CHANNEL:
                    continue
                taken[row.publisher] = taken.get(row.publisher, 0) + 1
                listed.append({**self.public_report(row), "uploaded_by": row.uploaded_by})
            return listed

    def get_report(self, report_id: str, *, include_pdf=False):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions() as session:
            report = session.get(MarketReport, report_id)
            return (
                (
                    self.public_report(report),
                    bytes(report.pdf) if include_pdf else None,
                    report.uploaded_by,
                )
                if report
                else None
            )

    def oldest_post_id(self, channel: str):
        """Smallest Telegram post id recorded for a channel, or None."""
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        prefix = f"https://t.me/{channel}/"
        with self.sessions() as session:
            urls = [row[0] for row in session.query(MarketReport.source_url).filter(MarketReport.source_url.like(f"{prefix}%")).all()]
        ids = [int(url[len(prefix):]) for url in urls if url[len(prefix):].isdigit()]
        return min(ids) if ids else None

    def promote_backlog(self, limit: int) -> int:
        """Queue up to `limit` backlog reports (newest first) for the claim-extraction routine."""
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            rows = (session.query(MarketReport).filter(MarketReport.status == "backlog")
                    .order_by(MarketReport.published_at.desc(), MarketReport.received_at.desc()).limit(limit).all())
            for row in rows:
                row.status = "claims_pending"
            return len(rows)

    def delete(self, report_id: str):
        if not self.sessions:
            raise RuntimeError("Market reports database unavailable")
        with self.sessions.begin() as session:
            report = session.get(MarketReport, report_id)
            if not report:
                return False
            session.delete(report)
            return True


market_reports_db = MarketReportsDatabase(market_dashboard_db.engine)
