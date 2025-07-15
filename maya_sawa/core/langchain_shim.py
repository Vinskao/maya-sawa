"""langchain_shim.py
A lightweight compatibility wrapper so project code can run even if the
`langchain` / `langchain_openai` packages are not available at runtime.

The real classes will be imported when possible.  Otherwise minimal stub
implementations are provided so that static analysis and runtime imports
won't fail during local development or in constrained build steps.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

__all__ = [
    "Document",
    "LLMChain",
    "PromptTemplate",
    "ChatOpenAI",
]

try:
    from langchain.schema import Document as _Document  # type: ignore
except Exception as exc:  # pragma: no cover
    logger.warning("langchain.schema.Document unavailable – using stub (%s)", exc)

    class _Document:  # type: ignore
        """Minimal stub replacement for langchain.schema.Document"""

        def __init__(self, page_content: str = "", metadata: Dict[str, Any] | None = None):
            self.page_content = page_content
            self.metadata = metadata or {}

    _Document.__module__ = __name__  # help linters

Document = _Document  # type: ignore

# === LLMChain ===
try:
    from langchain.chains import LLMChain as _LLMChain  # type: ignore
except Exception as exc:  # pragma: no cover
    logger.warning("langchain.chains.LLMChain unavailable – using stub (%s)", exc)

    class _LLMChain:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any):
            self.args = args
            self.kwargs = kwargs

        def invoke(self, *args: Any, **kwargs: Any):  # noqa: D401
            raise NotImplementedError("Stub LLMChain invoked. Please install langchain.")

    _LLMChain.__module__ = __name__

LLMChain = _LLMChain  # type: ignore

# === PromptTemplate ===
try:
    from langchain.prompts import PromptTemplate as _PromptTemplate  # type: ignore
except Exception as exc:  # pragma: no cover
    logger.warning("langchain.prompts.PromptTemplate unavailable – using stub (%s)", exc)

    class _PromptTemplate:  # type: ignore
        def __init__(self, input_variables: List[str] | None = None, template: str = ""):
            self.input_variables = input_variables or []
            self.template = template

        def format(self, **kwargs: Any) -> str:  # noqa: D401
            return self.template.format(**kwargs)

    _PromptTemplate.__module__ = __name__

PromptTemplate = _PromptTemplate  # type: ignore

# === ChatOpenAI ===
try:
    from langchain_openai import ChatOpenAI as _ChatOpenAI  # type: ignore
except Exception as exc:  # pragma: no cover
    logger.warning("langchain_openai.ChatOpenAI unavailable – using stub (%s)", exc)

    class _ChatOpenAI:  # type: ignore
        def __init__(self, *args: Any, **kwargs: Any):
            self.args = args
            self.kwargs = kwargs

        def invoke(self, *args: Any, **kwargs: Any):  # noqa: D401
            raise NotImplementedError("Stub ChatOpenAI invoked. Install langchain_openai.")

    _ChatOpenAI.__module__ = __name__

ChatOpenAI = _ChatOpenAI  # type: ignore 