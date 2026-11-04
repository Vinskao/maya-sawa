"""Durable completed narration, keyed by the exact public analysis revision."""
from datetime import datetime, timezone
import hashlib

from sqlalchemy import Column, DateTime, Integer, LargeBinary, Text, select, text, update
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class MarketAudio(Base):
    __tablename__ = 'maya_sawa_market_audio'
    product_type = Column(Text, primary_key=True)
    code = Column(Text, primary_key=True)
    revision = Column(Integer, primary_key=True)
    source_text = Column(Text, nullable=False)
    source_sha256 = Column(Text, nullable=False)
    audio_data = Column(LargeBinary, nullable=False)
    content_type = Column(Text, nullable=False)
    voice = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class MarketAudioJob(Base):
    __tablename__ = 'maya_sawa_market_audio_job'
    product_type = Column(Text, primary_key=True)
    code = Column(Text, primary_key=True)
    revision = Column(Integer, primary_key=True)
    source_text = Column(Text, nullable=False)
    source_sha256 = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    error_type = Column(Text)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MarketAudioMonthlyUsage(Base):
    __tablename__ = 'maya_sawa_market_audio_monthly_usage'
    month = Column(Text, primary_key=True)
    reserved_characters = Column(Integer, nullable=False, default=0)


class MarketAudioDatabase:
    def __init__(self, engine):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def acquire_worker_lock(self):
        """Hold one PostgreSQL session advisory lock to prevent multi-pod F0 workers."""
        if not self.engine or self.engine.dialect.name != 'postgresql':
            return None
        connection = self.engine.connect()
        acquired = connection.execute(text('SELECT pg_try_advisory_lock(hashtext(:key))'),
                                      {'key': 'market_audio_single_worker'}).scalar()
        if not acquired:
            connection.close()
            return None
        return connection

    @staticmethod
    def release_worker_lock(connection):
        if connection is None:
            return
        try:
            connection.execute(text('SELECT pg_advisory_unlock(hashtext(:key))'),
                               {'key': 'market_audio_single_worker'})
        finally:
            connection.close()

    def save(self, product_type, code, revision, text, audio, content_type, voice):
        if not text or not audio or revision < 1:
            raise ValueError('Complete text and nonempty audio are required')
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        with self.sessions.begin() as session:
            existing = session.get(MarketAudio, (product_type, code, revision))
            digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
            if existing:
                if existing.source_sha256 != digest:
                    raise ValueError('Revision already exists with different source')
                return
            session.add(MarketAudio(product_type=product_type, code=code, revision=revision,
                                    source_text=text, source_sha256=digest, audio_data=audio,
                                    content_type=content_type, voice=voice,
                                    created_at=datetime.now(timezone.utc)))

    def enqueue(self, product_type, code, revision, source_text):
        if product_type not in {'macro', 'stock', 'daily'} or not code or len(code) > 64 or revision < 1 or not source_text.strip():
            raise ValueError('Valid audio source and revision are required')
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        digest = hashlib.sha256(source_text.encode('utf-8')).hexdigest()
        with self.sessions.begin() as session:
            row = session.get(MarketAudioJob, (product_type, code, revision))
            if row:
                if row.source_sha256 != digest:
                    raise ValueError('Revision already exists with different source')
                return False
            session.add(MarketAudioJob(product_type=product_type, code=code, revision=revision,
                                       source_text=source_text, source_sha256=digest, status='pending',
                                       attempts=0, updated_at=datetime.now(timezone.utc)))
        return True

    def claim(self, max_attempts=3, product_type=None, codes=None):
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        with self.sessions.begin() as session:
            query = select(MarketAudioJob).where(
                MarketAudioJob.status.in_(['pending', 'retry']), MarketAudioJob.attempts < max_attempts
            ).order_by(MarketAudioJob.updated_at).with_for_update(skip_locked=True)
            if product_type is not None:
                query = query.where(MarketAudioJob.product_type == product_type)
            if codes is not None:
                if not codes:
                    return None
                query = query.where(MarketAudioJob.code.in_(codes))
            row = session.execute(query).scalars().first()
            if row is None:
                return None
            row.status = 'processing'
            row.attempts += 1
            row.error_type = None
            row.updated_at = datetime.now(timezone.utc)
            session.flush()
            return {'productType': row.product_type, 'code': row.code, 'revision': row.revision,
                    'sourceText': row.source_text, 'sourceSha256': row.source_sha256, 'attempts': row.attempts}

    def finish_job(self, product_type, code, revision, status, error_type=None):
        if status not in {'ready', 'retry', 'failed', 'blocked'}:
            raise ValueError('Invalid audio job result')
        with self.sessions.begin() as session:
            changed = session.execute(update(MarketAudioJob).where(
                MarketAudioJob.product_type == product_type, MarketAudioJob.code == code,
                MarketAudioJob.revision == revision, MarketAudioJob.status == 'processing'
            ).values(status=status, error_type=error_type, updated_at=datetime.now(timezone.utc))).rowcount
            return changed == 1

    def reserve_monthly_characters(self, characters, limit, now=None):
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        if characters < 1 or limit < 1:
            raise ValueError('A positive monthly character limit is required')
        month = (now or datetime.now(timezone.utc)).strftime('%Y-%m')
        with self.sessions.begin() as session:
            if session.bind.dialect.name == 'postgresql':
                session.execute(text('SELECT pg_advisory_xact_lock(hashtext(:key))'),
                                {'key': 'market_audio_usage:' + month})
            row = session.get(MarketAudioMonthlyUsage, month)
            if row is None:
                row = MarketAudioMonthlyUsage(month=month, reserved_characters=0)
                session.add(row)
                session.flush()
            if row.reserved_characters + characters > limit:
                raise AudioBudgetExceeded('Monthly character budget would be exceeded')
            row.reserved_characters += characters
            return row.reserved_characters

    def monthly_reserved_characters(self, month=None):
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        month = month or datetime.now(timezone.utc).strftime('%Y-%m')
        with self.sessions() as session:
            row = session.get(MarketAudioMonthlyUsage, month)
            return row.reserved_characters if row else 0

    def job(self, product_type, code, revision):
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        with self.sessions() as session:
            row = session.get(MarketAudioJob, (product_type, code, revision))
            if not row:
                return None
            return {'productType': row.product_type, 'code': row.code, 'revision': row.revision,
                    'status': row.status, 'attempts': row.attempts, 'errorType': row.error_type}


    def list_ready(self):
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        with self.sessions() as session:
            rows = session.execute(select(MarketAudio.product_type, MarketAudio.code,
                                          MarketAudio.revision, MarketAudio.voice,
                                          MarketAudio.created_at).order_by(MarketAudio.created_at.desc())).all()
            return [{'productType': row.product_type, 'code': row.code, 'revision': row.revision,
                     'voice': row.voice, 'createdAt': row.created_at.isoformat()} for row in rows]

    def audio(self, product_type, code, revision):
        if not self.sessions:
            raise RuntimeError('Audio database unavailable')
        with self.sessions() as session:
            row = session.get(MarketAudio, (product_type, code, revision))
            return (row.audio_data, row.content_type) if row else None


class AudioBudgetExceeded(Exception):
    pass
