"""Minimal Meta Graph API (Facebook Page, Instagram) and Threads API publishing clients.

Error classes decide what the outbox may do next:
- AuthError: token expired/revoked. Nothing posted; keep the post queued and alert the owner once.
- Rejected: failed before the final publish call. Nothing posted; safe to retry later.
- Ambiguous: the final publish call timed out or returned a server error. The post may be live; never resend automatically.
"""
import time

import httpx

GRAPH = 'https://graph.facebook.com/v23.0'
THREADS = 'https://graph.threads.net/v1.0'
AUTH_CODES = {102, 190}


class PublishError(Exception):
    pass


class AuthError(PublishError):
    pass


class Rejected(PublishError):
    pass


class Ambiguous(PublishError):
    pass


def _call(client, method, url, token, final=False, **fields):
    params = {**fields, 'access_token': token}
    try:
        response = (client.post(url, data=params, timeout=30) if method == 'POST'
                    else client.get(url, params=params, timeout=30))
    except httpx.HTTPError as exc:
        raise (Ambiguous if final else Rejected)(type(exc).__name__) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    error = body.get('error') if isinstance(body, dict) else None
    if response.status_code < 400 and not error:
        return body
    code = (error or {}).get('code')
    message = (error or {}).get('message') or f'HTTP {response.status_code}'
    if code in AUTH_CODES or response.status_code == 401:
        raise AuthError(message)
    if final and response.status_code >= 500:
        raise Ambiguous(message)
    raise Rejected(message)


def _permalink(client, base, media_id, token, field):
    try:
        return _call(client, 'GET', f'{base}/{media_id}', token, fields=field).get(field)
    except PublishError:
        return None  # the post is live; a missing link must not turn it into a retry


def _wait_ready(client, base, container, token, field, sleep, tries=10):
    for _ in range(tries):
        status = _call(client, 'GET', f'{base}/{container}', token, fields=field).get(field)
        if status in {'FINISHED', None}:
            return
        if status in {'ERROR', 'EXPIRED'}:
            raise Rejected(f'Container {status}')
        sleep(3)
    raise Rejected('Container not ready')


class Threads:
    def __init__(self, user_id, token, client=None, sleep=time.sleep):
        self.user_id, self.token, self.client, self.sleep = user_id, token, client or httpx.Client(), sleep

    def publish(self, text):
        container = _call(self.client, 'POST', f'{THREADS}/{self.user_id}/threads', self.token,
                          media_type='TEXT', text=text)['id']
        _wait_ready(self.client, THREADS, container, self.token, 'status', self.sleep)
        media = _call(self.client, 'POST', f'{THREADS}/{self.user_id}/threads_publish', self.token, final=True,
                      creation_id=container)['id']
        return {'id': media, 'url': _permalink(self.client, THREADS, media, self.token, 'permalink')}


class FacebookPage:
    def __init__(self, page_id, token, client=None):
        self.page_id, self.token, self.client = page_id, token, client or httpx.Client()

    def publish(self, text):
        post = _call(self.client, 'POST', f'{GRAPH}/{self.page_id}/feed', self.token, final=True, message=text)['id']
        return {'id': post, 'url': _permalink(self.client, GRAPH, post, self.token, 'permalink_url')}


class Instagram:
    def __init__(self, user_id, token, client=None, sleep=time.sleep):
        self.user_id, self.token, self.client, self.sleep = user_id, token, client or httpx.Client(), sleep

    def publish(self, caption, image_url):
        container = _call(self.client, 'POST', f'{GRAPH}/{self.user_id}/media', self.token,
                          image_url=image_url, caption=caption)['id']
        _wait_ready(self.client, GRAPH, container, self.token, 'status_code', self.sleep)
        media = _call(self.client, 'POST', f'{GRAPH}/{self.user_id}/media_publish', self.token, final=True,
                      creation_id=container)['id']
        return {'id': media, 'url': _permalink(self.client, GRAPH, media, self.token, 'permalink')}


def refresh_threads_token(token, client=None):
    """Long-lived Threads tokens last 60 days; refreshing returns a new one valid for another 60."""
    client = client or httpx.Client()
    body = _call(client, 'GET', 'https://graph.threads.net/refresh_access_token', token, grant_type='th_refresh_token')
    return body['access_token']


def discover_page(page_token, client=None):
    """A Page token's /me is the Page itself; its linked Instagram professional account comes with it."""
    body = _call(client or httpx.Client(), 'GET', f'{GRAPH}/me', page_token, fields='id,name,instagram_business_account')
    return {'page_id': body['id'], 'instagram_id': (body.get('instagram_business_account') or {}).get('id')}


def discover_threads_user(token, client=None):
    return _call(client or httpx.Client(), 'GET', f'{THREADS}/me', token, fields='id,username')['id']
