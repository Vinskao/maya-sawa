"""Git commit knowledge ingestion API."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..core.auth.keycloak import require_git_commit_access
from ..core.services.ai_rate_limiter import enforce_ai_rate_limit
from ..core.processing.git_commit_parser import parse_paste
from ..databases.git_commit_db import get_git_commit_db
from ..services.embedding_service import get_embedding_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/git-commits", tags=["Git Commits"])


class GitCommitIngestRequest(BaseModel):
    text: str = Field(..., min_length=1)
    generate_embedding: bool = True


class GitCommitIngestResponse(BaseModel):
    success: bool
    received: int
    created: int
    skipped_duplicate: int
    skipped_trivial: int
    embedding_failed: int
    timestamp: str
    details: List[Dict[str, Any]]


@router.post("/ingest", response_model=GitCommitIngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_git_commits(
    request: GitCommitIngestRequest,
    http_request: Request,
):
    enforce_ai_rate_limit(http_request, allow_anonymous=False)

    db = get_git_commit_db()
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Git commit database is not available")

    parsed_commits = parse_paste(request.text)
    existing = db.existing_hashes(commit.commit_hash for commit in parsed_commits)
    embedding_service = get_embedding_service() if request.generate_embedding else None

    stats = {
        "received": len(parsed_commits),
        "created": 0,
        "skipped_duplicate": 0,
        "skipped_trivial": 0,
        "embedding_failed": 0,
    }
    details: List[Dict[str, Any]] = []

    for commit in parsed_commits:
        detail = {"commit_hash": commit.commit_hash, "status": "created"}
        if commit.commit_hash in existing:
            stats["skipped_duplicate"] += 1
            detail["status"] = "skipped_duplicate"
            details.append(detail)
            continue

        if commit.is_trivial:
            stats["skipped_trivial"] += 1
            detail["status"] = "skipped_trivial"
            details.append(detail)
            continue

        embedding: Optional[List[float]] = None
        if embedding_service is not None:
            try:
                embedding_text = f"{commit.commit_message}\n{commit.changed_files_summary}".strip()
                embedding = embedding_service.generate_embedding(embedding_text)
            except Exception as exc:
                logger.warning("Embedding failed for commit %s: %s", commit.commit_hash, exc)
                stats["embedding_failed"] += 1
                detail["embedding"] = "failed"

        created = db.create_commit(commit, embedding)
        if created:
            stats["created"] += 1
            existing.add(commit.commit_hash)
        else:
            stats["skipped_duplicate"] += 1
            detail["status"] = "skipped_duplicate"
        details.append(detail)

    return GitCommitIngestResponse(
        success=True,
        timestamp=datetime.utcnow().isoformat(),
        details=details,
        **stats,
    )


@router.get("/", response_model=Dict[str, Any])
async def list_git_commits(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _claims: Dict[str, Any] = Depends(require_git_commit_access),
):
    db = get_git_commit_db()
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Git commit database is not available")

    return {
        "success": True,
        "data": db.get_commits(limit=limit, offset=offset),
        "timestamp": datetime.utcnow().isoformat(),
    }
