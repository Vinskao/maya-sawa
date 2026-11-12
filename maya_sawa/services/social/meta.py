"""Minimal Meta Graph API (Facebook Page, Instagram) and Threads API publishing clients.

Error classes decide what the outbox may do next:
- AuthError: token expired/revoked. Nothing posted; keep the post queued and alert the owner once.
- Rejected: failed before the final publish call. Nothing posted; safe to retry later.
- Ambiguous: the final publish call timed out or returned a server error. The post may be live; never resend automatically.
"""
import json
import time

import httpx

GRAPH = 'https://graph.facebook.com/v23.0'
THREADS = 'https://graph.threads.net/v1.0'
INSTAGRAM_LOGIN = 'https://graph.instagram.com/v23.0'  # Instagram API with Instagram Login: no Facebook Page needed
AUTH_CODES = {102, 190}


class PublishError(Exception):
    pass


class AuthError(PublishError):
    pass


class Rejected(PublishError):
    pass


class Ambiguous(PublishError):
    pass


def _call(client, method, endpoint, token, final=False, **fields):
    params = {**fields, 'access_token': token}
    try:
        response = (client.post(endpoint, data=params, timeout=30) if method == 'POST'
                    else client.get(endpoint, params=params, timeout=30))
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


def _urls(images):
    """One url, a list of urls or nothing, as a list."""
    if not images:
        return []
    return [images] if isinstance(images, str) else list(images)


class Threads:
    MAX_ITEMS = 20

    def __init__(self, user_id, token, client=None, sleep=time.sleep):
        self.user_id, self.token, self.client, self.sleep = user_id, token, client or httpx.Client(), sleep

    def _container(self, **fields):
        container = _call(self.client, 'POST', f'{THREADS}/{self.user_id}/threads', self.token, **fields)['id']
        _wait_ready(self.client, THREADS, container, self.token, 'status', self.sleep)
        return container

    def publish(self, text, images=None):
        images = _urls(images)[:self.MAX_ITEMS]
        if len(images) > 1:  # carousel: item containers first, then one carousel container holding the text
            children = [self._container(media_type='IMAGE', image_url=url, is_carousel_item='true') for url in images]
            container = self._container(media_type='CAROUSEL', children=','.join(children), text=text)
        elif images:
            container = self._container(media_type='IMAGE', image_url=images[0], text=text)
        else:
            container = self._container(media_type='TEXT', text=text)
        media = _call(self.client, 'POST', f'{THREADS}/{self.user_id}/threads_publish', self.token, final=True,
                      creation_id=container)['id']
        return {'id': media, 'url': _permalink(self.client, THREADS, media, self.token, 'permalink')}


class FacebookPage:
    MAX_PHOTOS = 10

    def __init__(self, page_id, token, client=None):
        self.page_id, self.token, self.client = page_id, token, client or httpx.Client()

    def publish(self, text, images=None):
        images = _urls(images)[:self.MAX_PHOTOS]
        if images:  # unpublished photos first (nothing is live), then one feed post attaching them, so it shows under Posts
            photos = [_call(self.client, 'POST', f'{GRAPH}/{self.page_id}/photos', self.token, url=url,
                            published='false')['id'] for url in images]
            attached = {f'attached_media[{index}]': json.dumps({'media_fbid': photo}) for index, photo in enumerate(photos)}
            post = _call(self.client, 'POST', f'{GRAPH}/{self.page_id}/feed', self.token, final=True, message=text,
                         **attached)['id']
        else:
            post = _call(self.client, 'POST', f'{GRAPH}/{self.page_id}/feed', self.token, final=True, message=text)['id']
        return {'id': post, 'url': _permalink(self.client, GRAPH, post, self.token, 'permalink_url')}


class Instagram:
    MAX_ITEMS = 10

    def __init__(self, user_id, token, client=None, sleep=time.sleep, base=GRAPH):
        self.user_id, self.token, self.client, self.sleep = user_id, token, client or httpx.Client(), sleep
        self.base = base

    def _container(self, **fields):
        container = _call(self.client, 'POST', f'{self.base}/{self.user_id}/media', self.token, **fields)['id']
        _wait_ready(self.client, self.base, container, self.token, 'status_code', self.sleep)
        return container

    def publish(self, caption, images):
        images = _urls(images)[:self.MAX_ITEMS]
        if len(images) > 1:
            children = [self._container(image_url=url, is_carousel_item='true') for url in images]
            container = self._container(media_type='CAROUSEL', children=','.join(children), caption=caption)
        else:
            container = self._container(image_url=images[0], caption=caption)
        media = _call(self.client, 'POST', f'{self.base}/{self.user_id}/media_publish', self.token, final=True,
                      creation_id=container)['id']
        return {'id': media, 'url': _permalink(self.client, self.base, media, self.token, 'permalink')}


def refresh_instagram_token(token, client=None):
    """Long-lived Instagram Login tokens last 60 days; refreshing returns a new one valid for another 60."""
    body = _call(client or httpx.Client(), 'GET', 'https://graph.instagram.com/refresh_access_token', token,
                 grant_type='ig_refresh_token')
    return body['access_token']


def discover_instagram_user(token, client=None):
    """The professional account id behind an Instagram Login token."""
    return _call(client or httpx.Client(), 'GET', f'{INSTAGRAM_LOGIN}/me', token, fields='user_id,username')['user_id']


def refresh_threads_token(token, client=None):
    """Long-lived Threads tokens last 60 days; refreshing returns a new one valid for another 60."""
    client = client or httpx.Client()
    body = _call(client, 'GET', 'https://graph.threads.net/refresh_access_token', token, grant_type='th_refresh_token')
    return body['access_token']


PAGE_NAME = 'Birch Investments'


def discover_page(token, client=None, page_id=None):
    """Accept either token kind. A (long-lived) USER token lists its Pages with their own Page tokens under
    /me/accounts; a Page token has no such edge, and its /me is the Page itself. Returns the token to post with."""
    client = client or httpx.Client()
    try:
        pages = _call(client, 'GET', f'{GRAPH}/me/accounts', token,
                      fields='id,name,access_token,instagram_business_account').get('data')
    except AuthError:
        raise
    except Rejected:
        pages = None
    if pages is None:
        body = _call(client, 'GET', f'{GRAPH}/me', token, fields='id,name,instagram_business_account')
        return {'page_id': body['id'], 'instagram_id': (body.get('instagram_business_account') or {}).get('id'),
                'page_token': token}
    page = (next((p for p in pages if page_id and p.get('id') == page_id), None)
            or next((p for p in pages if p.get('name') == PAGE_NAME), None)
            or (pages[0] if len(pages) == 1 else None))
    if not page or not page.get('access_token'):
        raise Rejected('The user token does not manage the Birch Investments Page')
    return {'page_id': page['id'], 'instagram_id': (page.get('instagram_business_account') or {}).get('id'),
            'page_token': page['access_token']}


def discover_threads_user(token, client=None):
    return _call(client or httpx.Client(), 'GET', f'{THREADS}/me', token, fields='id,username')['id']
