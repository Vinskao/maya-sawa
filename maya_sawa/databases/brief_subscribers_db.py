"""Readers who asked for the daily reading by email (double opt-in)."""
import secrets
from uuid import uuid4

from sqlalchemy import Column, DateTime, Text, update
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class BriefSubscriber(Base):
    __tablename__ = 'maya_sawa_brief_subscriber'

    id = Column(Text, primary_key=True)
    email = Column(Text, nullable=False, unique=True)
    token = Column(Text, nullable=False, unique=True)       # in the confirm and unsubscribe links; never listed by any API
    status = Column(Text, nullable=False)                   # pending | confirmed | unsubscribed
    created_at = Column(DateTime(timezone=True), nullable=False)
    confirmation_sent_at = Column(DateTime(timezone=True))
    confirmed_at = Column(DateTime(timezone=True))
    last_sent_day = Column(Text)                            # Taipei day of the last daily reading delivered


def _row(row):
    return {'id': row.id, 'email': row.email, 'token': row.token, 'status': row.status,
            'last_sent_day': row.last_sent_day}


class BriefSubscribersDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def _require(self):
        if not self.sessions:
            raise RuntimeError('Brief subscribers database unavailable')
        return self.sessions

    def subscribe(self, email, now):
        """Idempotent: the same address keeps its token; an unsubscribed one starts over as pending."""
        email = email.strip().lower()
        with self._require().begin() as session:
            row = session.query(BriefSubscriber).filter_by(email=email).first()
            if row is None:
                row = BriefSubscriber(id=str(uuid4()), email=email, token=secrets.token_urlsafe(32), status='pending',
                                      created_at=now)
                session.add(row)
            elif row.status == 'unsubscribed':
                row.status, row.confirmation_sent_at, row.confirmed_at, row.created_at = 'pending', None, None, now
            return _row(row)

    def created_since(self, since):
        with self._require()() as session:
            return session.query(BriefSubscriber).filter(BriefSubscriber.created_at >= since).count()

    def _set(self, token, status, now=None):
        with self._require().begin() as session:
            row = session.query(BriefSubscriber).filter_by(token=token).first()
            if row is None:
                return None
            if status == 'confirmed' and row.status == 'pending':
                row.status, row.confirmed_at = 'confirmed', now
            elif status == 'unsubscribed':
                row.status = 'unsubscribed'
            return _row(row)

    def confirm(self, token, now=None):
        return self._set(token, 'confirmed', now)

    def unsubscribe(self, token):
        return self._set(token, 'unsubscribed')

    def confirmed(self):
        with self._require()() as session:
            return [_row(row) for row in session.query(BriefSubscriber).filter_by(status='confirmed')
                    .order_by(BriefSubscriber.created_at).all()]

    def awaiting_confirmation_mail(self, limit=50):
        with self._require()() as session:
            return [_row(row) for row in session.query(BriefSubscriber)
                    .filter_by(status='pending', confirmation_sent_at=None).order_by(BriefSubscriber.created_at).limit(limit).all()]

    def claim_confirmation_mail(self, subscriber_id, now):
        """True for exactly one caller, so two pods never send the same confirmation."""
        with self._require().begin() as session:
            return session.execute(update(BriefSubscriber).where(
                BriefSubscriber.id == subscriber_id, BriefSubscriber.confirmation_sent_at.is_(None))
                .values(confirmation_sent_at=now)).rowcount == 1

    def release_confirmation_mail(self, subscriber_id):
        with self._require().begin() as session:
            session.execute(update(BriefSubscriber).where(BriefSubscriber.id == subscriber_id).values(confirmation_sent_at=None))

    def claim_daily(self, subscriber_id, day):
        """True for exactly one caller per subscriber per day; returns the previous day so a failure can restore it."""
        with self._require().begin() as session:
            row = session.query(BriefSubscriber).filter_by(id=subscriber_id, status='confirmed').first()
            if row is None or row.last_sent_day == day:
                return False, None
            previous = row.last_sent_day
            claimed = session.execute(update(BriefSubscriber).where(
                BriefSubscriber.id == subscriber_id,
                BriefSubscriber.last_sent_day.is_(None) if previous is None else BriefSubscriber.last_sent_day == previous)
                .values(last_sent_day=day)).rowcount == 1
            return claimed, previous

    def release_daily(self, subscriber_id, day, previous):
        with self._require().begin() as session:
            session.execute(update(BriefSubscriber).where(
                BriefSubscriber.id == subscriber_id, BriefSubscriber.last_sent_day == day).values(last_sent_day=previous))
