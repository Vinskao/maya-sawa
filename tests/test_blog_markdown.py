import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from maya_sawa.api.blog import router, get_blog
from maya_sawa.core.auth.keycloak import require_manage_users
from maya_sawa.services.blog import BlogService
from maya_sawa.services.blog_markdown import parse_markdown
from tests.test_blog import Store

MD = '''---
slug: engineering-log
title: 工程紀錄
description: SSR 與資料管線
category: Engineering
tags: [Astro, TDD]
publishDate: 2026-10-27 09:30:00
---
## 實作

測試先行。
'''


def test_parse_file_or_clipboard_with_taipei_legacy_date_and_bom():
    slug, data = parse_markdown('\ufeff' + MD)
    assert slug == 'engineering-log'
    assert data['publishDate'] == '2026-10-27T01:30:00+00:00'
    assert data['content'] == '## 實作\n\n測試先行。'
    assert data['tags'] == ['Astro', 'TDD']
    assert parse_markdown(MD.replace('slug: engineering-log\n', ''), 'from-file')[0] == 'from-file'


@pytest.mark.parametrize('markdown', ['# No frontmatter', MD.replace('slug: engineering-log', 'slug: ../private'), MD.replace('title: 工程紀錄', 'title: ""'), '---\ntitle: !!python/object/apply:os.system [echo]\n---\nbody'])
def test_rejects_invalid_documents_without_executing_yaml(markdown):
    with pytest.raises(ValueError):
        parse_markdown(markdown)


def test_agent_import_create_update_publish_and_version_conflict():
    service = BlogService(Store())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_blog] = lambda: service
    client = TestClient(app)
    assert client.post('/blog/admin/import', json={'markdown': MD}).status_code == 401
    app.dependency_overrides[require_manage_users] = lambda: {'sub': 'agent:editor'}
    created = client.post('/blog/admin/import', json={'markdown': MD})
    assert created.status_code == 200
    assert service.list() == []
    assert client.post('/blog/admin/import', json={'markdown': MD}).status_code == 409
    assert client.post('/blog/admin/import', json={'markdown': MD, 'operation': 'update'}).status_code == 428
    updated = client.post('/blog/admin/import', json={'markdown': MD.replace('測試先行', '更新正文'), 'operation': 'update', 'publish': True}, headers={'If-Match': created.json()['etag']})
    assert updated.status_code == 200
    assert '更新正文' in service.read('engineering-log')['content']
    assert service.read('engineering-log', admin=True)['indexStatus'] == 'pending'
    stale = client.post('/blog/admin/import', json={'markdown': MD, 'operation': 'update'}, headers={'If-Match': created.json()['etag']})
    assert stale.status_code == 409


def test_multipart_upload_and_selected_slug_guard():
    service = BlogService(Store())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_blog] = lambda: service
    app.dependency_overrides[require_manage_users] = lambda: {'sub': 'editor'}
    client = TestClient(app)
    response = client.post('/blog/admin/upload', files={'file': ('engineering-log.md', MD.encode('utf-8'), 'text/markdown')}, data={'publish': 'true'})
    assert response.status_code == 200
    assert service.read('engineering-log')['title'] == '工程紀錄'
    wrong = client.post('/blog/admin/import', json={'markdown': MD.replace('slug: engineering-log', 'slug: another'), 'operation': 'update', 'slug': 'engineering-log'}, headers={'If-Match': response.json()['etag']})
    assert wrong.status_code == 422
    assert client.post('/blog/admin/upload', files={'file': ('x.md', b'\xff\xfe')}).status_code == 422
    assert client.post('/blog/admin/upload', files={'file': ('x.md', b'x' * 550001)}).status_code == 413
