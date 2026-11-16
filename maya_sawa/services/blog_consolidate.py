"""Merge overlapping /work articles and remove empty ones (docs/BLOG_WORKFLOW.md, 2026-11-16).

`data/blog_consolidation.json` lists articles to delete and groups to merge (`into` keeps its URL, each `from` is folded in).
Merging is mechanical, no AI rewriting: the absorbed article's body is appended to the target under its own heading with its
headings pushed one level down, then the absorbed article goes to the blog's recoverable bin (action `delete`, restorable).
Running again does nothing: an absorbed article that is already gone is skipped, and a body already inside the target is never
appended twice.
"""
import json
import logging
import re
from pathlib import Path

from .blog import Conflict, Missing

logger = logging.getLogger(__name__)
EDITOR = 'blog-consolidate'
PLAN = Path(__file__).resolve().parent.parent / 'data' / 'blog_consolidation.json'


def load_plan(path: Path = PLAN) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def demote(markdown: str) -> str:
    """Push every heading one level down (outside code fences) and drop a leading H1 that repeats the article title."""
    lines, out, fenced = markdown.strip().split('\n'), [], False
    if lines and re.match(r'^# ', lines[0]):
        lines = lines[1:]
    for line in lines:
        if re.match(r'^\s*(```|~~~)', line):
            fenced = not fenced
        elif not fenced and re.match(r'^#{1,5} ', line):
            line = '#' + line
        out.append(line)
    return '\n'.join(out).strip()


def _live(service, slug):
    """The article's admin state, or None when it is missing or already in the bin."""
    try:
        state = service.read(slug, admin=True)
    except Missing:
        return None
    return None if state.get('deleted') else state


def _section_title(state) -> str:
    return re.sub(r'[#*`\[\]]', '', state['draft']['title']).strip()


def merge_group(group: dict, service) -> dict:
    counts = {'merged': 0, 'skipped': 0}
    target = _live(service, group['into'])
    if target is None:
        counts['skipped'] += len(group['from'])
        return counts
    for slug in group['from']:
        source = _live(service, slug)
        if source is None:
            counts['skipped'] += 1
            continue
        body = demote(source['draft']['content'])
        draft = dict(target['draft'])
        if body and body[:200] not in draft['content']:
            draft['content'] = f"{draft['content'].rstrip()}\n\n## {_section_title(source)}\n\n{body}\n"
        draft.update(title=group['title'], description=group['description'])
        saved = service.save(group['into'], draft, target['etag'], EDITOR)
        if target.get('published'):
            saved = service.action(group['into'], 'publish', saved['etag'], EDITOR)
        service.action(slug, 'delete', source['etag'], EDITOR)
        target = {**target, 'draft': draft, 'etag': saved['etag']}
        counts['merged'] += 1
    return counts


def consolidate(service, plan: dict | None = None) -> dict:
    plan = plan or load_plan()
    total = {'merged': 0, 'deleted': 0, 'skipped': 0, 'conflict': 0, 'failed': 0}
    for group in plan['merge']:
        try:
            for key, value in merge_group(group, service).items():
                total[key] += value
        except Conflict:
            total['conflict'] += 1
        except Exception:
            total['failed'] += 1
            logger.exception('Could not merge into %s', group.get('into'))
    for slug in plan['delete']:
        try:
            state = _live(service, slug)
            if state is None:
                total['skipped'] += 1
                continue
            service.action(slug, 'delete', state['etag'], EDITOR)
            total['deleted'] += 1
        except Conflict:
            total['conflict'] += 1
        except Exception:
            total['failed'] += 1
            logger.exception('Could not delete %s', slug)
    return total
