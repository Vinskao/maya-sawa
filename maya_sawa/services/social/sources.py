"""The current public AI analyses that get posted: the same rows /dashboard/analysis serves. Never holdings or reports."""
from datetime import datetime

from ...databases.market_ai_analysis_db import market_ai_analysis_db

SOURCE_LIMIT = 30


def public_sources(since=None, limit=SOURCE_LIMIT):
    rows = market_ai_analysis_db.list('stock') + [row for row in market_ai_analysis_db.list('macro') if row['code'] == 'US']
    items = [{'id': f"{row['productType']}:{row['code']}:{row['revision']}", 'productType': row['productType'],
              'code': row['code'], 'revision': row['revision'], 'updatedAt': row['updatedAt'], 'content': row['content']}
             for row in rows if since is None or datetime.fromisoformat(row['updatedAt']) > since]
    items.sort(key=lambda item: datetime.fromisoformat(item['updatedAt']), reverse=True)
    if limit is None:
        return {'sources': items, 'truncated': False}
    return {'sources': items[:limit], 'truncated': len(items) > limit}
