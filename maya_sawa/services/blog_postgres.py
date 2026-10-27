"""PostgreSQL editorial records plus an atomic projection into Maya's existing articles table."""
import json
import hashlib
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from sqlalchemy import Column, String, Integer, JSON, MetaData, Table, select, update, insert, text, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from .blog import Missing, Conflict, Unavailable

metadata = MetaData()
payload_type = JSON().with_variant(JSONB(), 'postgresql')
states = Table('blog_article_state', metadata,
               Column('key', String(500), primary_key=True), Column('payload', payload_type, nullable=False),
               Column('version', Integer, nullable=False))
revisions = Table('blog_article_revisions', metadata,
                  Column('key', String(500), primary_key=True), Column('payload', payload_type, nullable=False),
                  Column('version', Integer, nullable=False))


class PostgresStore:
    def __init__(self, engine):
        self.engine = engine

    def initialize(self):
        # Explicit migration command only. Runtime does not perform DDL.
        metadata.create_all(self.engine)

    def _table(self, key):
        return revisions if '/revisions/' in key else states

    def get(self, key):
        table = self._table(key)
        try:
            with self.engine.connect() as conn:
                row = conn.execute(select(table.c.payload, table.c.version).where(table.c.key == key)).first()
                if not row:
                    raise Missing()
                return row.payload, str(row.version)
        except SQLAlchemyError as exc:
            raise Unavailable() from exc

    def keys(self, prefix):
        table = self._table(prefix)
        try:
            with self.engine.connect() as conn:
                return list(conn.execute(select(table.c.key).where(table.c.key.startswith(prefix))).scalars())
        except SQLAlchemyError as exc:
            raise Unavailable() from exc

    def put(self, key, value, etag=None):
        table = self._table(key)
        try:
            version = int(etag) + 1 if etag is not None else 1
        except ValueError:
            raise Conflict()
        try:
            with self.engine.begin() as conn:
                previous = conn.execute(select(table.c.payload).where(table.c.key == key)).scalar()
                if etag is None:
                    conn.execute(insert(table).values(key=key, payload=value, version=version))
                else:
                    changed = conn.execute(update(table).where(table.c.key == key, table.c.version == int(etag))
                                           .values(payload=value, version=version)).rowcount
                    if not changed:
                        raise Conflict()
                if table is states and (previous or {}).get('published') != value.get('published'):
                    ready = self._project(conn, value)
                    if ready:
                        value['indexStatus'] = 'done'
                        conn.execute(update(table).where(table.c.key == key).values(payload=value))
            return str(version)
        except IntegrityError as exc:
            raise Conflict() from exc
        except SQLAlchemyError as exc:
            raise Unavailable() from exc

    def _project(self, conn, state):
        slug = state['id']
        path = f'{slug}.md'
        if not state.get('published'):
            # Only remove the derived search row. Source and immutable revisions remain recoverable.
            conn.execute(text('DELETE FROM articles WHERE file_path=:path'), {'path': path})
            return
        key = f"blog/v1/revisions/{slug}/{state['published']}.json"
        snapshot = conn.execute(select(revisions.c.payload).where(revisions.c.key == key)).scalar_one()
        existing = conn.execute(text('SELECT content,embedding FROM articles WHERE file_path=:path'), {'path': path}).first()
        ready = existing is not None and existing.content == snapshot['content'] and bool(existing.embedding)
        conn.execute(text('''INSERT INTO articles (file_path, content, file_date, embedding, deleted_at, updated_at)
            VALUES (:path, :content, :date, NULL, NULL, CURRENT_TIMESTAMP)
            ON CONFLICT (file_path) DO UPDATE SET content=excluded.content, file_date=excluded.file_date,
                embedding=CASE WHEN articles.content=excluded.content THEN articles.embedding ELSE NULL END,
                deleted_at=NULL, updated_at=CURRENT_TIMESTAMP'''),
            {'path': path, 'content': snapshot['content'], 'date': snapshot['publishDate']})
        return ready

    def adopt_legacy(self, slug, data, publish=False):
        """Attach editorial metadata to the existing DB body; never replace its ID or vector."""
        key = f'blog/v1/articles/{slug}.json'
        with self.engine.begin() as conn:
            if conn.execute(select(states.c.key).where(states.c.key == key)).first():
                raise Conflict()
            lock = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
            row = conn.execute(text('SELECT id,content,embedding FROM articles WHERE file_path=:path' + lock), {'path': f'{slug}.md'}).first()
            if row is None:
                return None
            revision = uuid.uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            snapshot = {**data, 'content': row.content, 'revision': revision, 'updatedAt': now,
                        'sha256': hashlib.sha256(row.content.encode()).hexdigest()}
            state = {'id': slug, 'revision': revision, 'published': revision if publish else None,
                     'deleted': False, 'editor': 'migration:frontend', 'updatedAt': now,
                     'legacyArticleId': row.id, 'indexStatus': ('done' if row.embedding else 'pending') if publish else 'idle',
                     'event': uuid.uuid4().hex, 'attempts': 0, 'retryAfter': 0}
            conn.execute(insert(revisions).values(key=f'blog/v1/revisions/{slug}/{revision}.json', payload=snapshot, version=1))
            conn.execute(insert(states).values(key=key, payload=state, version=1))
            if publish:
                conn.execute(text('UPDATE articles SET deleted_at=NULL WHERE id=:id'), {'id': row.id})
            return {'state': {**state, 'etag': '1'}, 'hasVector': bool(row.embedding)}

    def vectorize(self, slug, snapshot, embed):
        if snapshot is None:
            return True  # The publication transaction already removed the search row.
        vector = embed(snapshot['content'])
        import math
        if not vector or not all(isinstance(value, (float, int)) and math.isfinite(value) for value in vector):
            raise ValueError('Invalid embedding')
        with self.engine.begin() as conn:
            current = conn.execute(select(states.c.payload).where(states.c.key == f'blog/v1/articles/{slug}.json').with_for_update()).scalar_one()
            if current.get('published') != snapshot['revision'] or current.get('deleted'):
                return False
            value = json.dumps(vector)
            expression = 'CAST(:vector AS vector)' if conn.dialect.name == 'postgresql' else ':vector'
            changed = conn.execute(text(f'UPDATE articles SET embedding={expression} WHERE file_path=:path AND content=:content'),
                                   {'vector': value, 'path': f'{slug}.md', 'content': snapshot['content']}).rowcount
            return bool(changed)


@lru_cache
def get_postgres_store():
    from ..core.config.config import Config
    if not Config.DB_CONNECTION_STRING:
        raise Unavailable()
    return PostgresStore(create_engine(Config.DB_CONNECTION_STRING, pool_pre_ping=True, connect_args={'connect_timeout': 5}))
