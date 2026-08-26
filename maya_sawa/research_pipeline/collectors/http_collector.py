"""真實 evidence collector（httpx）。

安全邊界都在這裡收斂：URL allowlist、timeout、response 大小上限、
content-type 白名單、以及自己控管的 redirect 驗證。

HTTP client 由外部注入，測試用 httpx.MockTransport，完全不碰真實網路。
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from ..trusted_sources import TrustedSource, get_source, registry_is_resolved

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 512_000
DEFAULT_MAX_REDIRECTS = 3
DEFAULT_MAX_TEXT_CHARS = 2_000

ALLOWED_CONTENT_TYPES = ("text/html", "application/json", "text/plain", "application/xhtml+xml")

_SCRIPT_STYLE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


class FetchRejected(Exception):
    """這一筆 target 被安全規則擋下；跳過該筆，不中斷整個 run。"""


@dataclass(frozen=True)
class EvidenceTarget:
    """要抓取的目標。由設定檔決定，不由 LLM 決定。"""

    source_id: str
    url: str
    rack_part_id: str | None = None
    company: str | None = None
    product: str | None = None

    @property
    def evidence_id(self) -> str:
        return f"{self.source_id}:{self.url}"


def load_targets(path: str | Path) -> list[EvidenceTarget]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return [EvidenceTarget(**entry) for entry in payload]


def validate_url(url: str, source: TrustedSource) -> str:
    """只允許 https、來源 allowlist 內的 host，且不得帶 userinfo 或自訂 port。"""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise FetchRejected(f"只允許 https：{url}")
    if parsed.username or parsed.password:
        raise FetchRejected(f"URL 不得帶帳密：{url}")
    if parsed.port not in (None, 443):
        raise FetchRejected(f"不允許的 port：{url}")
    if not parsed.hostname or not source.allows_host(parsed.hostname):
        raise FetchRejected(
            f"host {parsed.hostname} 不在 {source.source_id} 的 allowlist {list(source.allowed_hosts)}"
        )
    return url


def _check_content_type(response: httpx.Response) -> str:
    content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise FetchRejected(f"不接受的 content-type：{content_type or '(未提供)'}")
    return content_type


def _check_declared_size(response: httpx.Response, max_bytes: int) -> None:
    declared = response.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise FetchRejected(f"response 過大：content-length {declared} > {max_bytes}")


def _read_limited(response: httpx.Response, max_bytes: int) -> bytes:
    body = response.content
    if len(body) > max_bytes:
        raise FetchRejected(f"response 過大：{len(body)} bytes > {max_bytes}")
    return body


def extract_text(body: bytes, content_type: str, *, max_chars: int = DEFAULT_MAX_TEXT_CHARS) -> str:
    """把 HTML/JSON 轉成可以放進 evidence 的短文字。"""
    raw = body.decode("utf-8", errors="replace")

    if content_type == "application/json":
        try:
            text = json.dumps(json.loads(raw), ensure_ascii=False, sort_keys=True)
        except json.JSONDecodeError as exc:
            raise FetchRejected(f"JSON 解析失敗：{exc}") from exc
    else:
        text = _TAG.sub(" ", _SCRIPT_STYLE.sub(" ", raw))
        text = html.unescape(text)

    text = _WHITESPACE.sub(" ", text).strip()
    if not text:
        raise FetchRejected("抓到的內容沒有可用文字")
    return text[:max_chars]


class HttpEvidenceCollector:
    """從可信來源實際抓取 evidence。

    單一 target 失敗只會被跳過並記錄原因；全部失敗時 evidence 為空，
    由 validate_evidence 讓整個 run 失敗（fail closed）。
    """

    is_fixture_source = False

    def __init__(
        self,
        client: httpx.Client,
        targets: Iterable[EvidenceTarget],
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._client = client
        self._targets = list(targets)
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._max_text_chars = max_text_chars
        self._timeout = timeout
        self.last_errors: list[tuple[str, str]] = []

    # --- 抓取 ---------------------------------------------------------
    def _fetch(self, url: str, source: TrustedSource) -> httpx.Response:
        """自己控管 redirect：每一跳都必須重新通過 allowlist 驗證。"""
        current = validate_url(url, source)

        for _ in range(self._max_redirects + 1):
            response = self._client.get(
                current, timeout=self._timeout, follow_redirects=False
            )
            if not response.is_redirect:
                if response.status_code != 200:
                    raise FetchRejected(f"HTTP {response.status_code}")
                return response

            location = response.headers.get("location")
            if not location:
                raise FetchRejected("redirect 缺少 Location")
            current = validate_url(str(response.url.join(location)), source)

        raise FetchRejected(f"redirect 次數超過上限 {self._max_redirects}")

    def _collect_one(self, target: EvidenceTarget) -> dict[str, Any]:
        source = get_source(target.source_id)
        if source is None:
            raise FetchRejected(f"來源 {target.source_id} 不在信任清單")

        response = self._fetch(target.url, source)
        content_type = _check_content_type(response)
        _check_declared_size(response, self._max_bytes)
        body = _read_limited(response, self._max_bytes)

        return {
            "evidenceId": target.evidence_id,
            "sourceId": target.source_id,
            # 記錄最終 URL，讓審核者看到真正被引用的位置。
            "sourceUrl": str(response.url),
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "rackPartId": target.rack_part_id,
            "company": target.company,
            "product": target.product,
            "evidenceText": extract_text(body, content_type, max_chars=self._max_text_chars),
            "confidence": "high" if source.trust_level == "primary" else "medium",
        }

    def collect(self, run_id: str, current_mapping: dict[str, Any]) -> list[dict[str, Any]]:
        if not registry_is_resolved():
            # registry 尚未完成設定時不允許真實抓取。
            raise FetchRejected("trusted source registry 尚未完成設定")

        self.last_errors = []
        evidence: list[dict[str, Any]] = []

        for target in self._targets:
            try:
                evidence.append(self._collect_one(target))
            except (FetchRejected, httpx.HTTPError) as exc:
                self.last_errors.append((target.evidence_id, str(exc)))
                logger.warning("run %s 跳過 evidence target %s：%s", run_id, target.url, exc)

        return evidence
