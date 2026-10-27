"""Database-backed editorial source of truth with immutable Markdown revisions."""
import copy
import hashlib
import time
import uuid
from datetime import datetime, timezone


class Missing(Exception):
    pass


class Conflict(Exception):
    pass


class Unavailable(Exception):
    pass


class BlogService:
    def __init__(self, store):
        self.store = store

    def _key(self, slug):
        return f'blog/v1/articles/{slug}.json'

    def _state(self, slug):
        return self.store.get(self._key(slug))

    def _write(self, slug, state, etag):
        next_etag = self.store.put(self._key(slug), state, etag)
        return {**state, 'etag': next_etag}

    def _check(self, state, actual, expected):
        if actual != expected or state.get('leaseUntil', 0) > time.time():
            raise Conflict()

    def revision(self, slug, revision):
        return self.store.get(f'blog/v1/revisions/{slug}/{revision}.json')[0]

    def read(self, slug, admin=False):
        state, etag = self._state(slug)
        if admin:
            return {**state, 'etag': etag, 'draft': self.revision(slug, state['revision'])}
        if state['deleted'] or not state.get('published'):
            raise Missing()
        return {**self.revision(slug, state['published']), 'id': slug}

    def list(self, admin=False):
        rows = []
        for key in self.store.keys('blog/v1/articles/'):
            slug = key.rsplit('/', 1)[-1][:-5]
            try:
                article = self.read(slug, admin)
                if admin:
                    rows.append(article)
                else:
                    article.pop('content', None)
                    rows.append(article)
            except Missing:
                continue
        return sorted(rows, key=lambda row: (row.get('draft') or row)['publishDate'], reverse=True)

    def save(self, slug, data, expected, editor):
        try:
            state, etag = self._state(slug)
            self._check(state, etag, expected)
            if state['deleted']:
                raise Conflict()
        except Missing:
            if expected is not None:
                raise Conflict()
            state, etag = {'id': slug, 'published': None, 'deleted': False, 'indexStatus': 'idle'}, None
        revision = uuid.uuid4().hex
        snapshot = copy.deepcopy(data)
        snapshot['revision'] = revision
        snapshot['updatedAt'] = datetime.now(timezone.utc).isoformat()
        snapshot['sha256'] = hashlib.sha256(data['content'].encode()).hexdigest()
        self.store.put(f'blog/v1/revisions/{slug}/{revision}.json', snapshot)
        state.update(revision=revision, editor=editor, updatedAt=snapshot['updatedAt'])
        return self._write(slug, state, etag)

    def action(self, slug, action, expected, editor):
        state, etag = self._state(slug)
        self._check(state, etag, expected)
        if state['deleted'] and action != 'restore':
            raise Conflict()
        if action == 'restore' and not state['deleted']:
            raise Conflict()
        if action == 'publish':
            if state.get('published') == state['revision']:
                return {**state, 'etag': etag}
            state['published'] = state['revision']
        elif action in ('delete', 'unpublish'):
            state['published'] = None
            state['deleted'] = action == 'delete'
        elif action == 'restore':
            state['deleted'] = False
            state['published'] = None
        else:
            raise ValueError('Unknown action')
        state.update(editor=editor, event=uuid.uuid4().hex, indexStatus='pending', attempts=0, retryAfter=0)
        return self._write(slug, state, etag)

    def process(self, slug, indexer):
        state, etag = self._state(slug)
        if state['indexStatus'] == 'done' or state['indexStatus'] == 'idle':
            return {**state, 'etag': etag}
        self._check(state, etag, etag)
        state['leaseUntil'] = time.time() + 180
        claimed = self._write(slug, state, etag)
        try:
            snapshot = self.revision(slug, state['published']) if state.get('published') else None
            indexer(slug, snapshot)
            state['indexStatus'] = 'done'
            state['attempts'] = 0
            state['retryAfter'] = 0
        except Exception:
            state['indexStatus'] = 'failed'
            state['attempts'] = min(state.get('attempts', 0) + 1, 10)
            state['retryAfter'] = time.time() + min(3600, 30 * 2 ** state['attempts'])
        state['leaseUntil'] = 0
        return self._write(slug, state, claimed['etag'])


def index_article(slug, snapshot):
    from .blog_postgres import get_postgres_store
    from ..services.embedding_service import get_embedding_service
    if not get_postgres_store().vectorize(slug, snapshot, get_embedding_service().generate_embedding):
        raise Conflict()
