from datetime import datetime
from types import SimpleNamespace
from maya_sawa.databases.qa_vector_db import QAVectorDatabase


def test_qa_casts_legacy_text_vectors_and_excludes_deleted_articles():
    calls = []
    cursor = SimpleNamespace(execute=lambda sql, args: calls.append((sql, args)),
                             fetchall=lambda: [(218, 'react-hydration.md', 'SSR body', datetime(2026,1,2), 0.95)])
    connection = SimpleNamespace(cursor=lambda: cursor)
    returned = []
    db = QAVectorDatabase.__new__(QAVectorDatabase)
    db.pool_manager = SimpleNamespace(get_postgres_connection=lambda: connection, return_postgres_connection=returned.append)
    db.embedding_service = SimpleNamespace(embed_query=lambda query: [1, 0])
    results = db.similarity_search('SSR', k=1, threshold=0.7)
    assert results[0].page_content == 'SSR body'
    assert results[0].metadata['id'] == 218
    assert returned == [connection]
    sql, values = calls[0]
    assert 'embedding::vector' in sql
    assert 'deleted_at IS NULL' in sql
    assert values[-1] == 1
