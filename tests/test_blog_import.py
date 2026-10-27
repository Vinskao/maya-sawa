from pathlib import Path
from scripts.import_blog import load_articles, migrate
from tests.test_blog import Store
from maya_sawa.services.blog import BlogService


def test_real_archive_preserves_all_slugs_and_dates_and_new_article():
    rows = load_articles(Path('docs/blog-import'))
    assert len(rows) == 68
    old = next(row for row in rows if row['slug'] == 'react-hydration')
    assert old['publishDate'] == '2026-01-02T05:00:00+00:00'
    assert 'Hydration' in old['content']
    newest = next(row for row in rows if row['slug'] == 'engineering-market-lab-2026-10')
    assert 'Astro' in newest['tags']
    assert '尚未設定' in newest['content']


def test_migration_is_repeatable_and_never_overwrites_editor_changes():
    service = BlogService(Store())
    rows = load_articles(Path('docs/blog-import'))[:2]
    assert migrate(service, rows, publish=True)['created'] == 2
    assert migrate(service, rows, publish=True)['unchanged'] == 2
    slug = rows[0]['slug']
    state = service.read(slug, admin=True)
    service.save(slug, {**state['draft'], 'content': '人工編輯'}, state['etag'], 'human')
    assert migrate(service, rows, publish=True)['protected'] == 1
    assert service.read(slug, admin=True)['draft']['content'] == '人工編輯'
