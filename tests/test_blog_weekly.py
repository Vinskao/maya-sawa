import hashlib
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.testclient import TestClient
from maya_sawa.api.blog import router, get_blog
from maya_sawa.services.blog import BlogService
from maya_sawa.services.blog_weekly import weekly_slug
from tests.test_blog import Store


def test_week_number_uses_taipei_and_iso_year():
    assert weekly_slug(datetime(2027,1,1,tzinfo=timezone.utc)) == 'weekly-tech-2026-w53'
    assert weekly_slug(datetime(2026,10,25,17,tzinfo=timezone.utc)) == 'weekly-tech-2026-w44'


def test_weekly_key_can_only_create_this_weeks_article_and_read_its_own_status(monkeypatch):
    monkeypatch.setenv('BLOG_WEEKLY_AGENT_KEY_SHA256', hashlib.sha256(b'unit-only-weekly-key').hexdigest())
    monkeypatch.setattr('maya_sawa.services.blog_weekly.weekly_slug', lambda: 'weekly-tech-2026-w44')
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_blog] = lambda: BlogService(Store())
    service = BlogService(Store())
    app.dependency_overrides[get_blog] = lambda: service
    client = TestClient(app)
    markdown = '---\nslug: weekly-tech-2026-w44\ntitle: Weekly deep dive\ndescription: Evidence based\ncategory: Engineering\ntags: [PostgreSQL]\npublishDate: 2026-10-27T00:00:00Z\n---\n\n## Mechanism'
    headers = {'X-Blog-Agent-Key':'unit-only-weekly-key'}
    assert client.post('/blog/weekly/import', json={'markdown':markdown}).status_code == 401
    assert client.post('/blog/weekly/import', json={'markdown':markdown}, headers={'X-Blog-Agent-Key':'bad'}).status_code == 403
    assert client.post('/blog/weekly/import', json={'markdown':markdown.replace('weekly-tech-2026-w44','arbitrary')}, headers=headers).status_code == 422
    created = client.post('/blog/weekly/import', json={'markdown':markdown,'publish':True}, headers=headers)
    assert created.status_code == 200
    assert service.read('weekly-tech-2026-w44')['title'] == 'Weekly deep dive'
    assert client.post('/blog/weekly/import', json={'markdown':markdown,'publish':True}, headers=headers).status_code == 409
    assert client.post('/blog/weekly/import', json={'markdown':markdown,'operation':'update'}, headers=headers).status_code == 422
    assert client.get('/blog/weekly/articles/weekly-tech-2026-w44', headers=headers).status_code == 200
    assert client.get('/blog/weekly/articles/arbitrary', headers=headers).status_code == 404
    assert client.get('/blog/admin/articles', headers=headers).status_code == 401
    assert client.delete('/blog/admin/articles/weekly-tech-2026-w44', headers=headers).status_code == 401
