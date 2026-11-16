"""Approved daily readings -> /blog articles (docs/DAILY_MAYA_BRIEF.md, 2026-11-16).

The audio is on /learn; this puts the same piece in writing on /blog through the blog service's own save + publish (the path
POST /blog/admin/import uses). Pure text building here, no AI: the approved `reading` (reader layout) is the body, falling back
to the spoken `content`. One article per day, slug `daily-reading-YYYY-MM-DD`, so running it again never duplicates.
"""
import logging
import re

from .blog import Missing

logger = logging.getLogger(__name__)
EDITOR = 'daily-maya'
CATEGORY = 'Market'
TAGS = ['Quant Finance', 'Daily Reading']


def slug_for(day: str) -> str:
    return f'daily-reading-{day}'


def _description(text: str) -> str:
    plain = re.sub(r'[#*`>\[\]]', '', text)
    plain = re.sub(r'\s+', ' ', plain).strip()
    first = re.split(r'(?<=[。！？])', plain, maxsplit=1)[0] or plain
    return (first if 20 <= len(first) <= 200 else plain[:150]) or '每日市場精讀'


def _body(row: dict) -> str:
    text = (row.get('reading') or '').strip()
    if not text:
        # Spoken transcript has no layout: one paragraph per blank-line block, else split after full stops.
        text = (row.get('content') or '').strip()
        if '\n' not in text:
            text = re.sub(r'(?<=。)(?=.)', '\n\n', text)
    sources = [s for s in row.get('sources') or []]
    links = [f'- <{s}>' if s.startswith('http') else f'- {s}' for s in sources]
    return text + ('\n\n## 資料來源\n\n' + '\n'.join(links) if links else '')


def to_draft(row: dict) -> dict:
    day = row['day']
    title = (row.get('title') or f'每日市場精讀｜{day.replace("-", "/")}').strip()
    body = _body(row)
    return {'title': title, 'description': _description(row.get('reading') or row.get('content') or ''), 'content': body,
            'category': CATEGORY, 'tags': list(TAGS), 'publishDate': f'{day}T09:00:00+08:00'}


def publish_to_blog(row: dict, service) -> str:
    """Create and publish the day's article; returns 'created' or 'exists'. Raises on storage errors (caller logs)."""
    slug = slug_for(row['day'])
    try:
        service.read(slug, admin=True)
        return 'exists'
    except Missing:
        pass
    from datetime import datetime
    from ..api.blog import Draft
    raw = to_draft(row)
    checked = Draft(**{**raw, 'publishDate': datetime.fromisoformat(raw['publishDate'])})
    draft = {**checked.model_dump(mode='json'), 'publishDate': checked.publishDate.isoformat()}
    state = service.save(slug, draft, None, EDITOR)
    service.action(slug, 'publish', state['etag'], EDITOR)
    return 'created'


def sync_published(rows: list, service) -> dict:
    """Backfill: every approved reading that is not on /blog yet. One bad row never stops the rest."""
    counts = {'created': 0, 'exists': 0, 'failed': 0}
    for row in rows:
        try:
            counts[publish_to_blog(row, service)] += 1
        except Exception:
            counts['failed'] += 1
            logger.exception('Daily reading %s could not be put on the blog', row.get('day'))
    return counts
