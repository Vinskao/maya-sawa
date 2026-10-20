"""PDF text extraction and page-preserving chunks for market research reports."""

from __future__ import annotations

import hashlib
import re
from io import BytesIO

from pypdf import PdfReader

MAX_REPORT_BYTES = 40 * 1024 * 1024
CHUNK_CHARS = 800
SEGMENTS = {
    "foundry",
    "memory",
    "packaging",
    "abf",
    "ccl_pcb",
    "thermal",
    "optical",
    "odm",
    "csp",
    "macro",
}
DIMENSIONS = {"cycle", "technology", "delivery", "macro", "timing"}
DIRECTIONS = {"tailwind", "neutral", "headwind"}


class PDFTextExtractionError(ValueError):
    def __init__(self, message: str, page_count: int = 0):
        super().__init__(message)
        self.page_count = page_count


def validate_pdf(filename: str, content_type: str, data: bytes) -> None:
    if (
        content_type.lower().split(";")[0].strip() != "application/pdf"
        or not filename.lower().endswith(".pdf")
        or not data.startswith(b"%PDF-")
    ):
        raise ValueError("Only valid PDF files are accepted")
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("PDF must be 40 MB or smaller")


def extract_pdf_pages(data: bytes) -> list[str]:
    try:
        reader = PdfReader(BytesIO(data), strict=False)
    except Exception as exc:
        raise PDFTextExtractionError("PDF could not be read") from exc
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    if not pages or not any(pages):
        raise PDFTextExtractionError(
            "PDF has no text layer; OCR is required", len(pages)
        )
    return pages


def chunk_pages(pages: list[str], max_chars: int = CHUNK_CHARS) -> list[dict]:
    chunks = []
    for page_number, page in enumerate(pages, 1):
        sentences = re.split(r"(?<=[.!?。！？])\s+", re.sub(r"\s+", " ", page).strip())
        current = ""
        for sentence in filter(None, sentences):
            # Keep each sentence intact, even when a single sentence exceeds the target size.
            if current and len(current) + 1 + len(sentence) > max_chars:
                chunks.append(
                    {"page": page_number, "seq": len(chunks), "text": current}
                )
                current = ""
            current = f"{current} {sentence}".strip()
        if current:
            chunks.append({"page": page_number, "seq": len(chunks), "text": current})
    return chunks


def report_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def report_for_viewer(
    report: dict, viewer_sub: str | None, *, include_text: bool = False
) -> dict | None:
    if report.get("visibility") == "owner" and viewer_sub != report.get("uploaded_by"):
        return None
    return {
        key: value
        for key, value in report.items()
        if key not in {"pdf", "uploaded_by"} and (include_text or key != "text")
    }


def validate_claims(claims: list[dict], page_count: int) -> list[dict]:
    if not isinstance(claims, list) or len(claims) > 1000:
        raise ValueError("claims must be a list of at most 1000 items")
    result = []
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("claim must be an object")
        page = claim.get("page")
        if not isinstance(page, int) or not 1 <= page <= page_count:
            raise ValueError("claim page is outside report page range")
        if (
            claim.get("segment") not in SEGMENTS
            or claim.get("dimension") not in DIMENSIONS
            or claim.get("direction") not in DIRECTIONS
        ):
            raise ValueError("invalid claim segment, dimension, or direction")
        codes = claim.get("codes", [])
        if not isinstance(codes, list) or any(
            not isinstance(code, str) or len(code) > 24 for code in codes
        ):
            raise ValueError("claim codes must be a list of short strings")
        for key in ("claim", "evidence"):
            if (
                not isinstance(claim.get(key), str)
                or not claim[key].strip()
                or len(claim[key]) > 2000
            ):
                raise ValueError(
                    f"claim {key} is required and must be at most 2000 characters"
                )
        result.append({**claim, "codes": codes})
    return result
