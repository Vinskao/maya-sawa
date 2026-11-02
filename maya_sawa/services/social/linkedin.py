"""LinkedIn personal-profile posting via "Share on LinkedIn" (scope w_member_social): text, or text plus images.

Same error classes as meta.py: AuthError (401, token expired: nothing posted), Rejected (failed before the final post
call: safe to retry), Ambiguous (the post call timed out or returned 5xx: it may be live, never resend)."""
import httpx

from .meta import Ambiguous, AuthError, Rejected

API = 'https://api.linkedin.com'
HEADERS = {'X-Restli-Protocol-Version': '2.0.0'}


def _check(response, final=False):
    if response.status_code < 400:
        return response
    if response.status_code == 401:
        raise AuthError('LinkedIn token expired or revoked')
    if final and response.status_code >= 500:
        raise Ambiguous(f'HTTP {response.status_code}')
    raise Rejected(f'HTTP {response.status_code}')


class LinkedIn:
    def __init__(self, author, token, client=None):
        self.author, self.token, self.client = author, token, client or httpx.Client()

    def _headers(self):
        return {'Authorization': f'Bearer {self.token}', **HEADERS}

    def _send(self, method, url, final=False, **kwargs):
        try:
            return _check(self.client.request(method, url, headers=self._headers(), timeout=60, **kwargs), final)
        except httpx.HTTPError as exc:
            raise (Ambiguous if final else Rejected)(type(exc).__name__) from exc

    def _upload(self, image_url):
        try:
            image = self.client.get(image_url, timeout=30)
            image.raise_for_status()
        except httpx.HTTPError as exc:
            raise Rejected(f'image fetch failed: {type(exc).__name__}') from exc
        registered = self._send('POST', f'{API}/v2/assets', params={'action': 'registerUpload'}, json={
            'registerUploadRequest': {'recipes': ['urn:li:digitalmediaRecipe:feedshare-image'], 'owner': self.author,
                                      'serviceRelationships': [{'relationshipType': 'OWNER',
                                                                'identifier': 'urn:li:userGeneratedContent'}]}}).json()['value']
        target = registered['uploadMechanism']['com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest']['uploadUrl']
        self._send('POST', target, content=image.content)
        return registered['asset']

    def publish(self, text, image_urls=()):
        assets = [self._upload(url) for url in image_urls]
        content = {'shareCommentary': {'text': text}, 'shareMediaCategory': 'IMAGE' if assets else 'NONE'}
        if assets:
            content['media'] = [{'status': 'READY', 'media': asset} for asset in assets]
        response = self._send('POST', f'{API}/v2/ugcPosts', final=True, json={
            'author': self.author, 'lifecycleState': 'PUBLISHED',
            'specificContent': {'com.linkedin.ugc.ShareContent': content},
            'visibility': {'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'}})
        urn = response.headers.get('X-RestLi-Id') or response.json().get('id')
        return {'id': urn, 'url': f'https://www.linkedin.com/feed/update/{urn}/'}


def discover_person(token, client=None):
    """The member URN for the token (needs the openid/profile scopes: "Sign In with LinkedIn using OpenID Connect")."""
    response = _check((client or httpx.Client()).get(f'{API}/v2/userinfo', headers={'Authorization': f'Bearer {token}'},
                                                      timeout=30))
    return f"urn:li:person:{response.json()['sub']}"
