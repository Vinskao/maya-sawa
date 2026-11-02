import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.services.social.meta import Ambiguous, AuthError, Rejected
from maya_sawa.services.social.outbox import SocialOutbox
from maya_sawa.services.social.runner import CATCHUP_SECONDS, RunTrigger, run_once

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
        return [row for row in self.rows.values() if since is None or datetime.fromisoformat(row['updatedAt']) > since]

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


def test_latest_revision_of_every_analysis_is_posted_even_if_it_predates_the_first_run(outbox):
    """2026-11-02: every stock's and the macro's latest analysis must have been posted; no baseline skip."""
    world = World()
    world.add(analysis('2330', 4, T0 - timedelta(days=30)))
    world.add(analysis('US', 7, T0 - timedelta(days=1), kind='macro'))
    world.run(outbox, T0)
    world.run(outbox, T0 + timedelta(minutes=10))
    assert sorted(world.posted) == sorted((channel, source) for channel in ('facebook', 'instagram', 'threads')
                                          for source in ('stock:2330:4', 'macro:US:7'))
    world.run(outbox, T0 + timedelta(hours=1))
    assert len(world.posted) == 6  # already posted: never again


def test_backlog_goes_out_one_analysis_per_ten_minutes_while_new_saves_post_at_once(outbox):
    """Owner's choice 2026-11-02: 27 unposted analyses in one burst could get Threads flagged as spam."""
    world = World()
    for code in ('1111', '2222', '3333'):
        world.add(analysis(code, 1, T0 - timedelta(days=3)))
    world.run(outbox, T0)
    assert {source for _, source in world.posted} == {'stock:1111:1'}  # oldest backlog item, every channel
    world.add(analysis('9999', 1, T0 + timedelta(minutes=2)))  # a new save
    world.run(outbox, T0 + timedelta(minutes=3))
    assert {source for _, source in world.posted} == {'stock:1111:1', 'stock:9999:1'}  # fresh: no 10-minute wait
    world.run(outbox, T0 + timedelta(minutes=10))
    assert 'stock:2222:1' in {source for _, source in world.posted}
    assert 'stock:3333:1' not in {source for _, source in world.posted}
    world.run(outbox, T0 + timedelta(minutes=20))
    assert len(world.posted) == 4 * 3


def test_coverage_reports_each_latest_analysis_per_channel(outbox):
    from maya_sawa.services.social.runner import coverage
    world = World()
    world.add(analysis('2330', 4, T0 - timedelta(days=1)))
    world.add(analysis('2408', 2, T0 - timedelta(days=1)))
    world.behaviour['threads'] = Rejected('temporary')
    world.run(outbox, T0)
    world.run(outbox, T0 + timedelta(minutes=10))  # backlog: one analysis per 10 minutes
    report = coverage(outbox, world.sources(None), ['facebook', 'threads'])
    assert report['complete'] is False
    assert {row['id']: row['channels'] for row in report['sources']} == {
        'stock:2330:4': {'facebook': 'published', 'threads': 'failed'},
        'stock:2408:2': {'facebook': 'published', 'threads': 'failed'}}
    world.add(analysis('2330', 5, T0 + timedelta(minutes=1)))  # saved, not yet run
    assert coverage(outbox, world.sources(None), ['facebook'])['sources'][0]['channels'] == {'facebook': 'missing'}
    world.behaviour.clear()
    for minutes in (60, 70, 80):
        world.run(outbox, T0 + timedelta(minutes=minutes))
    assert coverage(outbox, world.sources(None), ['facebook', 'instagram', 'threads'])['complete'] is True


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


def test_rejected_post_keeps_being_retried_until_posted_and_alerts_once_after_three_failures(outbox):
    world = World()
    world.run(outbox, T0)
    world.add(analysis('2330', 5, T0 + timedelta(hours=1)))
    world.behaviour['instagram'] = Rejected('image not reachable')
    for hour in (2, 3, 4, 5, 6):
        world.run(outbox, T0 + timedelta(hours=hour))
    row = next(row for row in outbox.posts() if row['channel'] == 'instagram')
    assert row['state'] == 'failed' and row['attempts'] == 5
    assert world.notices == [('instagram', 'failing')]  # once, not every hour
    world.behaviour.clear()
    world.run(outbox, T0 + timedelta(hours=7))
    assert ('instagram', 'stock:2330:5') in world.posted


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
    world.run(outbox, T0 + timedelta(days=6, minutes=10))  # held-back posts are backlog now: one per 10 minutes
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


def test_a_new_analysis_revision_triggers_one_coalesced_run():
    """The owner wants a post as soon as an analysis is updated, not on a weekly slot."""
    import threading
    ran, done = [], threading.Event()
    trigger = RunTrigger(lambda: (ran.append(1), done.set()), delay=0.05)
    for _ in range(5):  # a batch of saves inside the delay window
        trigger.fire()
    assert done.wait(2)
    done.clear()
    trigger.fire()  # a later save schedules a new run
    assert done.wait(2)
    assert len(ran) == 2


def test_a_failing_run_does_not_stop_later_triggers():
    import threading
    done, calls = threading.Event(), []
    def run():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('boom')
        done.set()
    trigger = RunTrigger(run, delay=0.01)
    trigger.fire()
    while len(calls) < 1:
        pass
    trigger.fire()
    assert done.wait(2)


def test_catch_up_sweep_retries_failed_posts_at_least_hourly():
    assert 0 < CATCHUP_SECONDS <= 3600


def test_saving_an_analysis_notifies_listeners_only_for_a_new_revision(tmp_path):
    from maya_sawa.databases.market_ai_analysis_db import MarketAiAnalysisDatabase
    db = MarketAiAnalysisDatabase(create_engine(f"sqlite:///{tmp_path / 'a.db'}"))
    seen = []
    db.listeners.append(lambda product_type, code, revision: seen.append((product_type, code, revision)))
    first = db.save('stock', '2330', 'm', '中立', 0, 'agent')
    assert seen == [('stock', '2330', 1)]
    db.listeners.insert(0, lambda *args: (_ for _ in ()).throw(RuntimeError('listener bug')))
    db.save('stock', '2330', 'm', '偏多', first['revision'], 'agent')  # a broken listener never fails the save
    assert seen[-1] == ('stock', '2330', 2)


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


def test_facebook_and_instagram_post_with_the_page_token_found_from_a_user_token(outbox, monkeypatch):
    from maya_sawa.services.social import meta, runner
    for name in ('META_PAGE_ID', 'INSTAGRAM_USER_ID', 'THREADS_ACCESS_TOKEN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('META_PAGE_ACCESS_TOKEN', 'USER-TOKEN')
    monkeypatch.setattr(runner, 'threads_token', lambda outbox: None)
    monkeypatch.setattr(meta, 'discover_page', lambda token: {'page_id': '1', 'instagram_id': '2', 'page_token': 'PAGE-TOKEN'})
    used = []
    monkeypatch.setattr(meta, 'FacebookPage', lambda page_id, token: used.append(('facebook', token)))
    monkeypatch.setattr(meta, 'Instagram', lambda ig_id, token: used.append(('instagram', token)))
    runner.build_publishers(outbox)
    assert used == [('facebook', 'PAGE-TOKEN'), ('instagram', 'PAGE-TOKEN')]


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


def test_linkedin_is_published_only_when_its_token_is_configured(outbox, monkeypatch):
    from maya_sawa.services.social import linkedin, runner
    for name in ('META_PAGE_ACCESS_TOKEN', 'THREADS_ACCESS_TOKEN', 'LINKEDIN_ACCESS_TOKEN', 'LINKEDIN_PERSON_URN'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runner, 'threads_token', lambda outbox: None)
    assert runner.build_publishers(outbox) == {}
    monkeypatch.setenv('LINKEDIN_ACCESS_TOKEN', 'tok')
    monkeypatch.setattr(linkedin, 'discover_person', lambda token: 'urn:li:person:42')
    assert set(runner.build_publishers(outbox)) == {'linkedin'}
    monkeypatch.setattr(linkedin, 'discover_person', lambda token: (_ for _ in ()).throw(linkedin.Rejected('x')))
    assert runner.build_publishers(outbox) == {}  # a failed lookup only skips LinkedIn this run
    monkeypatch.setenv('LINKEDIN_PERSON_URN', 'urn:li:person:42')
    assert set(runner.build_publishers(outbox)) == {'linkedin'}  # the configured URN needs no lookup


def test_every_post_carries_the_card_plus_the_diagrams_of_the_current_research_record():
    import json
    from maya_sawa.services.social.runner import image_urls
    research = {'revision': 3, 'content': json.dumps({'name': 'x', 'supplyChain': 'flowchart TB\n A-->B',
                                                       'technology': 'flowchart LR\n C-->D'})}
    source = {'productType': 'stock', 'code': '2330', 'revision': 5}
    urls = image_urls(source, read_research=lambda code: research)
    base = 'https://tymultiverse.cc/maya-sawa/market/publishing'
    assert urls == [f'{base}/cards/stock/2330/5.png', f'{base}/diagrams/2330/3/0.png', f'{base}/diagrams/2330/3/1.png']
    assert image_urls(source, read_research=lambda code: None) == [urls[0]]  # no research record: the card alone
    assert image_urls({'productType': 'macro', 'code': 'US', 'revision': 9},
                      read_research=lambda code: research) == [f'{base}/cards/macro/US/9.png']
    def broken(code):
        raise RuntimeError('db down')
    assert image_urls(source, read_research=broken) == [urls[0]]  # a failed lookup never blocks the post


def test_backlog_sweep_that_runs_a_moment_early_still_posts_the_next_item(outbox):
    """2026-11-02: the 10-minute sweep fired 0.5 s short of a 10-minute gap and the next post waited a whole extra sweep."""
    world = World()
    for code in ('1111', '2222'):
        world.add(analysis(code, 1, T0 - timedelta(days=3)))
    world.run(outbox, T0)
    world.run(outbox, T0 + timedelta(minutes=9, seconds=59))  # one sweep later, half a second early
    assert {source for _, source in world.posted} == {'stock:1111:1', 'stock:2222:1'}


def test_instagram_posts_through_its_own_login_token_even_when_the_page_is_not_linked(outbox, monkeypatch):
    from maya_sawa.services.social import meta, runner
    for name in ('META_PAGE_ACCESS_TOKEN', 'THREADS_ACCESS_TOKEN', 'LINKEDIN_ACCESS_TOKEN', 'INSTAGRAM_USER_ID'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(runner, 'threads_token', lambda outbox: None)
    monkeypatch.setattr(runner, 'instagram_token', lambda outbox: os.environ.get('INSTAGRAM_ACCESS_TOKEN'))
    assert runner.build_publishers(outbox) == {}
    monkeypatch.setenv('INSTAGRAM_ACCESS_TOKEN', 'igtok')
    monkeypatch.setattr(meta, 'discover_instagram_user', lambda token: '1784')
    made = []
    monkeypatch.setattr(meta, 'Instagram', lambda user, token, **kw: made.append((user, token, kw.get('base'))))
    assert set(runner.build_publishers(outbox)) == {'instagram'}
    assert made == [('1784', 'igtok', meta.INSTAGRAM_LOGIN)]
    monkeypatch.setattr(meta, 'discover_instagram_user', lambda token: (_ for _ in ()).throw(meta.Rejected('x')))
    assert runner.build_publishers(outbox) == {}  # a failed lookup only skips Instagram this run


def test_instagram_token_is_seeded_from_the_secret_then_refreshed_weekly_into_the_database(outbox, monkeypatch):
    from maya_sawa.services.social import runner
    monkeypatch.setenv('INSTAGRAM_ACCESS_TOKEN', 'SEED')
    refreshed = []
    refresh = lambda token: refreshed.append(token) or token + '+1'
    assert runner.instagram_token(outbox, refresh, T0) == 'SEED+1'
    assert runner.instagram_token(outbox, refresh, T0 + timedelta(days=1)) == 'SEED+1'  # stored, not refreshed again
    assert refreshed == ['SEED']
    monkeypatch.delenv('INSTAGRAM_ACCESS_TOKEN')
    assert runner.instagram_token(outbox, refresh, T0) == 'SEED+1'  # the stored token keeps working
