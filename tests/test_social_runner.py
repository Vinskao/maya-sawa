import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.services.social.meta import Ambiguous, AuthError, Rejected
from maya_sawa.services.social.outbox import SocialOutbox
from maya_sawa.services.social.runner import next_run, run_once

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def outbox():
    return SocialOutbox(create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))


def analysis(code, revision, updated, kind='stock'):
    return {'id': f'{kind}:{code}:{revision}', 'productType': kind, 'code': code, 'revision': revision,
            'updatedAt': updated.isoformat(), 'content': f'{code} rev {revision}'}


class World:
    """Public analyses plus fake platform publishers that record what was posted."""

    def __init__(self):
        self.rows = {}
        self.posted = []
        self.behaviour = {}
        self.notices = []

    def add(self, row):
        self.rows[(row['productType'], row['code'])] = row

    def sources(self, since):
        return [row for row in self.rows.values() if datetime.fromisoformat(row['updatedAt']) > since]

    def current(self, kind, code):
        return self.rows.get((kind, code))

    def publisher(self, channel):
        def publish(source):
            action = self.behaviour.get(channel)
            if action:
                raise action
            self.posted.append((channel, source['id']))
            return {'id': f'{channel}-{source["id"]}', 'url': f'https://{channel}.test/{source["code"]}'}
        return publish

    def run(self, outbox, now, channels=('facebook', 'instagram', 'threads')):
        return run_once(outbox, sources=self.sources, current=self.current,
                        publishers={channel: self.publisher(channel) for channel in channels},
                        now=now, notify=lambda channel, reason: self.notices.append((channel, reason)))


def test_first_run_records_a_baseline_and_does_not_backfill(outbox):
    world = World()
    world.add(analysis('2330', 4, T0 - timedelta(days=1)))
    assert world.run(outbox, T0)['baseline']
    assert world.posted == []


def test_new_revisions_go_to_every_channel_oldest_first_and_only_once(outbox):
    world = World()
    world.run(outbox, T0)
    world.add(analysis('2330', 5, T0 + timedelta(hours=2)))
    world.add(analysis('US', 9, T0 + timedelta(hours=1), kind='macro'))
    world.run(outbox, T0 + timedelta(days=2))
    assert world.posted == [('facebook', 'macro:US:9'), ('instagram', 'macro:US:9'), ('threads', 'macro:US:9'),
                            ('facebook', 'stock:2330:5'), ('instagram', 'stock:2330:5'), ('threads', 'stock:2330:5')]
    rows = {(row['id'], row['channel']): row for row in outbox.posts()}
    assert rows[('stock:2330:5', 'threads')] == {**rows[('stock:2330:5', 'threads')], 'state': 'published',
                                                 'url': 'https://threads.test/2330'}
    world.run(outbox, T0 + timedelta(days=4))
    assert len(world.posted) == 6


def test_rejected_post_is_retried_up_to_three_attempts(outbox):
    world = World()
    world.run(outbox, T0)
    world.add(analysis('2330', 5, T0 + timedelta(hours=1)))
    world.behaviour['instagram'] = Rejected('image not reachable')
    for day in (2, 4, 6, 8):
        world.run(outbox, T0 + timedelta(days=day))
    row = next(row for row in outbox.posts() if row['channel'] == 'instagram')
    assert row['state'] == 'failed' and row['attempts'] == 3
    world.behaviour.clear()
    world.run(outbox, T0 + timedelta(days=10))
    assert ('instagram', 'stock:2330:5') not in world.posted


def test_ambiguous_outcome_goes_to_review_is_never_resent_and_alerts(outbox):
    world = World()
    world.run(outbox, T0)
    world.add(analysis('2330', 5, T0 + timedelta(hours=1)))
    world.behaviour['threads'] = Ambiguous('publish timed out')
    world.run(outbox, T0 + timedelta(days=2))
    world.behaviour.clear()
    world.run(outbox, T0 + timedelta(days=4))
    assert ('threads', 'stock:2330:5') not in world.posted
    assert next(row for row in outbox.posts() if row['channel'] == 'threads')['state'] == 'pending_review'
    assert world.notices == [('threads', 'pending_review')]


def test_auth_failure_pauses_only_that_channel_alerts_once_and_recovers(outbox):
    world = World()
    world.run(outbox, T0)
    world.add(analysis('2330', 5, T0 + timedelta(hours=1)))
    world.add(analysis('2408', 2, T0 + timedelta(hours=2)))
    world.behaviour['facebook'] = AuthError('token expired')
    world.run(outbox, T0 + timedelta(days=2))
    world.run(outbox, T0 + timedelta(days=4))
    assert world.notices == [('facebook', 'auth')]
    assert {channel for channel, _ in world.posted} == {'instagram', 'threads'}
    facebook = [row for row in outbox.posts() if row['channel'] == 'facebook']
    assert all(row['state'] == 'queued' and row['attempts'] == 0 for row in facebook)
    world.behaviour.clear()
    world.run(outbox, T0 + timedelta(days=6))
    assert [source for channel, source in world.posted if channel == 'facebook'] == ['stock:2330:5', 'stock:2408:2']
    world.behaviour['facebook'] = AuthError('expired again')
    world.add(analysis('2330', 6, T0 + timedelta(days=7)))
    world.run(outbox, T0 + timedelta(days=8))
    assert world.notices == [('facebook', 'auth'), ('facebook', 'auth')]


def test_superseded_revision_is_skipped_in_favour_of_the_newer_one(outbox):
    world = World()
    world.run(outbox, T0)
    world.add(analysis('2330', 5, T0 + timedelta(hours=1)))
    world.behaviour['threads'] = Rejected('temporary')
    world.run(outbox, T0 + timedelta(days=2))
    world.behaviour.clear()
    world.add(analysis('2330', 6, T0 + timedelta(days=3)))
    world.run(outbox, T0 + timedelta(days=4))
    assert ('threads', 'stock:2330:5') not in world.posted
    assert ('threads', 'stock:2330:6') in world.posted
    states = {(row['id'], row['channel']): row['state'] for row in outbox.posts()}
    assert states[('stock:2330:5', 'threads')] == 'superseded'


def test_post_stuck_in_publishing_moves_to_review(outbox):
    outbox.ensure('stock:2330:5', ['threads'])
    assert outbox.claim('stock:2330:5', 'threads', T0)
    assert outbox.stall(T0 + timedelta(minutes=29)) == 0
    assert outbox.stall(T0 + timedelta(minutes=31)) == 1
    assert outbox.posts()[0]['state'] == 'pending_review'
    assert not outbox.claim('stock:2330:5', 'threads', T0 + timedelta(hours=1))


def test_next_run_is_wednesday_friday_sunday_at_2130_taipei():
    taipei = ZoneInfo('Asia/Taipei')
    monday = datetime(2026, 11, 2, 10, 0, tzinfo=taipei)
    assert next_run(monday) == datetime(2026, 11, 4, 21, 30, tzinfo=taipei)
    assert next_run(datetime(2026, 11, 4, 21, 30, tzinfo=taipei)) == datetime(2026, 11, 6, 21, 30, tzinfo=taipei)
    assert next_run(datetime(2026, 11, 6, 22, 0, tzinfo=taipei)) == datetime(2026, 11, 8, 21, 30, tzinfo=taipei)
    assert next_run(datetime(2026, 11, 8, 23, 0, tzinfo=taipei)) == datetime(2026, 11, 11, 21, 30, tzinfo=taipei)


def test_threads_token_is_seeded_from_the_secret_then_refreshed_weekly_into_the_database(outbox, monkeypatch):
    from maya_sawa.services.social import runner
    monkeypatch.setenv('THREADS_ACCESS_TOKEN', 'SEED')
    refreshed = []

    def refresh(token):
        refreshed.append(token)
        return f'{token}+1'

    assert runner.threads_token(outbox, refresh, T0) == 'SEED+1'
    assert runner.threads_token(outbox, refresh, T0 + timedelta(days=1)) == 'SEED+1'  # stored, not refreshed again
    assert refreshed == ['SEED']
    stored_at = outbox.updated_at('threads_token')
    assert runner.threads_token(outbox, refresh, stored_at + timedelta(days=8)) == 'SEED+1+1'


def test_only_channels_with_credentials_are_published(outbox, monkeypatch):
    from maya_sawa.services.social import meta, runner
    for name in ('META_PAGE_ID', 'META_PAGE_ACCESS_TOKEN', 'INSTAGRAM_USER_ID', 'THREADS_USER_ID', 'THREADS_ACCESS_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    found = {'page_id': '1', 'instagram_id': None}
    monkeypatch.setattr(meta, 'discover_page', lambda token: dict(found))
    monkeypatch.setattr(meta, 'discover_threads_user', lambda token: '9')
    monkeypatch.setattr(runner, 'threads_token', lambda outbox: os.environ.get('THREADS_ACCESS_TOKEN'))
    assert runner.build_publishers(outbox) == {}
    monkeypatch.setenv('META_PAGE_ACCESS_TOKEN', 'p')
    assert set(runner.build_publishers(outbox)) == {'facebook'}
    found['instagram_id'] = '2'
    assert set(runner.build_publishers(outbox)) == {'facebook', 'instagram'}
    monkeypatch.setenv('THREADS_ACCESS_TOKEN', 't')
    assert set(runner.build_publishers(outbox)) == {'facebook', 'instagram', 'threads'}


def test_ids_from_the_environment_win_and_a_failed_lookup_only_skips_that_channel(outbox, monkeypatch):
    from maya_sawa.services.social import meta, runner
    monkeypatch.setenv('META_PAGE_ACCESS_TOKEN', 'p')
    monkeypatch.setenv('META_PAGE_ID', '1')
    monkeypatch.setenv('INSTAGRAM_USER_ID', '2')
    monkeypatch.setenv('THREADS_ACCESS_TOKEN', 't')
    monkeypatch.delenv('THREADS_USER_ID', raising=False)
    monkeypatch.setattr(runner, 'threads_token', lambda outbox: 't')

    def fail(token):
        raise meta.AuthError('expired')

    monkeypatch.setattr(meta, 'discover_page', fail)  # not called: both ids are configured
    monkeypatch.setattr(meta, 'discover_threads_user', fail)
    assert set(runner.build_publishers(outbox)) == {'facebook', 'instagram'}


def test_card_url_points_at_the_public_card_route():
    from maya_sawa.services.social.runner import card_url
    assert card_url({'productType': 'stock', 'code': '2330', 'revision': 5}) == \
        'https://tymultiverse.cc/maya-sawa/market/publishing/cards/stock/2330/5.png'


def test_missing_instagram_link_alerts_once_and_rearms_after_it_is_linked(outbox, monkeypatch):
    from maya_sawa.services.social import meta, runner
    for name in ('META_PAGE_ID', 'INSTAGRAM_USER_ID', 'THREADS_USER_ID', 'THREADS_ACCESS_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('META_PAGE_ACCESS_TOKEN', 'p')
    monkeypatch.setattr(runner, 'threads_token', lambda outbox: None)
    found = {'page_id': '1', 'instagram_id': None}
    monkeypatch.setattr(meta, 'discover_page', lambda token: dict(found))
    notices = []
    notify = lambda channel, reason: notices.append((channel, reason))

    assert set(runner.build_publishers(outbox, notify)) == {'facebook'}
    assert set(runner.build_publishers(outbox, notify)) == {'facebook'}
    assert notices == [('instagram', 'not_linked')]  # once, not on every run

    found['instagram_id'] = '2'
    assert set(runner.build_publishers(outbox, notify)) == {'facebook', 'instagram'}
    assert len(notices) == 1
    found['instagram_id'] = None  # unlinked again later: alert again
    runner.build_publishers(outbox, notify)
    assert notices == [('instagram', 'not_linked')] * 2


def test_failed_page_lookup_is_not_reported_as_a_missing_instagram_link(outbox, monkeypatch):
    from maya_sawa.services.social import meta, runner
    for name in ('META_PAGE_ID', 'INSTAGRAM_USER_ID', 'THREADS_USER_ID', 'THREADS_ACCESS_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('META_PAGE_ACCESS_TOKEN', 'p')
    monkeypatch.setattr(runner, 'threads_token', lambda outbox: None)

    def fail(token):
        raise meta.AuthError('expired')

    monkeypatch.setattr(meta, 'discover_page', fail)
    notices = []
    assert runner.build_publishers(outbox, lambda channel, reason: notices.append((channel, reason))) == {}
    assert notices == []


def test_owner_message_for_a_missing_instagram_link_says_what_to_do(monkeypatch):
    from maya_sawa.services import telegram_notify
    from maya_sawa.services.social import runner
    sent = []
    monkeypatch.setattr(telegram_notify, 'send', lambda kind, title, body='': sent.append((kind, title, body)))
    runner.notify_owner('instagram', 'not_linked')
    kind, title, body = sent[0]
    assert kind == 'attention' and 'Instagram' in body and '粉專' in body and '略過' in body
