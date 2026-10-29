from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.services.social_publish_queue import PublishQueue, notify_pending


@pytest.fixture
def queue():
    return PublishQueue(create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))


def test_pending_survives_new_service_instance_and_repeated_source_is_not_duplicated(queue):
    first = queue.enqueue('macro:US:8', '公開研究摘要')
    assert first['state'] == 'pending_auth'
    assert queue.enqueue('macro:US:8', '重送')['draft'] == '公開研究摘要'
    reopened = PublishQueue(queue.engine)
    assert [row['id'] for row in reopened.jobs()] == ['macro:US:8']


def test_login_alert_is_once_per_episode_and_failed_send_can_retry(queue):
    queue.enqueue('macro:US:8', 'draft')
    sent = []
    def send(*args):
        sent.append(args)
        return {'sent': True}
    assert notify_pending(queue, send=send)['sent']
    assert notify_pending(queue, send=send)['reason'] == 'already-notified'
    queue.enqueue('stock:2330:15', 'second')
    assert notify_pending(queue, send=send)['reason'] == 'already-notified'
    assert len(sent) == 1
    queue.resume()
    queue.auth_required('token_expired')
    assert not notify_pending(queue, send=lambda *args: {'sent': False})['sent']
    assert notify_pending(queue, send=send)['sent']
    assert len(sent) == 2


def test_claims_prevent_duplicate_publish_and_unknown_result_needs_review(queue):
    queue.enqueue('stock:2330:15', 'draft')
    assert not queue.claim('stock:2330:15')
    queue.resume()
    assert queue.claim('stock:2330:15')
    assert not queue.claim('stock:2330:15')
    queue.review('stock:2330:15')
    queue.resume()
    assert queue.jobs()[0]['state'] == 'pending_review'
    assert not queue.claim('stock:2330:15')
    url = 'https://www.threads.com/@birch_investments/post/ABC123'
    assert queue.complete('stock:2330:15', url)['state'] == 'published'
    assert queue.complete('stock:2330:15', url)['publishedUrl'] == url
    queue.auth_required('login_required')
    queue.resume()
    assert queue.jobs()[0]['state'] == 'published'


def test_only_verified_account_post_urls_and_claimed_jobs_can_be_completed(queue):
    queue.enqueue('macro:US:8', 'draft')
    with pytest.raises(ValueError):
        queue.complete('macro:US:8', 'https://www.threads.com/@birch_investments/post/ABC')
    queue.resume()
    queue.claim('macro:US:8')
    for url in ['https://evil.test/@birch_investments/post/ABC', 'https://www.threads.com/@someone/post/ABC']:
        with pytest.raises(ValueError):
            queue.complete('macro:US:8', url)


def test_heartbeat_timeout_retains_jobs_and_requires_attention(queue):
    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    queue.enqueue('macro:US:8', 'draft')
    queue.resume()
    queue.heartbeat(now)
    assert not queue.check_stalled(now + timedelta(hours=1))
    assert queue.check_stalled(now + timedelta(hours=3))
    assert queue.jobs()[0]['state'] == 'pending_auth'


def test_pending_review_from_crashed_publish_is_never_automatically_retried(queue):
    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    queue.enqueue('macro:US:8', 'draft')
    queue.resume()
    queue.claim('macro:US:8', now)
    assert queue.check_stalled(now + timedelta(minutes=31))
    assert queue.jobs()[0]['state'] == 'pending_review'
    assert not queue.claim('macro:US:8')


def test_failed_notice_remains_eligible_for_monitor_retry(queue):
    queue.enqueue('macro:US:8', 'draft')
    assert not notify_pending(queue, send=lambda *args: {'sent': False})['sent']
    assert queue.check_stalled()


def test_monitor_lifecycle_starts_once_and_can_be_stopped(monkeypatch, queue):
    import asyncio
    from maya_sawa.services import social_publish_queue as service
    monkeypatch.setattr(service, 'publishing_queue', lambda: queue)
    async def lifecycle():
        service.start_monitor()
        first = service._monitor
        service.start_monitor()
        assert service._monitor is first
        await service.stop_monitor()
        assert first.done() and service._monitor is None
    asyncio.run(lifecycle())
