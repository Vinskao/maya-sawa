"""Market research report library endpoints."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import asyncio
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
import httpx

from ..core.public_api import public_data
from ..core.auth.keycloak import require_manage_users_request, require_member_request
from ..core.config.config import Config
from ..databases.market_reports_db import market_reports_db
from ..databases.market_report_claims_inbox_db import (
    ClaimInboxDatabase, InvalidClaimProposal,
)
from ..databases.user_activity_db import user_activity_db
from ..services import sec_filings
from ..services.embedding_service import get_embedding_service
from ..services.report_security import review_report_pages
from ..services import market_automation
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
market_report_claims_inbox_db = ClaimInboxDatabase(
    market_reports_db.sessions.kw["bind"] if market_reports_db.sessions else None
)

MEMBER_DAILY_UPLOADS = 5  # reports a member may upload per Taipei day; the owner has no limit
TAIPEI = ZoneInfo("Asia/Taipei")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _taipei_day_start(now: datetime) -> datetime:
    local = now.astimezone(TAIPEI)
    return datetime(local.year, local.month, local.day, tzinfo=TAIPEI).astimezone(timezone.utc)


def _is_owner(claims: dict) -> bool:
    return Config.GIT_COMMIT_REQUIRED_ROLE in set(claims.get("_roles", []))


async def _audit(claims: dict, action: str, resource_type: str, resource_id: str, detail: dict | None = None) -> None:
    """Write who did what to the activity log. A logging failure is reported but does not undo the action."""
    try:
        sub = str(claims.get("sub") or "")
        name = str(claims.get("preferred_username") or claims.get("name") or "")
        await asyncio.to_thread(user_activity_db.touch_user, sub, name)
        await asyncio.to_thread(user_activity_db.record, sub, name, action, resource_type, resource_id, detail or {})
    except Exception:
        logger.exception("User activity could not be recorded (%s %s %s)", action, resource_type, resource_id)


async def _optional_owner(authorization: str | None = Header(None)):
    """The signed-in viewer (a member or the owner), or None. Public listing supports anonymous readers; invalid or
    expired bearers are anonymous. A viewer sees public reports and their own uploads."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    from ..core.auth.keycloak import verify_bearer_token

    try:
        payload = verify_bearer_token(authorization.split(None, 1)[1])
        return payload if payload.get("sub") else None
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
    background_tasks: BackgroundTasks = None,
    claims: dict = Depends(require_member_request),
):
    uploaded_by = _owner(claims)
    owner = _is_owner(claims)
    if owner and visibility != "public":
        raise HTTPException(
            status_code=422, detail="Reports must be public"
        )
    if not title.strip() or len(title) > 300 or len(publisher) > 200:
        raise HTTPException(status_code=422, detail="Invalid report title or publisher")
    if not owner:
        # A member's upload is private to them until the owner approves it, whatever visibility they asked for.
        visibility = "owner"
        used = await asyncio.to_thread(market_reports_db.count_uploads_since, uploaded_by, _taipei_day_start(_now()))
        if used >= MEMBER_DAILY_UPLOADS:
            raise HTTPException(status_code=429, detail=f"Daily upload limit reached ({MEMBER_DAILY_UPLOADS} reports per day)")
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
        report, duplicate = market_reports_db.save_queued(
            title=title.strip(),
            publisher=publisher.strip(),
            published_at=published_at,
            visibility=visibility,
            uploaded_by=uploaded_by,
            digest=digest,
            pdf=data,
            received_at=_now(),
        )
    except Exception as exc:
        logger.exception("Could not queue uploaded market report")
        raise HTTPException(
            status_code=503, detail="Report upload could not be queued"
        ) from exc
    if duplicate:
        return {"report": report_for_viewer(report, uploaded_by), "duplicate": True}
    await _audit(claims, "C", "report", report["id"], {"title": title.strip()[:200], "visibility": visibility, "bytes": len(data)})
    if background_tasks is None:
        # FastAPI always injects this parameter in an HTTP request. Keep direct callers
        # from creating a permanently queued record if they omit the task collector.
        market_reports_db.set_upload_status(report["id"], "failed", "Background processing unavailable")
        raise HTTPException(status_code=503, detail="Report processing unavailable")
    background_tasks.add_task(process_queued_report, report["id"])
    return {"report": report_for_viewer(report, uploaded_by), "duplicate": False}


async def process_queued_report(report_id: str) -> None:
    """Extract and index a persisted PDF after the upload response has been sent."""
    try:
        stored = await asyncio.to_thread(market_reports_db.get_report, report_id, include_pdf=True)
        if not stored:
            return
        report, pdf, _uploaded_by = stored
        if report.get("status") != "queued":
            return
        await asyncio.to_thread(market_reports_db.set_upload_status, report_id, "processing")
        try:
            pages = await asyncio.to_thread(extract_pdf_pages, pdf)
        except ValueError as exc:
            page_count = exc.page_count if isinstance(exc, PDFTextExtractionError) else 0
            await asyncio.to_thread(market_reports_db.set_upload_status, report_id, "failed", str(exc))
            # Scanned documents still expose the page count in the failure record.
            if page_count:
                await asyncio.to_thread(market_reports_db.set_upload_page_count, report_id, page_count)
            return
        review = await asyncio.to_thread(review_report_pages, [report.get('title') or '', report.get('publisher') or '', *pages])
        if review.flagged:
            await asyncio.to_thread(market_reports_db.set_upload_status, report_id, "quarantined", "PDF 內容含可疑指令或隱藏字元，已隔離待審查")
            logger.warning("Report %s quarantined: %s", report_id, review.reason)
            return
        await asyncio.to_thread(market_reports_db.update_upload_extracted, report_id, pages)
        chunks = chunk_pages(pages)
        try:
            vectors = await asyncio.to_thread(
                get_embedding_service().embed_documents, [item["text"] for item in chunks]
            )
            await asyncio.to_thread(market_reports_db.add_chunks, report_id, chunks, vectors)
        except Exception as exc:
            logger.warning(
                "Semantic indexing unavailable for report %s: %s",
                report_id,
                type(exc).__name__,
            )
        # A member's upload stays out of the claim extraction queue (and so out of the public analyses) until the owner approves it.
        held = report.get("visibility") == "owner"
        await asyncio.to_thread(market_reports_db.set_upload_status, report_id, "awaiting_review" if held else "claims_pending")
    except Exception as exc:
        logger.exception("Background processing failed for market report %s", report_id)
        try:
            await asyncio.to_thread(
                market_reports_db.set_upload_status,
                report_id,
                "failed",
                f"Report processing failed: {type(exc).__name__}",
            )
        except Exception:
            logger.exception("Could not save failure state for market report %s", report_id)

@router.get("", **public_data("公開研究報告清單（含 SEC 申報、頻道貼文與網路文章）", "研究報告與主張"))
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


MARKET_SUFFIXES = ("-US", "-JP", "-KR")


def claim_code_variants(code: str) -> list[str]:
    """Claims carry plain tickers (MU, 000660); the dashboard and the routines use MU-US / 000660-KR, so try both."""
    code = code.strip().upper()
    plain = code[: -3] if code.endswith(MARKET_SUFFIXES) else code
    return [code] if plain == code else [code, plain]


class WebReportRequest(BaseModel):
    url: str = Field(min_length=10, max_length=500)


@router.post("/web")
async def add_report_from_url(body: WebReportRequest, claims: dict = Depends(require_manage_users_request)):
    """Owner only: add an SEC EDGAR filing (a https://www.sec.gov/Archives/edgar/data/... page) as reports, one per chosen section."""
    owner = _owner(claims)
    url = body.url.strip()
    if not sec_filings.allowed_filing_url(url):
        raise HTTPException(status_code=422, detail="Only https://www.sec.gov/Archives/edgar/data/... .htm pages are allowed")
    try:
        return await asyncio.to_thread(sec_filings.import_filing, market_reports_db, url, owner)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        logger.warning("SEC filing fetch failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Could not fetch the filing from sec.gov") from exc


@router.get("/collector", **public_data("Telegram 頻道收集狀況（各頻道的數量與狀態，不含貼文內容）", "研究報告與主張"))
async def collector_status():
    """Public, aggregate only: what the Telegram collector has stored per channel (no post text)."""
    try:
        return {"channels": market_reports_db.collector_summary()}
    except Exception as exc:
        logger.exception("Collector summary unavailable")
        raise HTTPException(status_code=503, detail="Collector summary unavailable") from exc


@router.get("/claims", **public_data("研究報告主張（可用 code 或 segment 篩選）", "研究報告與主張"))
async def list_report_claims(
    code: str | None = None, segment: str | None = None, since: date | None = None
):
    try:
        claims, seen = [], set()
        for variant in claim_code_variants(code) if code else [None]:
            for claim in market_reports_db.list_claims(code=variant, segment=segment, since=since):
                key = (claim.get("report_id"), claim.get("page"), claim.get("claim"))
                if key not in seen:
                    seen.add(key)
                    claims.append(claim)
        return {"claims": claims}
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
    include_private: bool = False,
    x_market_agent_key: str | None = Header(None),
):
    if not q.strip() or len(q) > 1000:
        raise HTTPException(
            status_code=422, detail="Search text must be between 1 and 1000 characters"
        )
    if x_market_agent_key:
        _verify_agent(x_market_agent_key)
    elif include_private:
        _verify_agent(None)
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


@router.get("/fulltext", **public_data("公開研究報告全文關鍵字搜尋（每個詞都要出現；回傳報告、頁碼與摘錄）", "研究報告與主張"))
async def fulltext_reports(q: str, limit: int = 200):
    if len(q) > 200:
        raise HTTPException(status_code=422, detail="Search text must be at most 200 characters")
    if not q.strip():
        return {"results": []}
    try:
        return {"results": await asyncio.to_thread(market_reports_db.search_text, q.strip(), min(max(limit, 1), 200))}
    except Exception as exc:
        logger.exception("Market report full-text search failed")
        raise HTTPException(status_code=503, detail="Report search unavailable") from exc


@router.get("/pending")
async def pending_reports(x_market_agent_key: str | None = Header(None)):
    _verify_agent(x_market_agent_key)
    return {"reports": market_reports_db.pending_claims()}


@router.get("/claim-proposals/sources")
async def gpt_claim_sources():
    return {"reports": await asyncio.to_thread(market_reports_db.public_pending_claim_ids)}


@router.get("/claim-proposals/source/{report_id}")
async def gpt_claim_source(report_id: str):
    """GPT receives only one public, currently pending report at a time."""
    try:
        report = await asyncio.to_thread(market_report_claims_inbox_db.source_report, report_id, market_reports_db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Public pending report not found") from exc
    return {"report": report}


class ClaimProposalBody(BaseModel):
    claims: list[dict] = Field(max_length=300)


class ClaimProposalReviewBody(BaseModel):
    action: str = Field(pattern="^(apply|reject)$")
    note: str = Field(default="", max_length=300)


@router.post("/claim-proposals/{report_id}")
async def submit_gpt_claim_proposal(report_id: str, body: ClaimProposalBody):
    """Store untrusted model output for keyed review; this never changes live claims."""
    try:
        proposal, created = await asyncio.to_thread(
            market_report_claims_inbox_db.submit, report_id, body.claims, market_reports_db
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Public pending report not found") from exc
    except InvalidClaimProposal as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    return {"stored": True, "created": created, "proposal": proposal}


@router.get("/claim-proposals")
async def list_gpt_claim_proposals(
    status: str = "pending", limit: int = 50,
    x_market_agent_key: str | None = Header(None),
):
    _verify_agent(x_market_agent_key)
    if status not in {"pending", "applying", "applied", "rejected", "failed", "all"}:
        raise HTTPException(status_code=422, detail="Invalid proposal status")
    return {"proposals": await asyncio.to_thread(
        market_report_claims_inbox_db.list, None if status == "all" else status, limit
    )}


@router.post("/claim-proposals/{proposal_id}/review")
async def review_gpt_claim_proposal(
    proposal_id: str, body: ClaimProposalReviewBody, background_tasks: BackgroundTasks,
    x_market_agent_key: str | None = Header(None),
):
    _verify_agent(x_market_agent_key)
    proposal = await asyncio.to_thread(market_report_claims_inbox_db.claim, proposal_id)
    if not proposal:
        if not await asyncio.to_thread(market_report_claims_inbox_db.get, proposal_id):
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=409, detail="Proposal is not pending")
    if body.action == "reject":
        result = await asyncio.to_thread(
            market_report_claims_inbox_db.finish, proposal_id, "rejected", {"note": body.note}
        )
        if not result:
            raise HTTPException(status_code=409, detail="Proposal review lease was lost")
        return result
    try:
        report = await asyncio.to_thread(market_report_claims_inbox_db.source_report,
                                         proposal["reportId"], market_reports_db)
        validated = validate_claims(proposal["claims"], report["page_count"])
    except (LookupError, ValueError) as exc:
        result = await asyncio.to_thread(market_report_claims_inbox_db.finish, proposal_id, "rejected",
                                         {"note": f"Source no longer pending or proposal invalid: {exc}"})
        if not result:
            raise HTTPException(status_code=409, detail="Proposal review lease was lost")
        return result
    saved = await asyncio.to_thread(market_reports_db.replace_claims, proposal["reportId"], validated,
                                    "GPT (Claude review)", require_pending=True)
    if not saved:
        result = await asyncio.to_thread(market_report_claims_inbox_db.finish, proposal_id, "rejected",
                                         {"note": "Report is no longer public and pending"})
        if not result:
            raise HTTPException(status_code=409, detail="Proposal review lease was lost")
        return result
    related_codes = sorted({code.strip() for claim in validated for code in claim.get("codes", [])
                            if isinstance(code, str) and len(code.strip()) == 4 and code.strip().isdigit()})
    if related_codes and background_tasks:
        background_tasks.add_task(market_automation.fire_analysis_event,
            market_automation.automation_store(), event_key=f"report:{proposal['reportId']}:claims",
            codes=related_codes, reason=f"研究報告 {proposal['reportId']} 的主張已完成擷取")
    result = await asyncio.to_thread(market_report_claims_inbox_db.finish, proposal_id, "applied",
                                     {"claimCount": len(validated)})
    if not result:
        raise HTTPException(status_code=409, detail="Claims saved but proposal review lease was lost")
    return result


@router.get("/review-queue")
async def review_queue(claims: dict = Depends(require_manage_users_request)):
    """Owner only: member uploads waiting for a decision (no text, no PDF)."""
    queue = await asyncio.to_thread(market_reports_db.review_queue)
    names = await asyncio.to_thread(user_activity_db.usernames, [row["uploaded_by"] for row in queue])
    return {"reports": [{key: value for key, value in {**row, "uploadedBy": names.get(row["uploaded_by"]) or row["uploaded_by"]}.items()
                         if key != "uploaded_by"} for row in queue]}


class ReviewBody(BaseModel):
    action: str = Field(pattern="^(approve|reject)$")
    note: str = Field(default="", max_length=300)


@router.post("/{report_id}/review")
async def review_report(report_id: str, body: ReviewBody, claims: dict = Depends(require_manage_users_request)):
    """Owner only: approve (publish and queue claim extraction) or reject a member upload. Decided once."""
    outcome, uploader, status = await asyncio.to_thread(market_reports_db.set_review, report_id, body.action)
    if outcome == "missing":
        raise HTTPException(status_code=404, detail="Report not found")
    if outcome == "conflict":
        raise HTTPException(status_code=409, detail="Report is not waiting for review")
    await _audit(claims, "U", "report", report_id, {"decision": body.action, "note": body.note, "uploader": uploader})
    return {"id": report_id, "status": status}


@router.get("/{report_id}", **public_data("單一報告內容與其萃取出的主張", "研究報告與主張"))
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
    await _audit(claims, "D", "report", report_id)
    return {"deleted": True}


class ClaimsBody(BaseModel):
    claims: list[dict]
    extracted_by: str


@router.put("/{report_id}/claims")
async def put_claims(
    report_id: str, body: ClaimsBody, background_tasks: BackgroundTasks,
    x_market_agent_key: str | None = Header(None)
):
    _verify_agent(x_market_agent_key)
    try:
        saved = market_reports_db.replace_claims(
            report_id,
            validate_claims(body.claims, market_reports_db.page_count(report_id)),
            body.extracted_by,
            require_pending=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not saved:
        raise HTTPException(status_code=404, detail="Public pending report not found")
    related_codes = sorted({code.strip() for claim in body.claims
                            for code in claim.get("codes", [])
                            if isinstance(code, str) and len(code.strip()) == 4 and code.strip().isdigit()})
    if related_codes:
        background_tasks.add_task(
            market_automation.fire_analysis_event,
            market_automation.automation_store(),
            event_key=f"report:{report_id}:claims",
            codes=related_codes,
            reason=f"研究報告 {report_id} 的主張已完成擷取",
        )
    return {"saved": True, "claim_count": len(body.claims)}
