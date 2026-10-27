"""Strict, non-executable Markdown frontmatter input for agents and clipboard pastes."""
import re
from datetime import datetime, timezone, timedelta
import yaml


def parse_markdown(markdown, fallback_slug=None):
    raw = markdown.lstrip('\ufeff')
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)(.*)\Z', raw, re.S)
    if not match:
        raise ValueError('Markdown requires YAML frontmatter')
    try:
        # Reject aliases/anchors: editorial metadata does not need them.
        if any(isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)) for token in yaml.scan(match[1])):
            raise ValueError('YAML aliases are not supported')
        meta = yaml.safe_load(match[1])
        if not isinstance(meta, dict):
            raise ValueError('Invalid metadata')
        slug = meta.get('slug') or fallback_slug
        if not isinstance(slug, str) or len(slug) > 120 or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', slug):
            raise ValueError('A valid slug is required')
        date = datetime.fromisoformat(str(meta['publishDate']).replace('Z', '+00:00'))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone(timedelta(hours=8)))
        from ..api.blog import Draft
        data = Draft(title=meta['title'], description=meta['description'], category=meta.get('category', 'Engineering'),
                     tags=meta.get('tags', []), content=match[2].strip(), publishDate=date)
        return slug, {**data.model_dump(mode='json'), 'publishDate': data.publishDate.isoformat()}
    except Exception as exc:
        raise ValueError('Check slug, title, description, publishDate, tags and Markdown content') from exc
