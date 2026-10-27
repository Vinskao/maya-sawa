import pytest
from sqlalchemy import create_engine, text
from maya_sawa.services.blog import BlogService, Conflict
from maya_sawa.services.blog_postgres import PostgresStore
from tests.test_blog import data


@pytest.fixture
def store():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE articles (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT UNIQUE, content TEXT, file_date TEXT, embedding TEXT, deleted_at TEXT, updated_at TEXT)'))
    store = PostgresStore(engine)
    store.initialize()
    return store


def test_db_publish_is_atomic_with_qa_body_and_stale_vector_invalidation(store):
    service = BlogService(store)
    first = service.save('engineering', data(), None, 'a')
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM articles')).scalar() == 0
    live = service.action('engineering', 'publish', first['etag'], 'a')
    with store.engine.begin() as conn:
        assert conn.execute(text('SELECT content FROM articles')).scalar() == 'SSR 與圖表'
        conn.execute(text("UPDATE articles SET embedding='[1,2]'"))
    edited = service.save('engineering', data('修訂正文'), live['etag'], 'b')
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT embedding FROM articles')).scalar() == '[1,2]'
    live = service.action('engineering', 'publish', edited['etag'], 'b')
    with store.engine.connect() as conn:
        row = conn.execute(text('SELECT content, embedding FROM articles')).one()
        assert row == ('修訂正文', None)
    removed = service.action('engineering', 'delete', live['etag'], 'b')
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT count(*) FROM articles')).scalar() == 0
    restored = service.action('engineering', 'restore', removed['etag'], 'b')
    service.action('engineering', 'publish', restored['etag'], 'b')
    assert service.read('engineering')['content'] == '修訂正文'


def test_db_cas_and_immutable_revisions(store):
    service = BlogService(store)
    first = service.save('engineering', data(), None, 'a')
    second = service.save('engineering', data('v2'), first['etag'], 'b')
    with pytest.raises(Conflict):
        service.save('engineering', data('lost'), first['etag'], 'a')
    assert service.revision('engineering', first['revision'])['content'] == 'SSR 與圖表'
    assert service.read('engineering', admin=True)['etag'] == second['etag']


def test_db_published_revision_and_projection_roll_back_together(store):
    service = BlogService(store)
    first = service.save('engineering', data(), None, 'a')
    with store.engine.begin() as conn:
        conn.execute(text('DROP TABLE articles'))
    with pytest.raises(Exception):
        service.action('engineering', 'publish', first['etag'], 'a')
    assert service.read('engineering', admin=True)['published'] is None


def test_vector_worker_writes_qa_vector_and_skips_stale_revision(store):
    service = BlogService(store)
    first = service.save('engineering', data(), None, 'a')
    live = service.action('engineering', 'publish', first['etag'], 'a')
    snapshot = service.read('engineering')
    assert store.vectorize('engineering', snapshot, lambda content: [1.0, 2.0])
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT embedding FROM articles')).scalar() == '[1.0, 2.0]'
    edited = service.save('engineering', data('v2'), live['etag'], 'a')
    service.action('engineering', 'publish', edited['etag'], 'a')
    assert not store.vectorize('engineering', snapshot, lambda content: [9.0, 9.0])
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT embedding FROM articles')).scalar() is None


def test_adopts_legacy_database_body_id_and_vector_without_rewriting(store):
    from scripts.import_blog import migrate
    with store.engine.begin() as conn:
        conn.execute(text("INSERT INTO articles (id,file_path,content,file_date,embedding,deleted_at) VALUES (218,'engineering.md','DB edited body','2026-01-02','[1,2]','2026-10-26')"))
    result = migrate(BlogService(store), [{'slug': 'engineering', **data('older frontend body')}], publish=True)
    assert result['adopted'] == 1
    assert result['preservedVectors'] == 1
    assert BlogService(store).read('engineering')['content'] == 'DB edited body'
    with store.engine.connect() as conn:
        row = conn.execute(text('SELECT id,content,embedding,deleted_at FROM articles')).one()
        assert row == (218, 'DB edited body', '[1,2]', None)
    state = BlogService(store).read('engineering', admin=True)
    assert state['indexStatus'] == 'done'
    assert migrate(BlogService(store), [{'slug': 'engineering', **data('older frontend body')}], publish=True)['protected'] == 1


def test_missing_vector_is_queued_but_metadata_only_edit_keeps_existing_vector(store):
    from scripts.import_blog import migrate
    with store.engine.begin() as conn:
        conn.execute(text("INSERT INTO articles (id,file_path,content,file_date) VALUES (10,'engineering.md','SSR 與圖表','2026-01-02')"))
    migrate(BlogService(store), [{'slug': 'engineering', **data()}], publish=True)
    service = BlogService(store)
    assert service.read('engineering', admin=True)['indexStatus'] == 'pending'
    service.process('engineering', lambda slug, snapshot: store.vectorize(slug, snapshot, lambda content: [1, 2]))
    state = service.read('engineering', admin=True)
    edited = service.save('engineering', data(title='Metadata only'), state['etag'], 'editor')
    published = service.action('engineering', 'publish', edited['etag'], 'editor')
    assert published['indexStatus'] == 'done'
    with store.engine.connect() as conn:
        assert conn.execute(text('SELECT id,embedding FROM articles')).one() == (10, '[1, 2]')
