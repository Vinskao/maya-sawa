"""Market research report library endpoints."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import asyncio
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..core.auth.keycloak import require_manage_users_request
from ..core.config.config import Config
from ..databases.market_reports_db import market_reports_db
from ..services.embedding_service import get_embedding_service
from ..services.market_reports import (
    MAX_REPORT_BYTES,
    PDFTextExtractionError,
    chunk_pages,
    extract_pdf_pages,
    report_digest,
    report_for_viewer,
    validate_claims,
    validate_pdf,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market/reports", tags=["market-reports"])


async def _optional_owner(authorization: str | None = Header(None)):
    """Public listing supports anonymous readers; invalid or expired bearers are anonymous."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    from ..core.auth.keycloak import verify_bearer_token

    try:
        payload = verify_bearer_token(authorization.split(None, 1)[1])
        if Config.GIT_COMMIT_REQUIRED_ROLE not in set(payload.get("_roles", [])):
            return None
        return payload
    except Exception:
        return None


def _verify_agent(key: str | None) -> None:
    expected = os.environ.get("MARKET_AGENT_KEY_SHA256", "").strip().lower()
    if (
        not key
        or not expected
        or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), expected)
    ):
        raise HTTPException(status_code=401, detail="Invalid agent key")


def _owner(claims: dict) -> str:
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Authenticated identity required")
    return str(subject)


@router.post("")
async def upload_report(
    file: UploadFile = File(...),
    title: str = Form(...),
    publisher: str = Form(""),
    published_at: date | None = Form(None),
    visibility: str = Form("public"),
    claims: dict = Depends(require_manage_users_request),
):
    uploaded_by = _owner(claims)
    if visibility not in {"public", "owner"}:
        raise HTTPException(
            status_code=422, detail="visibility must be public or owner"
        )
    if not title.strip() or len(title) > 300 or len(publisher) > 200:
        raise HTTPException(status_code=422, detail="Invalid report title or publisher")
    data = await file.read(MAX_REPORT_BYTES + 1)
    try:
        validate_pdf(file.filename or "", file.content_type or "", data)
    except ValueError as exc:
        raise HTTPException(
            status_code=413 if len(data) > MAX_REPORT_BYTES else 422, detail=str(exc)
        ) from exc
    digest = report_digest(data)
    # Avoid spending embedding calls when this exact file is already stored.
    existing = market_reports_db.find_by_digest(digest)
    if existing:
        if (
            existing.get("status") == "failed"
            and existing.get("uploaded_by") == uploaded_by
        ):
            # A failed attempt owns the digest but has no usable vectors. Let the same
            # uploader retry, while the database check prevents deleting a row that
            # another concurrent request has already repaired.
            removed = market_reports_db.delete_failed_owned(existing["id"], uploaded_by)
            if not removed:
                existing = market_reports_db.find_by_digest(digest) or existing
                return {
                    "report": report_for_viewer(existing, uploaded_by),
                    "duplicate": True,
                }
        else:
            return {
                "report": report_for_viewer(existing, uploaded_by),
                "duplicate": True,
            }
    try:
        pages = extract_pdf_pages(data)
    except ValueError as exc:
        stored = market_reports_db.save_failed(
            title=title.strip(),
            publisher=publisher.strip(),
            published_at=published_at,
            visibility=visibility,
            uploaded_by=uploaded_by,
            digest=digest,
            pdf=data,
            reason=str(exc),
            page_count=exc.page_count if isinstance(exc, PDFTextExtractionError) else 0,
        )
        return {"report": report_for_viewer(stored, uploaded_by), "duplicate": False}
    chunks = chunk_pages(pages)
    try:
        vectors = await asyncio.to_thread(
            get_embedding_service().embed_documents, [item["text"] for item in chunks]
        )
        report, duplicate = await asyncio.to_thread(
            market_reports_db.ingest,
            title=title.strip(),
            publisher=publisher.strip(),
            published_at=published_at,
            visibility=visibility,
            uploaded_by=uploaded_by,
            digest=digest,
            pdf=data,
            pages=pages,
            chunks=chunks,
            vectors=vectors,
        )
        return {
            "report": report_for_viewer(report, uploaded_by),
            "duplicate": duplicate,
        }
    except Exception as exc:
        logger.exception("Market report ingestion failed")
        try:
            stored = await asyncio.to_thread(
                market_reports_db.save_failed,
                title=title.strip(),
                publisher=publisher.strip(),
                published_at=published_at,
                visibility=visibility,
                uploaded_by=uploaded_by,
                digest=digest,
                pdf=data,
                reason="向量化失敗，請稍後重試",
                page_count=len(pages),
                pages=pages,
            )
        except Exception:
            logger.exception("Could not record failed market report")
            raise HTTPException(
                status_code=503, detail="Report extraction or embedding failed"
            ) from exc
        return {
            "report": report_for_viewer(stored, uploaded_by),
            "duplicate": False,
        }


@router.get("")
async def list_reports(claims: dict | None = Depends(_optional_owner)):
    owner = str(claims["sub"]) if claims and claims.get("sub") else None
    try:
        reports = market_reports_db.list_reports(owner)
        reports = [
            {
                **{
                    key: value
                    for key, value in report.items()
                    if key not in {"text", "uploaded_by"}
                },
                "can_download": owner is not None
                and report.get("uploaded_by") == owner,
            }
            for report in reports
        ]
        return {"reports": reports}
    except Exception as exc:
        logger.exception("Market report listing failed")
        raise HTTPException(
            status_code=503, detail="Report library unavailable"
        ) from exc


@router.get("/claims")
async def list_report_claims(
    code: str | None = None, segment: str | None = None, since: date | None = None
):
    try:
        return {
            "claims": market_reports_db.list_claims(
                code=code.strip().upper() if code else None,
                segment=segment,
                since=since,
            )
        }
    except Exception as exc:
        logger.exception("Market report claims unavailable")
        raise HTTPException(
            status_code=503, detail="Report claims unavailable"
        ) from exc


@router.get("/search")
async def search_reports(
    q: str,
    code: str | None = None,
    segment: str | None = None,
    limit: int = 10,
    x_market_agent_key: str | None = Header(None),
):
    if not q.strip() or len(q) > 1000:
        raise HTTPException(
            status_code=422, detail="Search text must be between 1 and 1000 characters"
        )
    include_private = bool(x_market_agent_key)
    if x_market_agent_key:
        _verify_agent(x_market_agent_key)
    try:
        vector = await asyncio.to_thread(get_embedding_service().embed_query, q.strip())
        return {
            "results": await asyncio.to_thread(
                market_reports_db.search_chunks,
                vector,
                code=code.strip().upper() if code else None,
                segment=segment,
                limit=min(max(limit, 1), 50),
                include_private=include_private,
            )
        }
    except Exception as exc:
        logger.exception("Market report search failed")
        raise HTTPException(
            status_code=503, detail="Report search unavailable"
        ) from exc


@router.get("/pending")
async def pending_reports(x_market_agent_key: str | None = Header(None)):
    _verify_agent(x_market_agent_key)
    return {"reports": market_reports_db.pending_claims()}


@router.get("/{report_id}")
async def get_report(
    report_id: str,
    download: bool = False,
    claims: dict | None = Depends(_optional_owner),
):
    result = market_reports_db.get_report(report_id, include_pdf=download)
    if not result:
        raise HTTPException(status_code=404, detail="Report not found")
    report, pdf, uploaded_by = result
    owner = str(claims["sub"]) if claims and claims.get("sub") else None
    visible = report_for_viewer(
        {**report, "uploaded_by": uploaded_by}, owner, include_text=True
    )
    if visible is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if download:
        if owner != uploaded_by:
            raise HTTPException(
                status_code=403,
                detail="Only the uploader can download the original PDF",
            )
        return Response(
            pdf,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{report_id}.pdf"',
                "Cache-Control": "no-store",
            },
        )
    return {"report": visible}


@router.delete("/{report_id}")
async def delete_report(
    report_id: str, claims: dict = Depends(require_manage_users_request)
):
    if not market_reports_db.delete_owned(report_id, _owner(claims)):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": True}


class ClaimsBody(BaseModel):
    claims: list[dict]
    extracted_by: str


@router.put("/{report_id}/claims")
async def put_claims(
    report_id: str, body: ClaimsBody, x_market_agent_key: str | None = Header(None)
):
    _verify_agent(x_market_agent_key)
    try:
        saved = market_reports_db.replace_claims(
            report_id,
            validate_claims(body.claims, market_reports_db.page_count(report_id)),
            body.extracted_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not saved:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"saved": True, "claim_count": len(body.claims)}
