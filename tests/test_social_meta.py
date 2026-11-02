"""Meta Graph / Threads API clients. Response shapes follow Meta's published docs (no live capture yet: no tokens)."""
import json
from pathlib import Path

import httpx
import pytest

from maya_sawa.services.social.meta import (Ambiguous, AuthError, FacebookPage, Instagram, Rejected, Threads,
                                            refresh_threads_token)

FIXTURES = json.loads((Path(__file__).parent / 'fixtures' / 'meta_responses.json').read_text(encoding='utf-8'))


def client(routes, calls):
    def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params), request.content.decode()))
        key = f'{request.method} {request.url.path}'
        response = routes[key]
        if isinstance(response, Exception):
            raise response
        status, body = response
        return httpx.Response(status, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_threads_publishes_text_and_returns_permalink():
    calls = []
    routes = {
        'POST /v1.0/111/threads': (200, FIXTURES['threads_container']),
        'GET /v1.0/178': (200, {'status': 'FINISHED', 'id': '178'}),
        'POST /v1.0/111/threads_publish': (200, FIXTURES['threads_publish']),
        'GET /v1.0/179': (200, FIXTURES['threads_permalink']),
    }
    result = Threads('111', 'tok', client(routes, calls), sleep=lambda s: None).publish('hello')
    assert result == {'id': '179', 'url': 'https://www.threads.com/@birch_investments/post/DAbc123'}
    assert 'media_type=TEXT' in calls[0][3] and 'text=hello' in calls[0][3]


def test_facebook_page_post_returns_permalink():
    calls = []
    routes = {'POST /v23.0/222/feed': (200, FIXTURES['facebook_feed']),
              'GET /v23.0/222_333': (200, FIXTURES['facebook_permalink'])}
    result = FacebookPage('222', 'tok', client(routes, calls)).publish('hello')
    assert result == {'id': '222_333', 'url': 'https://www.facebook.com/222/posts/333'}


def test_instagram_waits_for_the_container_then_publishes_with_image():
    calls = []
    statuses = iter([(200, {'status_code': 'IN_PROGRESS', 'id': '444'}), (200, {'status_code': 'FINISHED', 'id': '444'})])

    def handler(request):
        calls.append((request.method, request.url.path, request.content.decode()))
        key = f'{request.method} {request.url.path}'
        if key == 'GET /v23.0/444':
            status, body = next(statuses)
        else:
            status, body = {'POST /v23.0/555/media': (200, {'id': '444'}),
                            'POST /v23.0/555/media_publish': (200, {'id': '666'}),
                            'GET /v23.0/666': (200, FIXTURES['instagram_permalink'])}[key]
        return httpx.Response(status, json=body)

    ig = Instagram('555', 'tok', httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    result = ig.publish('caption', 'https://tymultiverse.cc/card.png')
    assert result == {'id': '666', 'url': 'https://www.instagram.com/p/DXyz789/'}
    assert 'image_url=https' in calls[0][2]


def test_expired_token_is_an_auth_error_and_nothing_is_published():
    calls = []
    routes = {'POST /v23.0/222/feed': (400, FIXTURES['error_expired_token'])}
    with pytest.raises(AuthError):
        FacebookPage('222', 'tok', client(routes, calls)).publish('hello')


def test_failure_before_the_publish_step_is_retryable_but_a_publish_timeout_is_ambiguous():
    calls = []
    routes = {'POST /v1.0/111/threads': (400, FIXTURES['error_invalid_parameter'])}
    with pytest.raises(Rejected):
        Threads('111', 'tok', client(routes, calls), sleep=lambda s: None).publish('hello')
    routes = {'POST /v1.0/111/threads': (200, {'id': '178'}),
              'GET /v1.0/178': (200, {'status': 'FINISHED', 'id': '178'}),
              'POST /v1.0/111/threads_publish': httpx.ReadTimeout('slow')}
    with pytest.raises(Ambiguous):
        Threads('111', 'tok', client(routes, []), sleep=lambda s: None).publish('hello')
    routes = {'POST /v23.0/222/feed': (500, FIXTURES['error_unknown'])}
    with pytest.raises(Ambiguous):
        FacebookPage('222', 'tok', client(routes, [])).publish('hello')


def test_published_post_without_permalink_still_counts_as_published():
    routes = {'POST /v23.0/222/feed': (200, FIXTURES['facebook_feed']),
              'GET /v23.0/222_333': (500, FIXTURES['error_unknown'])}
    assert FacebookPage('222', 'tok', client(routes, [])).publish('hello') == {'id': '222_333', 'url': None}


def test_threads_token_refresh_returns_new_token():
    routes = {'GET /refresh_access_token': (200, FIXTURES['threads_refresh'])}
    calls = []
    assert refresh_threads_token('old', client(routes, calls)) == 'THNEW'
    assert calls[0][2]['grant_type'] == 'th_refresh_token'


def test_page_token_discovers_the_page_and_its_linked_instagram_account():
    from maya_sawa.services.social.meta import discover_page
    no_accounts = (400, NONEXISTING_FIELD)  # a Page token has no /me/accounts edge
    routes = {'GET /v23.0/me/accounts': no_accounts, 'GET /v23.0/me': (200, FIXTURES['page_me'])}
    calls = []
    assert discover_page('tok', client(routes, calls)) == {'page_id': '222', 'instagram_id': '555', 'page_token': 'tok'}
    assert 'instagram_business_account' in calls[-1][2]['fields']
    routes = {'GET /v23.0/me/accounts': no_accounts, 'GET /v23.0/me': (200, {'id': '222', 'name': 'Birch Investments'})}
    assert discover_page('tok', client(routes, [])) == {'page_id': '222', 'instagram_id': None, 'page_token': 'tok'}


# Shape of the live error on 2026-11-02 when a USER token was saved as META_PAGE_ACCESS_TOKEN and /me asked for the IG field.
NONEXISTING_FIELD = {'error': {'message': '(#100) Tried accessing nonexisting field (instagram_business_account) on node type (User)',
                               'type': 'OAuthException', 'code': 100}}


def test_a_long_lived_user_token_is_exchanged_for_the_birch_page_token():
    """2026-11-02: Jenkins held a long-lived USER token; Facebook and Instagram were silently skipped."""
    from maya_sawa.services.social.meta import discover_page
    accounts = {'data': [{'id': '1425078927350905', 'name': 'Birch Investments', 'access_token': 'PAGE-TOKEN'}]}
    routes = {'GET /v23.0/me/accounts': (200, accounts)}
    calls = []
    found = discover_page('USER-TOKEN', client(routes, calls))
    assert found == {'page_id': '1425078927350905', 'instagram_id': None, 'page_token': 'PAGE-TOKEN'}
    assert 'access_token' in calls[0][2]['fields'] and 'instagram_business_account' in calls[0][2]['fields']
    linked = {'data': [{'id': '9', 'name': 'Other', 'access_token': 'X'},
                       {'id': '1425078927350905', 'name': 'Birch Investments', 'access_token': 'PAGE-TOKEN',
                        'instagram_business_account': {'id': '555'}}]}
    found = discover_page('USER-TOKEN', client({'GET /v23.0/me/accounts': (200, linked)}, []))
    assert found == {'page_id': '1425078927350905', 'instagram_id': '555', 'page_token': 'PAGE-TOKEN'}
    assert discover_page('USER-TOKEN', client({'GET /v23.0/me/accounts': (200, linked)}, []), page_id='9')['page_token'] == 'X'


def test_a_user_token_without_the_page_or_an_expired_token_is_an_error():
    from maya_sawa.services.social.meta import discover_page
    with pytest.raises(Rejected):
        discover_page('USER-TOKEN', client({'GET /v23.0/me/accounts': (200, {'data': []})}, []))
    expired = (400, {'error': {'message': 'Session has expired', 'type': 'OAuthException', 'code': 190}})
    with pytest.raises(AuthError):
        discover_page('USER-TOKEN', client({'GET /v23.0/me/accounts': expired}, []))


def test_threads_token_discovers_its_user_id():
    from maya_sawa.services.social.meta import discover_threads_user
    routes = {'GET /v1.0/me': (200, FIXTURES['threads_me'])}
    assert discover_threads_user('tok', client(routes, [])) == '111'
