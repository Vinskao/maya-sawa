"""Durable per-channel outbox: one row per (analysis revision, platform), so a post is never sent twice.

States: queued -> publishing -> published | failed (retryable, nothing posted) | pending_review (outcome unknown,
never resent automatically) | superseded (a newer revision of the same analysis replaced it before it went out).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, Integer, Text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
CHANNEL_ORDER = ('facebook', 'instagram', 'threads', 'linkedin')
MAX_ATTEMPTS = 3  # after this many failed attempts the owner is alerted once; retries continue on every run
STALL = timedelta(minutes=30)


class SocialPost(Base):
    __tablename__ = 'maya_sawa_social_post'
    source_key = Column(Text, primary_key=True)
    channel = Column(Text, primary_key=True)
    state = Column(Text, nullable=False)
    source_updated_at = Column(DateTime(timezone=True), nullable=False)
    post_id = Column(Text)
    url = Column(Text)
    error = Column(Text)
    attempts = Column(Integer, nullable=False, default=0)
    started_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), nullable=False)


class SocialState(Base):
    __tablename__ = 'maya_sawa_social_state'
    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


def _aware(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc) if value else None


def public_post(row):
    return {'id': row.source_key, 'channel': row.channel, 'state': row.state, 'postId': row.post_id, 'url': row.url,
            'error': row.error, 'attempts': row.attempts, 'sourceUpdatedAt': _aware(row.source_updated_at).isoformat()}


class SocialOutbox:
    def __init__(self, engine):
        if engine is None:
            raise RuntimeError('Publishing database unavailable')
        self.sessions = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

    def get(self, key):
        with self.sessions() as session:
            row = session.get(SocialState, key)
            return row.value if row else None

    def set(self, key, value):
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            row = session.get(SocialState, key)
            if row:
                row.value, row.updated_at = value, now
            else:
                session.add(SocialState(key=key, value=value, updated_at=now))

    def updated_at(self, key):
        with self.sessions() as session:
            row = session.get(SocialState, key)
            return _aware(row.updated_at) if row else None

    def delete(self, key):
        with self.sessions.begin() as session:
            row = session.get(SocialState, key)
            if row:
                session.delete(row)

    def ensure(self, source_key, channels, source_updated_at=None):
        now = datetime.now(timezone.utc)
        for channel in channels:
            try:
                with self.sessions.begin() as session:
                    if session.get(SocialPost, (source_key, channel)) is None:
                        session.add(SocialPost(source_key=source_key, channel=channel, state='queued',
                                               source_updated_at=source_updated_at or now, updated_at=now))
            except IntegrityError:  # another worker queued it first
                pass

    def posts(self):
        with self.sessions() as session:
            rows = session.query(SocialPost).all()
            rows.sort(key=lambda row: (_aware(row.source_updated_at), row.source_key, CHANNEL_ORDER.index(row.channel)
                                       if row.channel in CHANNEL_ORDER else 99))
            return [public_post(row) for row in rows]

    def due(self):
        """Failed posts (nothing went live) stay due on every run until they succeed; see MAX_ATTEMPTS for the alert."""
        return [row for row in self.posts() if row['state'] in ('queued', 'failed')]

    def _move(self, source_key, channel, allowed, **values):
        values['updated_at'] = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            result = session.execute(update(SocialPost).where(SocialPost.source_key == source_key,
                SocialPost.channel == channel, SocialPost.state.in_(allowed)).values(**values))
            return result.rowcount == 1

    def claim(self, source_key, channel, now):
        with self.sessions.begin() as session:
            result = session.execute(update(SocialPost).where(
                SocialPost.source_key == source_key, SocialPost.channel == channel,
                SocialPost.state.in_(['queued', 'failed'])
            ).values(state='publishing', started_at=now, attempts=SocialPost.attempts + 1, updated_at=now))
            return result.rowcount == 1

    def published(self, source_key, channel, post_id, url):
        return self._move(source_key, channel, ['publishing'], state='published', post_id=post_id, url=url, error=None)

    def failed(self, source_key, channel, error):
        return self._move(source_key, channel, ['publishing'], state='failed', error=str(error)[:300])

    def requeue(self, source_key, channel, error):
        """Auth problems are not the post's fault: put it back without spending an attempt."""
        return self._move(source_key, channel, ['publishing'], state='queued', error=str(error)[:300],
                          attempts=SocialPost.attempts - 1)

    def review(self, source_key, channel, error):
        return self._move(source_key, channel, ['publishing'], state='pending_review', error=str(error)[:300])

    def supersede(self, source_key, channel):
        return self._move(source_key, channel, ['queued', 'failed'], state='superseded')

    def stall(self, now):
        with self.sessions.begin() as session:
            result = session.execute(update(SocialPost).where(SocialPost.state == 'publishing',
                SocialPost.started_at <= now - STALL).values(state='pending_review', error='publishing stalled',
                                                             updated_at=now))
            return result.rowcount
