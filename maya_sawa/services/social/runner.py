"""Publisher: every new public analysis revision goes to every configured channel as soon as it is saved.

A save fires `RunTrigger` (coalesced over a short delay); an hourly catch-up sweep retries failed/queued posts."""
import asyncio
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from .meta import Ambiguous, AuthError, PublishError
from .outbox import MAX_ATTEMPTS

logger = logging.getLogger(__name__)
CURSOR = 'cursor'
TRIGGER_DELAY_SECONDS = 30  # saves within this window go out in one run
CATCHUP_SECONDS = 600  # sweep: retries and the next backlog item
BACKLOG_AT = 'backlog_at'
BACKLOG_GAP = timedelta(minutes=10)  # unposted older analyses go out one at a time, this far apart (spam risk)


class RunTrigger:
    """Run `run` once, `delay` seconds after the first fire; fires while one is pending join it. Runs never overlap."""

    def __init__(self, run, delay=TRIGGER_DELAY_SECONDS):
        self.run, self.delay = run, delay
        self._lock, self._running = threading.Lock(), threading.Lock()
        self._pending = False

    def fire(self):
        with self._lock:
            if self._pending:
                return
            self._pending = True
        timer = threading.Timer(self.delay, self._go)
        timer.daemon = True
        timer.start()

    def _go(self):
        with self._running:
            with self._lock:
                self._pending = False  # a save during this run schedules the next one
            try:
                self.run()
            except Exception:
                logger.exception('Triggered social publish run failed')


def run_once(outbox, *, sources, current, publishers, now, notify, pause=lambda seconds: None):
    """One pass. `sources(None)` lists the latest public analysis of every stock plus macro:US; each must end up
    published on every configured channel, so anything not yet posted (including old backlog) is queued and sent."""
    outbox.stall(now)
    channels = [channel for channel in ('facebook', 'instagram', 'threads') if channel in publishers]
    last_run = outbox.get(CURSOR)
    fresh = set()  # saved since the previous run: posted at once; everything else is backlog, paced
    for source in sorted(sources(None), key=lambda row: row['updatedAt']):
        updated = datetime.fromisoformat(source['updatedAt'])
        outbox.ensure(source['id'], channels, updated)
        if last_run and updated > datetime.fromisoformat(last_run):
            fresh.add(source['id'])
    outbox.set(CURSOR, now.isoformat())

    backlog_at = outbox.get(BACKLOG_AT)
    backlog_open = backlog_at is None or now - datetime.fromisoformat(backlog_at) >= BACKLOG_GAP
    backlog_item = None
    # stable sort: fresh saves first, then never-tried backlog, then retries of failed posts; oldest first within each
    due = sorted(outbox.due(), key=lambda row: (row['id'] not in fresh, row['state'] == 'failed'))
    blocked, published, first = set(), 0, True
    for row in due:
        channel = row['channel']
        if channel in blocked or channel not in publishers:
            continue
        if row['id'] not in fresh:
            if not backlog_open or (backlog_item and backlog_item != row['id']):
                continue
            if backlog_item is None:
                backlog_item = row['id']
                outbox.set(BACKLOG_AT, now.isoformat())
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
            alert_key = f"alerted:failing:{row['id']}:{channel}"
            if row['attempts'] + 1 >= MAX_ATTEMPTS and outbox.get(alert_key) is None:
                outbox.set(alert_key, str(exc)[:200])
                notify(channel, 'failing')
            continue
        except Exception as exc:  # unexpected: treat like an unknown outcome, never resend blindly
            logger.exception('Social publish crashed for %s %s', channel, row['id'])
            outbox.review(row['id'], channel, type(exc).__name__)
            notify(channel, 'pending_review')
            continue
        outbox.published(row['id'], channel, result.get('id'), result.get('url'))
        outbox.delete(f'alerted:{channel}')
        outbox.delete(f"alerted:failing:{row['id']}:{channel}")
        published += 1
    return {'published': published}


def coverage(outbox, sources, channels):
    """For the latest revision of every public analysis: its state on each channel ('missing' = not queued yet)."""
    states = {(row['id'], row['channel']): row['state'] for row in outbox.posts()}
    report = [{'id': source['id'], 'updatedAt': source['updatedAt'],
               'channels': {channel: states.get((source['id'], channel), 'missing') for channel in channels}}
              for source in sorted(sources, key=lambda row: row['updatedAt'], reverse=True)]
    return {'complete': all(state == 'published' for row in report for state in row['channels'].values()),
            'sources': report}


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


def build_publishers(outbox, notify=None):
    """Only two secrets are required (Page token, Threads token); ids come from the environment or the tokens.

    `notify(channel, reason)` is told once when the Page has no linked Instagram account, until that is fixed."""
    from . import meta
    from .post_text import build_post
    publishers = {}
    page_token = os.getenv('META_PAGE_ACCESS_TOKEN', '').strip()
    if page_token:
        page_id, ig_user = os.getenv('META_PAGE_ID', '').strip(), os.getenv('INSTAGRAM_USER_ID', '').strip()
        looked_up = False
        if not (page_id and ig_user):
            try:
                found = meta.discover_page(page_token)
                page_id, ig_user = page_id or found['page_id'], ig_user or (found['instagram_id'] or '')
                page_token = found.get('page_token') or page_token  # a user token is swapped for the Page's own token
                looked_up = True
            except meta.PublishError:
                logger.warning('Facebook Page lookup failed; Facebook and Instagram skipped this run')
        _instagram_link_alert(outbox, notify, linked=bool(ig_user), checked=looked_up or bool(ig_user))
        if page_id:
            page = meta.FacebookPage(page_id, page_token)
            publishers['facebook'] = lambda source: page.publish(build_post(source, 'facebook'), card_url(source))
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
            publishers['threads'] = lambda source: threads.publish(build_post(source, 'threads'), card_url(source))
    return publishers


def _instagram_link_alert(outbox, notify, linked, checked):
    """Instagram posts only exist when the Page has a linked professional account; say so once instead of skipping silently."""
    if not checked:
        return  # the Page lookup failed: we do not know, so do not claim the link is missing
    if linked:
        outbox.delete('alerted:instagram_link')
    elif notify and outbox.get('alerted:instagram_link') is None:
        outbox.set('alerted:instagram_link', 'not_linked')
        notify('instagram', 'not_linked')


def notify_owner(channel, reason):
    from .. import telegram_notify
    names = {'facebook': 'Facebook 粉專', 'instagram': 'Instagram', 'threads': 'Threads'}
    name = names.get(channel, channel)
    if reason == 'auth':
        body = (f'{name} 授權失效，該平台貼文已保留在佇列、不會遺失。\n'
                '請更新 Jenkins credential 後重新部署；恢復後下次排程會補發。')
    elif reason == 'failing':
        body = (f'{name} 有貼文連續發布失敗 {MAX_ATTEMPTS} 次（平台拒絕，尚未發出）。之後每輪仍會自動重試直到發出；'
                '請看 /maya-sawa/market/publishing/social/status 的 error 欄位。')
    elif reason == 'not_linked':
        body = ('Instagram 尚未連結到 Facebook 粉專，這一輪只發 Facebook 與 Threads，Instagram 被略過；'
                '之後才連結的話，被略過的貼文不會補發。\n'
                '請在 Instagram App：個人檔案 → 編輯個人檔案 → 粉專，選 Birch Investments 連結。'
                '連結後若仍被略過，請重新產生 META_PAGE_ACCESS_TOKEN（選到 Instagram 帳號）並更新 Jenkins。')
    else:
        body = (f'{name} 有一則貼文發布結果不明，已標為 pending_review、不會自動重送。\n'
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
                    publishers=build_publishers(outbox, notify_owner), now=datetime.now(timezone.utc), notify=notify_owner,
                    pause=lambda seconds: __import__('time').sleep(seconds))


def _logged_run():
    logger.info('Social publish run: %s', run_now())


trigger = RunTrigger(_logged_run)


def on_analysis_saved(product_type, code, revision):
    """Listener for market_ai_analysis_db: post the new revision right away."""
    if enabled():
        trigger.fire()


async def scheduler():
    """Catch-up sweep: retries failed/queued posts and anything a lost trigger missed."""
    while True:
        try:
            await asyncio.to_thread(trigger.fire)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception('Social publish sweep failed')
        await asyncio.sleep(CATCHUP_SECONDS)


def start():
    global _task
    if not enabled():
        return
    from ...databases.market_ai_analysis_db import market_ai_analysis_db
    if on_analysis_saved not in market_ai_analysis_db.listeners:
        market_ai_analysis_db.listeners.append(on_analysis_saved)
    if _task is None or _task.done():
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
