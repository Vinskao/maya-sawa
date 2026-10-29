"""Durable Threads outbox. Credentials and Telegram routing stay on the server."""
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import Boolean, Column, DateTime, Integer, Text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
ACCOUNT = 'birch_investments'
logger = logging.getLogger(__name__)


class PublisherAccount(Base):
    __tablename__ = 'maya_sawa_publisher_account'
    account = Column(Text, primary_key=True)
    ready = Column(Boolean, nullable=False, default=False)
    notified = Column(Boolean, nullable=False, default=False)
    heartbeat_at = Column(DateTime(timezone=True))
    reason = Column(Text, nullable=False, default='missing_connection')


class PublishJob(Base):
    __tablename__ = 'maya_sawa_publish_job'
    source_key = Column(Text, primary_key=True)
    draft = Column(Text, nullable=False)
    state = Column(Text, nullable=False)
    published_url = Column(Text)
    started_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, nullable=False, default=0)


def _aware(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc)


def public_job(row):
    return {'id': row.source_key, 'draft': row.draft, 'state': row.state,
            'publishedUrl': row.published_url, 'attempts': row.attempts,
            'createdAt': _aware(row.created_at).isoformat()}


class PublishQueue:
    def __init__(self, engine):
        if engine is None:
            raise RuntimeError('Publishing database unavailable')
        self.engine = engine
        self.sessions = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        try:
            with self.sessions.begin() as session:
                if session.get(PublisherAccount, ACCOUNT) is None:
                    session.add(PublisherAccount(account=ACCOUNT))
        except IntegrityError:  # another worker initialized the same singleton
            pass

    def status(self):
        with self.sessions() as session:
            account = session.get(PublisherAccount, ACCOUNT)
            return {'account': ACCOUNT, 'platform': 'threads', 'ready': account.ready,
                    'reason': account.reason, 'jobs': self.jobs()}

    def jobs(self):
        with self.sessions() as session:
            return [public_job(row) for row in session.query(PublishJob).order_by(PublishJob.created_at).all()]

    def enqueue(self, source_key, draft):
        if not re.fullmatch(r'(stock|macro):[A-Z0-9.-]{1,24}:[1-9][0-9]*', source_key):
            raise ValueError('Invalid public analysis identity')
        if not isinstance(draft, str) or not 1 <= len(draft.strip()) <= 1800:
            raise ValueError('Draft must contain 1 to 1800 characters')
        from .telegram_notify import mask
        if mask(draft) != draft:
            raise ValueError('Draft contains credential-like content')
        try:
            with self.sessions.begin() as session:
                row = session.get(PublishJob, source_key)
                if row is None:
                    account = session.get(PublisherAccount, ACCOUNT)
                    row = PublishJob(source_key=source_key, draft=draft.strip(),
                                     state='ready' if account.ready else 'pending_auth',
                                     created_at=datetime.now(timezone.utc))
                    session.add(row)
                    session.flush()
                return public_job(row)
        except IntegrityError:
            with self.sessions() as session:
                return public_job(session.get(PublishJob, source_key))

    def auth_required(self, reason):
        if reason not in {'missing_connection', 'login_required', 'token_expired', 'heartbeat_missing'}:
            raise ValueError('Invalid pending reason')
        with self.sessions.begin() as session:
            account = session.get(PublisherAccount, ACCOUNT)
            account.ready, account.reason = False, reason
            session.execute(update(PublishJob).where(PublishJob.state == 'ready').values(state='pending_auth'))

    def resume(self):
        """Caller must verify the Metricool brand and connection before resuming."""
        with self.sessions.begin() as session:
            account = session.get(PublisherAccount, ACCOUNT)
            account.ready, account.notified, account.reason = True, False, ''
            session.execute(update(PublishJob).where(PublishJob.state == 'pending_auth').values(state='ready'))

    def claim(self, source_key, now=None):
        with self.sessions.begin() as session:
            if not session.get(PublisherAccount, ACCOUNT).ready:
                return False
            result = session.execute(update(PublishJob).where(PublishJob.source_key == source_key,
                PublishJob.state == 'ready').values(state='publishing', started_at=now or datetime.now(timezone.utc),
                                                    attempts=PublishJob.attempts + 1))
            return result.rowcount == 1

    def review(self, source_key):
        with self.sessions.begin() as session:
            session.execute(update(PublishJob).where(PublishJob.source_key == source_key,
                PublishJob.state == 'publishing').values(state='pending_review'))

    def complete(self, source_key, url):
        parsed = urlparse(url)
        if (parsed.scheme != 'https' or parsed.netloc not in {'threads.com', 'www.threads.com'} or
                not re.fullmatch(r'/@birch_investments/post/[A-Za-z0-9_-]+/?', parsed.path)):
            raise ValueError('A verified birch_investments Threads post URL is required')
        with self.sessions.begin() as session:
            row = session.get(PublishJob, source_key)
            if row is None or row.state not in {'publishing', 'pending_review', 'published'}:
                raise ValueError('Job must be claimed before publishing')
            if row.state == 'published':
                if row.published_url != url:
                    raise ValueError('This source revision was already published')
                return public_job(row)
            result = session.execute(update(PublishJob).where(PublishJob.source_key == source_key,
                PublishJob.state.in_(['publishing', 'pending_review'])).values(state='published', published_url=url))
            if result.rowcount != 1:
                raise ValueError('Publication state changed; reread before retrying')
            session.expire(row)
            return public_job(row)

    def heartbeat(self, now=None):
        with self.sessions.begin() as session:
            session.get(PublisherAccount, ACCOUNT).heartbeat_at = now or datetime.now(timezone.utc)

    def check_stalled(self, now=None):
        now = now or datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            account = session.get(PublisherAccount, ACCOUNT)
            stale = account.heartbeat_at and now - _aware(account.heartbeat_at) >= timedelta(hours=3)
            if stale:
                account.ready, account.reason = False, 'heartbeat_missing'
                session.execute(update(PublishJob).where(PublishJob.state == 'ready').values(state='pending_auth'))
            result = session.execute(update(PublishJob).where(PublishJob.state == 'publishing',
                PublishJob.started_at <= now - timedelta(minutes=30)).values(state='pending_review'))
            pending = session.query(PublishJob.source_key).filter(
                PublishJob.state.in_(['pending_auth', 'pending_review'])).first()
            return bool(stale or result.rowcount or pending)

    def claim_notice(self):
        with self.sessions.begin() as session:
            result = session.execute(update(PublisherAccount).where(PublisherAccount.account == ACCOUNT,
                PublisherAccount.notified.is_(False)).values(notified=True))
            return result.rowcount == 1

    def retry_notice(self):
        with self.sessions.begin() as session:
            session.get(PublisherAccount, ACCOUNT).notified = False


def notify_pending(queue, send=None, history=None):
    from . import telegram_notify
    if not queue.claim_notice():
        return {'sent': False, 'reason': 'already-notified'}
    rows = [row for row in queue.jobs() if row['state'].startswith('pending_')]
    title = 'Birch Threads 發文待處理'
    body = (f'帳號：{ACCOUNT}\n待處理：{len(rows)} 篇，內容與來源版本已保留。\n'
            '請檢查 ChatGPT／Metricool 登入與 Threads 授權；重新連接後再恢復佇列。\n'
            '若為 pending_review，先查平台是否已發布，不可直接重送。\n'
            'https://chatgpt.com/c/6ae3248f-32b8-83ee-8364-0f01607b8064')
    try:
        result = (send or telegram_notify.send)('attention', title, body)
    except Exception:
        queue.retry_notice()
        return {'sent': False, 'reason': 'delivery-failed'}
    if not result.get('sent'):
        queue.retry_notice()
    elif history:
        try:
            history('attention', title, body)
        except Exception:
            logger.warning('Publishing attention history was not stored')
    return result


_queue = None
_monitor = None


def publishing_queue():
    global _queue
    if _queue is None:
        from ..databases.market_dashboard_db import market_dashboard_db
        _queue = PublishQueue(market_dashboard_db.engine)
    return _queue


async def monitor():
    from ..databases.market_notification_db import market_notification_db
    while True:
        try:
            queue = await asyncio.to_thread(publishing_queue)
            if await asyncio.to_thread(queue.check_stalled):
                await asyncio.to_thread(notify_pending, queue, history=market_notification_db.add)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Publishing monitor failed')
        await asyncio.sleep(15 * 60)


def start_monitor():
    global _monitor
    if _monitor is None or _monitor.done():
        _monitor = asyncio.create_task(monitor())


async def stop_monitor():
    global _monitor
    if _monitor:
        _monitor.cancel()
        try:
            await _monitor
        except asyncio.CancelledError:
            pass
        _monitor = None
