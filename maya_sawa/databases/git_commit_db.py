"""Database access for git commit knowledge records."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import BigInteger, Boolean, Column, DateTime, String, Text, create_engine, pool, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from ..core.config.config import Config
from ..core.processing.git_commit_parser import ParsedCommit

logger = logging.getLogger(__name__)
Base = declarative_base()


class GitCommit(Base):
    __tablename__ = "maya_sawa_git_commits"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    commit_hash = Column(String(40), unique=True, nullable=False)
    git_url = Column(String(500), nullable=True)
    commit_time = Column(DateTime(timezone=True), nullable=False)
    commit_message = Column(Text, nullable=True)
    changed_files_summary = Column(Text, nullable=True)
    embedding = Column(Text, nullable=True)
    is_trivial = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "commit_hash": self.commit_hash,
            "git_url": self.git_url,
            "commit_time": self.commit_time.isoformat() if self.commit_time else None,
            "commit_message": self.commit_message,
            "changed_files_summary": self.changed_files_summary,
            "embedding": self.embedding,
            "is_trivial": self.is_trivial,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class GitCommitDatabase:
    _instance = None
    _engine = None
    _session_factory = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._engine is None:
            self._initialize_engine()

    def _initialize_engine(self) -> None:
        db_url = Config.get_paprika_db_url()
        if not db_url:
            logger.warning("Git commit database URL not configured")
            return

        self._engine = create_engine(
            db_url,
            poolclass=pool.QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_recycle=1800,
            echo=False,
        )
        self._session_factory = sessionmaker(bind=self._engine)
        logger.info("Git commit database initialized")

    @contextmanager
    def get_session(self):
        if self._session_factory is None:
            raise RuntimeError("Git commit database not initialized")
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def is_available(self) -> bool:
        return self._engine is not None

    def commit_exists(self, commit_hash: str) -> bool:
        with self.get_session() as session:
            return (
                session.query(GitCommit.commit_hash)
                .filter(GitCommit.commit_hash == commit_hash)
                .first()
                is not None
            )

    def existing_hashes(self, commit_hashes: Iterable[str]) -> set[str]:
        hashes = list({h for h in commit_hashes if h})
        if not hashes:
            return set()
        with self.get_session() as session:
            rows = session.query(GitCommit.commit_hash).filter(GitCommit.commit_hash.in_(hashes)).all()
            return {row[0] for row in rows}

    def create_commit(self, parsed: ParsedCommit, embedding: Optional[List[float]]) -> bool:
        embedding_literal = None if embedding is None else "[" + ",".join(str(float(x)) for x in embedding) + "]"
        sql = text(
            """
            INSERT INTO maya_sawa_git_commits (
                commit_hash, git_url, commit_time, commit_message,
                changed_files_summary, embedding, is_trivial
            )
            VALUES (
                :commit_hash, :git_url, :commit_time, :commit_message,
                :changed_files_summary, CAST(:embedding AS vector), :is_trivial
            )
            ON CONFLICT (commit_hash) DO NOTHING
            """
        )
        with self.get_session() as session:
            result = session.execute(
                sql,
                {
                    "commit_hash": parsed.commit_hash,
                    "git_url": parsed.git_url,
                    "commit_time": parsed.commit_time,
                    "commit_message": parsed.commit_message,
                    "changed_files_summary": parsed.changed_files_summary,
                    "embedding": embedding_literal,
                    "is_trivial": parsed.is_trivial,
                },
            )
            return result.rowcount == 1

    def get_commits(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        limit = min(max(limit, 1), 200)
        offset = max(offset, 0)
        with self.get_session() as session:
            commits = (
                session.query(GitCommit)
                .order_by(GitCommit.commit_time.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )
            return [commit.to_dict() for commit in commits]


_git_commit_db: Optional[GitCommitDatabase] = None


def get_git_commit_db() -> GitCommitDatabase:
    global _git_commit_db
    if _git_commit_db is None:
        _git_commit_db = GitCommitDatabase()
    return _git_commit_db
