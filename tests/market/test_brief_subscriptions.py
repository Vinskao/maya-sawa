"""Daily reading by email: double opt-in, one mail per subscriber per day, unsubscribe in every mail."""
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from maya_sawa.api.brief_subscriptions import make_router
from maya_sawa.databases.brief_subscribers_db import BriefSubscribersDatabase
from maya_sawa.services.brief_mailer import BriefMailer, daily_message, confirmation_message

NOW = datetime(2026, 11, 10, 2, tzinfo=timezone.utc)
BRIEF = {'id': 'b1', 'day': '2026-11-10', 'title': '淨流動性收緊下的營收驗證', 'content': '今天市場的第一段。\n第二段。'}
LINKS = [{'label': 'Spotify', 'href': 'https://open.spotify.com/show/x'}, {'label': 'Threads', 'href': 'https://threads.net/@x'}]


def _db():
    return BriefSubscribersDatabase(create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool))


class Outbox:
    def __init__(self, fail_for=()):
        self.sent, self.fail_for = [], set(fail_for)

    def __call__(self, message):
        if message['To'] in self.fail_for:
            raise OSError('smtp down')
        self.sent.append(message)


def _mailer(db, outbox, configured=True):
    return BriefMailer(db, send=outbox, configured=lambda: configured, sender='Birch <brief@tymultiverse.cc>',
                       site='https://tymultiverse.cc', links=LINKS, now=lambda: NOW)


def test_subscribe_is_pending_until_the_emailed_link_is_opened():
    db = _db()
    row = db.subscribe(' Reader@Example.com ', NOW)
    assert row['email'] == 'reader@example.com' and row['status'] == 'pending' and len(row['token']) >= 32
    assert db.subscribe('reader@example.com', NOW)['token'] == row['token']      # asking twice is the same subscription
    assert db.confirmed() == []
    assert db.confirm('wrong') is None
    assert db.confirm(row['token'])['status'] == 'confirmed'
    assert [s['email'] for s in db.confirmed()] == ['reader@example.com']
    assert db.unsubscribe(row['token'])['status'] == 'unsubscribed'
    assert db.confirmed() == []
    assert db.subscribe('reader@example.com', NOW)['status'] == 'pending'         # may opt in again, and must confirm again


def test_confirmation_mail_goes_out_once_and_only_when_mail_is_configured():
    db = _db()
    db.subscribe('a@example.com', NOW)
    off = Outbox()
    _mailer(db, off, configured=False).run_once(BRIEF)
    assert off.sent == []
    out = Outbox()
    mailer = _mailer(db, out)
    mailer.run_once(None)
    mailer.run_once(None)
    assert len(out.sent) == 1
    token = db.subscribe('a@example.com', NOW)['token']
    assert f'https://tymultiverse.cc/api/market/subscriptions/confirm?token={token}' in out.sent[0].get_content()


def test_daily_mail_reaches_each_confirmed_reader_once_with_text_links_and_unsubscribe():
    db = _db()
    a = db.subscribe('a@example.com', NOW)
    db.confirm(a['token'])
    b = db.subscribe('b@example.com', NOW)
    db.confirm(b['token'])
    db.subscribe('pending@example.com', NOW)
    out = Outbox(fail_for={'b@example.com'})
    _mailer(db, out).run_once(BRIEF)
    daily = [m for m in out.sent if m['To'] == 'a@example.com']
    assert len(daily) == 1 and '淨流動性收緊下的營收驗證' in daily[0]['Subject']
    body = daily[0].get_content()
    assert '今天市場的第一段。' in body and '第二段。' in body
    assert 'https://open.spotify.com/show/x' in body and 'https://threads.net/@x' in body
    unsubscribe = f"https://tymultiverse.cc/api/market/subscriptions/unsubscribe?token={a['token']}"
    assert unsubscribe in body and unsubscribe in daily[0]['List-Unsubscribe']
    assert daily[0]['List-Unsubscribe-Post'] == 'List-Unsubscribe=One-Click'
    # a failed delivery is retried on the next run; a delivered one is never repeated that day
    retry = Outbox()
    _mailer(db, retry).run_once(BRIEF)
    assert [m['To'] for m in retry.sent if '淨流動性' in m['Subject']] == ['b@example.com']
    again = Outbox()
    _mailer(db, again).run_once(BRIEF)
    assert [m for m in again.sent if '淨流動性' in m['Subject']] == []


def test_messages_are_plain_text_with_the_disclaimer():
    message = daily_message(BRIEF, 'r@example.com', 'tok', sender='Birch <b@x.cc>', site='https://tymultiverse.cc', links=LINKS)
    assert message.get_content_type() == 'text/plain' and '不構成投資建議' in message.get_content()
    assert 'tok' in confirmation_message('r@example.com', 'tok', sender='Birch <b@x.cc>', site='https://tymultiverse.cc').get_content()


def _client(db, limit=200):
    app = FastAPI()
    app.include_router(make_router(db, lambda: NOW, daily_limit=limit))
    return TestClient(app)


def test_api_accepts_an_address_without_revealing_whether_it_exists():
    db = _db()
    client = _client(db)
    first = client.post('/market/subscriptions', json={'email': 'reader@example.com'})
    second = client.post('/market/subscriptions', json={'email': 'reader@example.com'})
    assert first.status_code == 200 and first.json() == second.json() == {'status': 'pending'}
    assert client.post('/market/subscriptions', json={'email': 'not-an-email'}).status_code == 422
    assert client.post('/market/subscriptions', json={'email': 'a@b.cc\nBcc: x@y.zz'}).status_code == 422


def test_api_confirm_and_unsubscribe_by_token_and_caps_new_signups_per_day():
    db = _db()
    client = _client(db, limit=2)
    client.post('/market/subscriptions', json={'email': 'a@example.com'})
    token = db.subscribe('a@example.com', NOW)['token']
    assert client.get('/market/subscriptions/confirm', params={'token': 'nope'}).status_code == 404
    assert client.get('/market/subscriptions/confirm', params={'token': token}).json()['status'] == 'confirmed'
    assert client.post('/market/subscriptions/unsubscribe', params={'token': token}).json()['status'] == 'unsubscribed'
    assert client.get('/market/subscriptions/unsubscribe', params={'token': token}).json()['status'] == 'unsubscribed'
    client.post('/market/subscriptions', json={'email': 'b@example.com'})
    assert client.post('/market/subscriptions', json={'email': 'c@example.com'}).status_code == 429
