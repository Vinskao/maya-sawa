"""Real PostgreSQL smoke test in an isolated schema; never targets production article rows."""
import json
import uuid
from types import SimpleNamespace
from sqlalchemy import create_engine, text
from fastapi import FastAPI
from fastapi.testclient import TestClient
from maya_sawa.core.config.config import Config
from maya_sawa.core.auth.keycloak import require_manage_users
from maya_sawa.api.blog import router, get_blog
from maya_sawa.services.blog import BlogService
from maya_sawa.services.blog_postgres import PostgresStore
from maya_sawa.databases.qa_vector_db import QAVectorDatabase
from scripts.import_blog import migrate


def main():
    schema = 'blog_verify_' + uuid.uuid4().hex
    root = create_engine(Config.DB_CONNECTION_STRING)
    with root.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA {schema}'))
    engine = create_engine(Config.DB_CONNECTION_STRING, connect_args={'options': f'-csearch_path={schema},public'})
    try:
        with engine.begin() as conn:
            conn.execute(text('''CREATE TABLE articles (id SERIAL PRIMARY KEY, file_path varchar(500) UNIQUE,
                content TEXT, file_date TIMESTAMP, embedding TEXT, deleted_at TIMESTAMP, updated_at TIMESTAMP)'''))
            conn.execute(text("INSERT INTO articles (id,file_path,content,file_date,embedding,deleted_at) VALUES (218,'existing.md','DB original','2026-01-02',:v,CURRENT_TIMESTAMP)"),
                         {'v': json.dumps([1.0] + [0.0] * 1535)})
        store = PostgresStore(engine)
        store.initialize()
        service = BlogService(store)
        payload = {'title': 'Existing', 'description': 'Metadata', 'category': 'Engineering',
                   'tags': ['PostgreSQL'], 'publishDate': '2026-10-27T00:00:00Z', 'content': 'Older frontend body'}
        result = migrate(service, [{'slug': 'existing', **payload}], publish=True)
        assert result['adopted'] == result['preservedVectors'] == 1
        with engine.connect() as conn:
            row = conn.execute(text('SELECT id,content,embedding IS NOT NULL,deleted_at FROM articles')).one()
            assert row == (218, 'DB original', True, None)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_blog] = lambda: service
        client = TestClient(app)
        assert client.get('/blog/admin/articles').status_code == 401
        app.dependency_overrides[require_manage_users] = lambda: {'sub': 'integration-editor'}
        md = '---\nslug: smoke\ntitle: Smoke\ndescription: PostgreSQL verification\ntags: [TDD]\npublishDate: 2026-10-27T00:00:00Z\n---\n\n## Smoke body'
        created = client.post('/blog/admin/upload', files={'file': ('smoke.md', md)}, data={'publish': 'true'})
        assert created.status_code == 200, created.text
        assert service.process('smoke', lambda slug, snapshot: store.vectorize(slug, snapshot, lambda body: [1.0] + [0.0] * 1535))['indexStatus'] == 'done'
        db = QAVectorDatabase.__new__(QAVectorDatabase)
        db.pool_manager = SimpleNamespace(get_postgres_connection=engine.raw_connection, return_postgres_connection=lambda conn: conn.close())
        db.embedding_service = SimpleNamespace(embed_query=lambda query: [1.0] + [0.0] * 1535)
        assert any(doc.metadata['file_path'] == 'smoke.md' for doc in db.similarity_search('smoke', k=10, threshold=0.7))
        state = service.read('smoke', admin=True)
        client.delete('/blog/admin/articles/smoke', headers={'If-Match': state['etag']})
        assert client.get('/blog/articles/smoke').status_code == 404
        assert all(doc.metadata['file_path'] != 'smoke.md' for doc in db.similarity_search('smoke', k=10, threshold=0.7))
        state = service.read('smoke', admin=True)
        restored = client.post('/blog/admin/articles/smoke/restore', headers={'If-Match': state['etag']})
        assert restored.status_code == 200
        assert client.get('/blog/articles/smoke').status_code == 404
        print(json.dumps({'postgresSmoke': 'passed', 'isolatedSchema': schema, 'checks': ['JSONB', 'adopt-id-body-vector', 'multipart-create', 'auth', 'publish', 'vector-cast-search', 'delete', 'restore']}))
    finally:
        engine.dispose()
        # Only this explicitly-created disposable schema is removed.
        assert schema.startswith('blog_verify_') and len(schema) == 44
        with root.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        root.dispose()


if __name__ == '__main__':
    main()
