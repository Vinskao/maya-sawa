"""LinkedIn personal-profile posting (Share on LinkedIn: w_member_social). Response shapes follow LinkedIn's docs."""
import httpx
import pytest

from maya_sawa.services.social.meta import Ambiguous, AuthError, Rejected
from maya_sawa.services.social.linkedin import LinkedIn, discover_person

REGISTER = {'value': {'uploadMechanism': {'com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest':
                                           {'uploadUrl': 'https://api.linkedin.com/mediaUpload/ABC/0'}},
                      'asset': 'urn:li:digitalmediaAsset:C55'}}


def transport(calls, post_status=201, upload_status=201, error=None):
    def handler(request):
        calls.append((request.method, request.url.path, request.headers, request.content))
        key = f'{request.method} {request.url.path}'
        if request.url.host == 'tymultiverse.cc':
            return httpx.Response(200, content=b'PNGDATA', headers={'content-type': 'image/png'})
        if error:
            raise error
        if key == 'POST /v2/assets':
            return httpx.Response(200, json=REGISTER)
        if key == 'POST /mediaUpload/ABC/0':
            return httpx.Response(upload_status)
        if key == 'POST /v2/ugcPosts':
            return httpx.Response(post_status, json={'id': 'urn:li:share:7'} if post_status < 400 else {'message': 'x'},
                                  headers={'X-RestLi-Id': 'urn:li:share:7'} if post_status < 400 else {})
        raise AssertionError(key)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_text_only_post_goes_to_ugc_posts_as_the_member_with_public_visibility():
    calls = []
    result = LinkedIn('urn:li:person:42', 'tok', transport(calls)).publish('hello')
    assert result == {'id': 'urn:li:share:7', 'url': 'https://www.linkedin.com/feed/update/urn:li:share:7/'}
    method, path, headers, body = calls[0]
    assert (method, path) == ('POST', '/v2/ugcPosts')
    assert headers['authorization'] == 'Bearer tok' and headers['x-restli-protocol-version'] == '2.0.0'
    import json
    data = json.loads(body)
    assert data['author'] == 'urn:li:person:42' and data['lifecycleState'] == 'PUBLISHED'
    content = data['specificContent']['com.linkedin.ugc.ShareContent']
    assert content['shareCommentary']['text'] == 'hello' and content['shareMediaCategory'] == 'NONE'
    assert data['visibility'] == {'com.linkedin.ugc.MemberNetworkVisibility': 'PUBLIC'}


def test_images_are_registered_uploaded_then_attached():
    calls = []
    LinkedIn('urn:li:person:42', 'tok', transport(calls)).publish('hello', ['https://tymultiverse.cc/card.png'])
    order = [(c[0], c[1]) for c in calls]
    assert order == [('GET', '/card.png'), ('POST', '/v2/assets'), ('POST', '/mediaUpload/ABC/0'), ('POST', '/v2/ugcPosts')]
    assert calls[2][3] == b'PNGDATA'
    import json
    content = json.loads(calls[3][3])['specificContent']['com.linkedin.ugc.ShareContent']
    assert content['shareMediaCategory'] == 'IMAGE'
    assert content['media'] == [{'status': 'READY', 'media': 'urn:li:digitalmediaAsset:C55'}]


def test_expired_token_is_an_auth_error_server_errors_on_the_final_call_are_ambiguous():
    with pytest.raises(AuthError):
        LinkedIn('urn:li:person:42', 'tok', transport([], post_status=401)).publish('x')
    with pytest.raises(Ambiguous):
        LinkedIn('urn:li:person:42', 'tok', transport([], post_status=500)).publish('x')
    with pytest.raises(Ambiguous):
        LinkedIn('urn:li:person:42', 'tok', transport([], error=httpx.ReadTimeout('slow'))).publish('x')
    with pytest.raises(Rejected):  # a failed image upload happens before the post: safe to retry
        LinkedIn('urn:li:person:42', 'tok', transport([], upload_status=400)).publish('x', ['https://tymultiverse.cc/c.png'])


def test_person_urn_comes_from_the_openid_userinfo_subject():
    def handler(request):
        assert request.url.path == '/v2/userinfo' and request.headers['authorization'] == 'Bearer tok'
        return httpx.Response(200, json={'sub': 'abc123', 'name': 'Tianyi Kao'})
    assert discover_person('tok', httpx.Client(transport=httpx.MockTransport(handler))) == 'urn:li:person:abc123'
