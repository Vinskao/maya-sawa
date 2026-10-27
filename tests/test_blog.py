import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from maya_sawa.services.blog import BlogService, Conflict, Missing
from maya_sawa.api.blog import router, get_blog
from maya_sawa.core.auth.keycloak import require_manage_users


class Store:
    def __init__(self):
        self.rows = {}
        self.counter = 0

    def get(self, key):
        if key not in self.rows:
            raise Missing()
        return copy.deepcopy(self.rows[key])

    def put(self, key, value, etag=None):
        if (self.rows.get(key) or (None, None))[1] != etag:
            raise Conflict()
        self.counter += 1
        self.rows[key] = (copy.deepcopy(value), str(self.counter))
        return str(self.counter)

    def keys(self, prefix):
        return [key for key in self.rows if key.startswith(prefix)]


@pytest.fixture
def service():
    return BlogService(Store())


def data(content='SSR 與圖表', title='工程紀錄'):
    return dict(title=title, description='開發摘要', content=content, category='Engineering',
                tags=['Astro', 'TDD'], publishDate='2026-10-27T00:00:00Z')


def test_draft_publish_edit_unpublish_restore(service):
    draft = service.save('engineering', data(), None, 'editor')
    assert service.list() == []
    with pytest.raises(Missing):
        service.read('engineering')
    live = service.action('engineering', 'publish', draft['etag'], 'editor')
    assert service.read('engineering')['content'] == 'SSR 與圖表'
    edited = service.save('engineering', data('新的草稿'), live['etag'], 'editor')
    assert service.read('engineering')['content'] == 'SSR 與圖表'
    deleted = service.action('engineering', 'delete', edited['etag'], 'editor')
    assert service.list() == []
    restored = service.action('engineering', 'restore', deleted['etag'], 'editor')
    assert service.list() == []  # restore never implicitly republishes
    service.action('engineering', 'publish', restored['etag'], 'editor')
    assert service.read('engineering')['content'] == '新的草稿'


def test_stale_editor_cannot_overwrite_and_revisions_are_immutable(service):
    first = service.save('engineering', data(), None, 'a')
    second = service.save('engineering', data('v2'), first['etag'], 'b')
    with pytest.raises(Conflict):
        service.save('engineering', data('lost update'), first['etag'], 'a')
    assert service.revision('engineering', first['revision'])['content'] == 'SSR 與圖表'
    assert service.read('engineering', admin=True)['draft']['content'] == 'v2'


def test_publish_event_is_durable_retryable_and_only_indexes_public_content(service):
    first = service.save('engineering', data(), None, 'a')
    service.action('engineering', 'publish', first['etag'], 'a')
    calls = []
    def fail(slug, snapshot):
        raise RuntimeError('private infrastructure detail')
    assert service.process('engineering', fail)['indexStatus'] == 'failed'
    assert service.read('engineering')['title'] == '工程紀錄'
    result = service.process('engineering', lambda slug, snapshot: calls.append((slug, snapshot)))
    assert result['indexStatus'] == 'done'
    service.process('engineering', lambda *args: calls.append(args))
    assert len(calls) == 1
    state = service.read('engineering', admin=True)
    service.action('engineering', 'unpublish', state['etag'], 'a')
    service.process('engineering', lambda slug, snapshot: calls.append((slug, snapshot)))
    assert calls[-1] == ('engineering', None)


def test_api_permissions_validation_and_public_response(service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_blog] = lambda: service
    client = TestClient(app)
    assert client.post('/blog/admin/articles/engineering', json=data()).status_code == 401
    assert client.get('/blog/admin/articles').status_code == 401
    app.dependency_overrides[require_manage_users] = lambda: {'sub': 'editor'}
    assert client.post('/blog/admin/articles/engineering', json=data()).status_code == 201
    assert client.post('/blog/admin/articles/engineering', json=data()).status_code == 409
    assert client.put('/blog/admin/articles/engineering', json=data()).status_code == 428
    assert client.post('/blog/admin/articles/bad.slug', json=data()).status_code == 422
    assert client.post('/blog/admin/articles/empty', json=data(' ')).status_code == 422
    row = client.get('/blog/admin/articles/engineering').json()
    response = client.post('/blog/admin/articles/engineering/publish', headers={'If-Match': row['etag']})
    assert response.status_code == 200
    public = client.get('/blog/articles/engineering').json()
    assert public['title'] == '工程紀錄'
    assert not {'draft', 'editor', 'etag', 'indexStatus'} & public.keys()
    assert 'content' not in client.get('/blog/articles').json()[0]


def test_api_forbids_logged_in_non_admin(monkeypatch, service):
    from maya_sawa.core.auth import keycloak
    monkeypatch.setattr(keycloak, '_verify_rs256', lambda token: {'sub': 'reader'})
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_blog] = lambda: service
    response = TestClient(app).post('/blog/admin/articles/test', json=data(), headers={'Authorization': 'Bearer reader'})
    assert response.status_code == 403


def test_active_index_lease_blocks_concurrent_editor_and_recovers_after_timeout(service):
    first = service.save('engineering', data(), None, 'a')
    first = service.action('engineering', 'publish', first['etag'], 'a')
    def indexing(slug, snapshot):
        current = service.read(slug, admin=True)
        with pytest.raises(Conflict):
            service.save(slug, data('race'), current['etag'], 'b')
        with pytest.raises(Conflict):
            service.process(slug, lambda *args: None)
    assert service.process('engineering', indexing)['indexStatus'] == 'done'


def test_pending_events_are_processed_after_restart(service):
    from maya_sawa.services.blog_worker import drain
    first = service.save('engineering', data(), None, 'a')
    service.action('engineering', 'publish', first['etag'], 'a')
    calls = []
    assert drain(BlogService(service.store), lambda *args: calls.append(args)) == 1
    assert drain(BlogService(service.store), lambda *args: calls.append(args)) == 0
    assert len(calls) == 1


def test_restore_only_accepts_deleted_and_republishing_same_revision_is_idempotent(service):
    first = service.save('engineering', data(), None, 'a')
    with pytest.raises(Conflict):
        service.action('engineering', 'restore', first['etag'], 'a')
    live = service.action('engineering', 'publish', first['etag'], 'a')
    done = service.process('engineering', lambda *args: None)
    again = service.action('engineering', 'publish', done['etag'], 'a')
    assert again['indexStatus'] == 'done'
    assert again['event'] == live['event']
