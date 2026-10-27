"""Public published snapshots and role-protected editorial CRUD."""
import os
from functools import lru_cache
from typing import Annotated, Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Path, UploadFile, File, Form
from pydantic import BaseModel, Field, field_validator
from datetime import datetime, timezone
from ..core.auth.keycloak import require_manage_users
from ..services.blog_postgres import get_postgres_store
from ..services.blog import BlogService, Missing, Conflict, Unavailable, index_article
from ..services.blog_markdown import parse_markdown
from ..services import blog_weekly

router = APIRouter(prefix='/blog', tags=['Blog'])
Slug = Annotated[str, Path(pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$', max_length=120)]


@lru_cache
def get_blog():
    if os.getenv('BLOG_ENABLED', 'false').lower() != 'true':
        raise HTTPException(503, 'Blog storage is not configured')
    try:
        return BlogService(get_postgres_store())
    except Exception:
        raise HTTPException(503, 'Blog storage is unavailable')


class Draft(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=500000)
    category: str = Field(default='Engineering', max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=20)
    publishDate: datetime

    @field_validator('title', 'description', 'content')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Must not be blank')
        return value

    @field_validator('publishDate')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('Timezone required')
        return value.astimezone(timezone.utc)

    @field_validator('tags')
    @classmethod
    def valid_tags(cls, values):
        if any(not value.strip() or len(value) > 80 for value in values):
            raise ValueError('Invalid tag')
        return list(dict.fromkeys(values))


def run(call):
    try:
        return call()
    except Missing:
        raise HTTPException(404, 'Article not found')
    except Conflict:
        raise HTTPException(409, 'Article changed or is processing; reload and retry')
    except Unavailable:
        raise HTTPException(503, 'Blog storage is unavailable')


def match(value):
    if not value:
        raise HTTPException(428, 'If-Match is required')
    return value


class MarkdownImport(BaseModel):
    markdown: str = Field(min_length=1, max_length=550000)
    slug: str | None = None
    operation: Literal['create', 'update'] = 'create'
    publish: bool = False


@router.post('/weekly/import')
def weekly_import(payload: MarkdownImport, claims=Depends(blog_weekly.require_weekly_agent), service=Depends(get_blog)):
    try:
        slug, draft = parse_markdown(payload.markdown, payload.slug)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if payload.operation != 'create' or slug != blog_weekly.weekly_slug() or draft['category'] != 'Engineering':
        raise HTTPException(422, 'Weekly writer can only create this week’s Engineering article')
    return import_markdown(payload, None, claims, service)


@router.get('/weekly/articles/{slug}')
def weekly_status(slug: Slug, claims=Depends(blog_weekly.require_weekly_agent), service=Depends(get_blog)):
    if not slug.startswith('weekly-tech-'):
        raise HTTPException(404, 'Article not found')
    state = run(lambda: service.read(slug, admin=True))
    if state['editor'] != claims['sub']:
        raise HTTPException(404, 'Article not found')
    return state


def import_markdown(payload, expected, claims, service):
    try:
        slug, draft = parse_markdown(payload.markdown, payload.slug)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if payload.operation == 'update' and payload.slug and slug != payload.slug:
        raise HTTPException(422, 'Markdown slug must match the selected article')
    etag = match(expected) if payload.operation == 'update' else None
    state = run(lambda: service.save(slug, draft, etag, claims['sub']))
    if payload.publish:
        state = run(lambda: service.action(slug, 'publish', state['etag'], claims['sub']))
    return state


@router.post('/admin/import')
def import_article(payload: MarkdownImport, if_match: str | None = Header(default=None),
                   claims=Depends(require_manage_users), service=Depends(get_blog)):
    return import_markdown(payload, if_match, claims, service)


@router.post('/admin/upload')
def upload_article(file: UploadFile = File(...), operation: Literal['create', 'update'] = Form('create'),
                   publish: bool = Form(False), if_match: str | None = Header(default=None),
                   claims=Depends(require_manage_users), service=Depends(get_blog)):
    if not file.filename or not file.filename.lower().endswith('.md'):
        raise HTTPException(422, 'Upload a UTF-8 .md file')
    content = file.file.read(550001)
    if len(content) > 550000:
        raise HTTPException(413, 'Markdown file exceeds the size limit')
    try:
        markdown = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise HTTPException(422, 'Markdown must use UTF-8')
    fallback = file.filename.replace('\\', '/').rsplit('/', 1)[-1][:-3]
    return import_markdown(MarkdownImport(markdown=markdown, slug=fallback, operation=operation, publish=publish),
                           if_match, claims, service)


@router.get('/articles')
def articles(service=Depends(get_blog)):
    return run(lambda: service.list())


@router.get('/articles/{slug}')
def article(slug: Slug, service=Depends(get_blog)):
    return run(lambda: service.read(slug))


@router.get('/admin/articles', dependencies=[Depends(require_manage_users)])
def admin_articles(service=Depends(get_blog)):
    return run(lambda: service.list(admin=True))


@router.get('/admin/articles/{slug}', dependencies=[Depends(require_manage_users)])
def admin_article(slug: Slug, service=Depends(get_blog)):
    return run(lambda: service.read(slug, admin=True))


@router.post('/admin/articles/{slug}', status_code=201)
def create(slug: Slug, draft: Draft, claims=Depends(require_manage_users), service=Depends(get_blog)):
    return run(lambda: service.save(slug, draft.model_dump(mode='json'), None, claims['sub']))


@router.put('/admin/articles/{slug}')
def update(slug: Slug, draft: Draft, if_match: str | None = Header(default=None),
           claims=Depends(require_manage_users), service=Depends(get_blog)):
    expected = match(if_match)
    return run(lambda: service.save(slug, draft.model_dump(mode='json'), expected, claims['sub']))


@router.delete('/admin/articles/{slug}')
def delete(slug: Slug, if_match: str | None = Header(default=None),
           claims=Depends(require_manage_users), service=Depends(get_blog)):
    expected = match(if_match)
    return run(lambda: service.action(slug, 'delete', expected, claims['sub']))


@router.post('/admin/articles/{slug}/trigger', dependencies=[Depends(require_manage_users)])
def trigger(slug: Slug, service=Depends(get_blog)):
    return run(lambda: service.process(slug, index_article))


@router.post('/admin/articles/{slug}/{action}')
def action(slug: Slug, action: Literal['publish', 'unpublish', 'restore'],
           if_match: str | None = Header(default=None), claims=Depends(require_manage_users), service=Depends(get_blog)):
    expected = match(if_match)
    return run(lambda: service.action(slug, action, expected, claims['sub']))


@router.get('/admin/articles/{slug}/revisions/{revision}', dependencies=[Depends(require_manage_users)])
def revision(slug: Slug, revision: Annotated[str, Path(pattern=r'^[a-f0-9]{32}$')], service=Depends(get_blog)):
    return run(lambda: service.revision(slug, revision))
