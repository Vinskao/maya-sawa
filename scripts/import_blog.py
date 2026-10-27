"""One-time archive import. Dry-run by default; never overwrites an editor's work."""
import argparse
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import yaml
from maya_sawa.services.blog import BlogService, Missing
from maya_sawa.api.blog import Draft
from maya_sawa.services.blog_postgres import get_postgres_store


def load_articles(directory):
    articles = []
    for path in sorted(directory.glob('*.md')):
        raw = path.read_text(encoding='utf-8-sig')
        _, front, content = raw.split('---', 2)
        meta = yaml.safe_load(front)
        date = meta['publishDate']
        date = datetime.fromisoformat(str(date).replace('Z', '+00:00'))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone(timedelta(hours=8)))
        data = dict(title=meta['title'], description=str(meta.get('description', '')).strip() or meta['title'],
                    content=content.strip(), category=meta.get('category') or 'Other', tags=meta.get('tags', []),
                    publishDate=date.astimezone(timezone.utc).isoformat())
        # Validate the entire archive before the first write.
        Draft(**data)
        articles.append({'slug': path.stem, **data})
    return articles


def migrate(service, rows, publish=False):
    result = dict(created=0, unchanged=0, protected=0, published=0, adopted=0, preservedVectors=0)
    for row in rows:
        slug = row['slug']
        payload = {key: value for key, value in row.items() if key != 'slug'}
        try:
            state = service.read(slug, admin=True)
            if state['editor'] != 'migration:frontend' or state['draft']['sha256'] != hashlib.sha256(payload['content'].encode()).hexdigest():
                result['protected'] += 1
                continue
            result['unchanged'] += 1
        except Missing:
            adopted = service.store.adopt_legacy(slug, payload, publish) if hasattr(service.store, 'adopt_legacy') else None
            if adopted:
                state = adopted['state']
                result['adopted'] += 1
                result['preservedVectors'] += int(adopted['hasVector'])
                # Existing DB edits are authoritative, even if the frontend archive differs.
                payload['content'] = service.read(slug, admin=True)['draft']['content']
            else:
                state = service.save(slug, payload, None, 'migration:frontend')
                result['created'] += 1
        if publish and not state.get('published') and not state['deleted']:
            state = service.action(slug, 'publish', state['etag'], 'migration:frontend')
            result['published'] += 1
        # Verify the exact UTF-8 body after the write; mismatch stops migration.
        saved = service.read(slug, admin=True)
        if saved['draft']['content'] != payload['content']:
            raise RuntimeError(f'Read-back mismatch: {slug}')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('docs/blog-import'))
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--initialize', action='store_true')
    args = parser.parse_args()
    rows = load_articles(args.source)
    if not args.apply:
        print(json.dumps({'dryRun': True, 'count': len(rows), 'slugs': [row['slug'] for row in rows]}))
        return
    store = get_postgres_store()
    if args.initialize:
        store.initialize()
    print(json.dumps(migrate(BlogService(store), rows, args.publish)))


if __name__ == '__main__':
    main()
