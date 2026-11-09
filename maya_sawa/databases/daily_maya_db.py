"""Isolated daily brief proposals; only reviewed records are public."""
from datetime import datetime
import hashlib
import json
import uuid

from sqlalchemy import Column, DateTime, Text, UniqueConstraint, inspect, update, text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class DailyMayaProposal(Base):
    __tablename__ = 'maya_sawa_daily_maya_proposal'
    __table_args__ = (UniqueConstraint('day', 'digest'),)
    id = Column(Text, primary_key=True)
    day = Column(Text, nullable=False, index=True)
    digest = Column(Text, nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=False)
    reviewed_at = Column(DateTime(timezone=True))
    review_note = Column(Text)
    # Public episode title (podcast feed and Learn list). Nullable: older rows have none.
    title = Column(Text)


def _row(row):
    return {'id': row.id, 'day': row.day, 'content': row.content, 'sources': json.loads(row.sources),
            'status': row.status, 'submittedAt': row.submitted_at.isoformat(),
            'reviewedAt': row.reviewed_at.isoformat() if row.reviewed_at else None,
            'reviewNote': row.review_note, 'title': row.title}


class DailyMayaDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)
            self._add_missing_columns(engine)

    @staticmethod
    def _add_missing_columns(engine):
        # create_all never alters an existing table, so add the title column in place.
        columns = {column['name'] for column in inspect(engine).get_columns(DailyMayaProposal.__tablename__)}
        if 'title' not in columns:
            with engine.begin() as connection:
                connection.execute(text('ALTER TABLE ' + DailyMayaProposal.__tablename__ + ' ADD COLUMN title TEXT'))

    def submit(self, day, content, sources, now, limit=10, title=None):
        datetime.strptime(day, '%Y-%m-%d')
        if not content.strip() or len(content) > 20000 or not sources or len(sources) > 50:
            raise ValueError('Content and bounded sources required')
        source_json = json.dumps(sorted(set(sources)), ensure_ascii=False)
        digest = hashlib.sha256((content + '\0' + source_json).encode()).hexdigest()
        with self.sessions.begin() as session:
            # Serialize each day's submissions across PostgreSQL workers, including
            # the duplicate check and limit. SQLite is for single-process tests.
            if session.bind.dialect.name == 'postgresql':
                session.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),
                                {'key': 'daily_maya:' + day})
            old = session.query(DailyMayaProposal).filter_by(day=day, digest=digest).first()
            if old:
                return _row(old), False
            if session.query(DailyMayaProposal).filter_by(day=day).count() >= limit:
                raise OverflowError('Daily proposal inbox is full')
            row = DailyMayaProposal(id=str(uuid.uuid4()), day=day, digest=digest, content=content,
                                    sources=source_json, status='pending', submitted_at=now, title=title)
            session.add(row)
            session.flush()
            return _row(row), True

    def pending(self):
        with self.sessions() as session:
            rows = session.query(DailyMayaProposal).filter_by(status='pending').order_by(
                DailyMayaProposal.submitted_at).limit(100).all()
            return [_row(row) for row in rows]

    def get(self, proposal_id):
        with self.sessions() as session:
            row = session.get(DailyMayaProposal, proposal_id)
            return _row(row) if row else None

    def review(self, proposal_id, decision, note, now):
        if decision not in {'approved', 'rejected'} or not note.strip():
            raise ValueError('Decision and review note required')
        with self.sessions.begin() as session:
            changed = session.execute(update(DailyMayaProposal).where(
                DailyMayaProposal.id == proposal_id, DailyMayaProposal.status == 'pending'
            ).values(status=decision, review_note=note, reviewed_at=now)).rowcount
            return changed == 1

    def published(self):
        with self.sessions() as session:
            rows = session.query(DailyMayaProposal).filter_by(status='approved').order_by(
                DailyMayaProposal.day.desc(), DailyMayaProposal.reviewed_at.desc()).limit(100).all()
            return [_row(row) for row in rows]
