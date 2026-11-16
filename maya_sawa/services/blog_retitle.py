"""Give /work articles descriptive titles and summaries so people and AI search can find them (docs/BLOG_WORKFLOW.md, 2026-11-16).

Many early articles were imported with the file name as the title (`redis`, `r2dbc`) and a date or an English line as the summary.
`data/blog_titles.json` maps slug -> [title, description], written from each article's own text. The sync goes through the same
BlogService.save + publish the import API uses and only touches an article whose title is still its slug or a bare date, so a title someone has
already edited by hand is never overwritten; running it again does nothing.
"""
import json
import logging
import re
from pathlib import Path

from .blog import Conflict, Missing

logger = logging.getLogger(__name__)
EDITOR = 'blog-retitle'
TITLES = Path(__file__).resolve().parent.parent / 'data' / 'blog_titles.json'


def load_titles(path: Path = TITLES) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def placeholder(title, slug: str) -> bool:
    """A title nobody wrote: the slug itself or just a date (some imports used the publish date)."""
    title = (title or '').strip().lower()
    return not title or title == slug or bool(re.fullmatch(r'[\d/:. -]+', title))


def retitle(slug: str, title: str, description: str, service) -> str:
    """'updated', 'skipped' (already titled / missing) or 'conflict' (article busy or changed; retried on the next start)."""
    try:
        state = service.read(slug, admin=True)
    except Missing:
        return 'skipped'
    draft = state['draft']
    if not placeholder(draft.get('title'), slug):
        return 'skipped'
    try:
        saved = service.save(slug, {**draft, 'title': title, 'description': description}, state['etag'], EDITOR)
        if state.get('published'):
            service.action(slug, 'publish', saved['etag'], EDITOR)
    except Conflict:
        return 'conflict'
    return 'updated'


def sync_titles(service, titles: dict | None = None) -> dict:
    counts = {'updated': 0, 'skipped': 0, 'conflict': 0, 'failed': 0}
    for slug, (title, description) in (titles or load_titles()).items():
        try:
            counts[retitle(slug, title, description, service)] += 1
        except Exception:
            counts['failed'] += 1
            logger.exception('Could not retitle blog article %s', slug)
    return counts
