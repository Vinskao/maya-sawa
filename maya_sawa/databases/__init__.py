"""
Databases Module

This module contains all database-related classes and configurations
for different data sources used in the Maya Sawa unified system.

Databases:
- Paprika Database: Article management (from Laravel)
- Maya-v2 Database: Conversations & AI models (from Django)
- Postgres Vector Store: Document embeddings for QA system

Author: Maya Sawa Team
Version: 0.1.0
"""

from .paprika_db import get_paprika_db, PaprikaDatabase, Article
from .maya_v2_db import get_maya_v2_db, MayaV2Database
from .postgres_store import PostgresVectorStore

__all__ = [
    'get_paprika_db',
    'PaprikaDatabase', 
    'Article',
    'get_maya_v2_db',
    'MayaV2Database',
    'PostgresVectorStore'
]
