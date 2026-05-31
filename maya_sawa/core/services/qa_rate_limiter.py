"""Backward-compatible wrapper for QA endpoints using the shared AI limit."""

from fastapi import Request

from .ai_rate_limiter import enforce_ai_rate_limit


def enforce_qa_rate_limit(request: Request) -> None:
    enforce_ai_rate_limit(request, allow_anonymous=True)
