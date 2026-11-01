"""Scheduled publisher: Wed/Fri/Sun 21:30 Asia/Taipei, every new public analysis revision to every configured channel."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .meta import Ambiguous, AuthError, PublishError

logger = logging.getLogger(__name__)
TAIPEI = ZoneInfo('Asia/Taipei')
RUN_DAYS = {2, 4, 6}  # Monday=0: Wednesday, Friday, Sunday
RUN_AT = (21, 30)
CURSOR = 'cursor'


def next_run(now):
    local = now.astimezone(TAIPEI)
    for offset in range(8):
        day = (local + timedelta(days=offset)).date()
        candidate = datetime(day.year, day.month, day.day, *RUN_AT, tzinfo=TAIPEI)
        if candidate.weekday() in RUN_DAYS and candidate > local:
            return candidate
    raise RuntimeError('No run day within a week')


def run_once(outbox, *, sources, current, publishers, now, notify, pause=lambda seconds: None):
    """One pass. `sources(since)` lists public analyses updated after `since`; `publishers` maps channel -> callable."""
    cursor = outbox.get(CURSOR)
    if cursor is None:
        outbox.set(CURSOR, now.isoformat())
        return {'baseline': now.isoformat(), 'published': 0}
    outbox.stall(now)
    channels = [channel for channel in ('facebook', 'instagram', 'threads') if channel in publishers]
    for source in sorted(sources(datetime.fromisoformat(cursor)), key=lambda row: row['updatedAt']):
        outbox.ensure(source['id'], channels, datetime.fromisoformat(source['updatedAt']))
    outbox.set(CURSOR, now.isoformat())

    blocked, published, first = set(), 0, True
    for row in outbox.due():
        channel = row['channel']
        if channel in blocked or channel not in publishers:
            continue
        kind, code, revision = row['id'].split(':')
        source = current(kind, code)
        if not source or source['revision'] != int(revision):
            outbox.supersede(row['id'], channel)
            continue
        if not outbox.claim(row['id'], channel, now):
            continue
        if not first:
            pause(20)  # space posts out; bursts look like spam to the platforms
        first = False
        try:
            result = publishers[channel](source)
        except AuthError as exc:
            outbox.requeue(row['id'], channel, exc)
            blocked.add(channel)
            if outbox.get(f'alerted:{channel}') is None:
                outbox.set(f'alerted:{channel}', 'auth')
                notify(channel, 'auth')
            continue
        except Ambiguous as exc:
            outbox.review(row['id'], channel, exc)
            notify(channel, 'pending_review')
            continue
        except PublishError as exc:
            outbox.failed(row['id'], channel, exc)
            continue
        except Exception as exc:  # unexpected: treat like an unknown outcome, never resend blindly
            logger.exception('Social publish crashed for %s %s', channel, row['id'])
            outbox.review(row['id'], channel, type(exc).__name__)
            notify(channel, 'pending_review')
            continue
        outbox.published(row['id'], channel, result.get('id'), result.get('url'))
        outbox.delete(f'alerted:{channel}')
        published += 1
    return {'baseline': None, 'published': published}


# ---- production wiring ----

_task = None


def enabled():
    return os.getenv('SOCIAL_PUBLISH_ENABLED', 'false').lower() == 'true'


def card_url(source):
    base = os.getenv('SOCIAL_CARD_BASE_URL', 'https://tymultiverse.cc/maya-sawa/market/publishing/cards').rstrip('/')
    return f"{base}/{source['productType']}/{source['code']}/{source['revision']}.png"


def threads_token(outbox, refresh=None, now=None):
    """Seed from the secret once, then keep the refreshed 60-day token in the database; refresh weekly."""
    from .meta import refresh_threads_token
    now = now or datetime.now(timezone.utc)
    token = outbox.get('threads_token') or os.getenv('THREADS_ACCESS_TOKEN', '').strip()
    if not token:
        return None
    refreshed = outbox.updated_at('threads_token')
    if refreshed is None or now - refreshed > timedelta(days=7):
        try:
            token = (refresh or refresh_threads_token)(token)
            outbox.set('threads_token', token)
        except PublishError:
            logger.warning('Threads token refresh failed; using the current token')
    return token


def build_publishers(outbox):
    """Only two secrets are required (Page token, Threads token); ids come from the environment or the tokens."""
    from . import meta
    from .post_text import build_post
    publishers = {}
    page_token = os.getenv('META_PAGE_ACCESS_TOKEN', '').strip()
    if page_token:
        page_id, ig_user = os.getenv('META_PAGE_ID', '').strip(), os.getenv('INSTAGRAM_USER_ID', '').strip()
        if not (page_id and ig_user):
            try:
                found = meta.discover_page(page_token)
                page_id, ig_user = page_id or found['page_id'], ig_user or (found['instagram_id'] or '')
            except meta.PublishError:
                logger.warning('Facebook Page lookup failed; Facebook and Instagram skipped this run')
        if page_id:
            page = meta.FacebookPage(page_id, page_token)
            publishers['facebook'] = lambda source: page.publish(build_post(source, 'facebook'))
        if page_id and ig_user:
            ig = meta.Instagram(ig_user, page_token)
            publishers['instagram'] = lambda source: ig.publish(build_post(source, 'instagram'), card_url(source))
    token = threads_token(outbox)
    if token:
        threads_user = os.getenv('THREADS_USER_ID', '').strip()
        if not threads_user:
            try:
                threads_user = meta.discover_threads_user(token)
            except meta.PublishError:
                logger.warning('Threads user lookup failed; Threads skipped this run')
        if threads_user:
            threads = meta.Threads(threads_user, token)
            publishers['threads'] = lambda source: threads.publish(build_post(source, 'threads'))
    return publishers


def notify_owner(channel, reason):
    from .. import telegram_notify
    names = {'facebook': 'Facebook 粉專', 'instagram': 'Instagram', 'threads': 'Threads'}
    if reason == 'auth':
        body = (f'{names.get(channel, channel)} 授權失效，該平台貼文已保留在佇列、不會遺失。\n'
                '請更新 Jenkins credential 後重新部署；恢復後下次排程會補發。')
    else:
        body = (f'{names.get(channel, channel)} 有一則貼文發布結果不明，已標為 pending_review、不會自動重送。\n'
                '請到平台確認是否已發出。')
    try:
        telegram_notify.send('attention', 'Birch 社群發文需要處理', body)
    except Exception:
        logger.warning('Social publishing alert was not delivered')


def run_now():
    from ...databases.market_ai_analysis_db import market_ai_analysis_db
    from ...databases.market_dashboard_db import market_dashboard_db
    from .outbox import SocialOutbox
    from .sources import public_sources
    outbox = SocialOutbox(market_dashboard_db.engine)

    def current(kind, code):
        return market_ai_analysis_db.read(kind, code).get('analysis')

    return run_once(outbox, sources=lambda since: public_sources(since, limit=None)['sources'], current=current,
                    publishers=build_publishers(outbox), now=datetime.now(timezone.utc), notify=notify_owner,
                    pause=lambda seconds: __import__('time').sleep(seconds))


async def scheduler():
    while True:
        wait = (next_run(datetime.now(timezone.utc)) - datetime.now(TAIPEI)).total_seconds()
        await asyncio.sleep(max(wait, 1))
        try:
            result = await asyncio.to_thread(run_now)
            logger.info('Social publish run: %s', result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Social publish run failed')


def start():
    global _task
    if enabled() and (_task is None or _task.done()):
        _task = asyncio.create_task(scheduler())


async def stop():
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
