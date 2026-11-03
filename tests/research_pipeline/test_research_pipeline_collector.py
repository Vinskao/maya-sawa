"""HTTP evidence collector 測試。

全部使用 httpx.MockTransport，不會發出任何真實網路請求。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from maya_sawa.research_pipeline.collectors import (
    EvidenceTarget,
    FetchRejected,
    HttpEvidenceCollector,
    extract_text,
    load_targets,
    validate_url,
)
from maya_sawa.research_pipeline.collectors.http_collector import DEFAULT_MAX_BYTES
from maya_sawa.research_pipeline.schemas import parse_evidence_list
from maya_sawa.research_pipeline.trusted_sources import get_source
from maya_sawa.research_pipeline.validation import validate_evidence

FIXTURES = Path("maya_sawa/research_pipeline/fixtures")
SOURCES = FIXTURES / "sources"

DELTA_URL = "https://www.deltaww.com/en-US/products/dc-dc-power-module"
VICOR_URL = "https://www.vicorpower.com/api/products/fpa.json"

DELTA_TARGET = EvidenceTarget(
    source_id="delta-official",
    url=DELTA_URL,
    company="Delta Electronics",
    product="800V→48V DC-DC power module",
)
VICOR_TARGET = EvidenceTarget(
    source_id="vicor-official",
    url=VICOR_URL,
    company="Vicor",
    product="Factorized Power (FPA) modules",
)


def html_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=(SOURCES / "delta_dc_dc.html").read_bytes(),
        headers={"content-type": "text/html; charset=utf-8"},
        request=request,
    )


def json_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        content=(SOURCES / "vicor_fpa.json").read_bytes(),
        headers={"content-type": "application/json"},
        request=request,
    )


def make_collector(handler, targets, **kwargs) -> HttpEvidenceCollector:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpEvidenceCollector(client, targets, **kwargs)


def default_handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "www.deltaww.com":
        return html_response(request)
    if request.url.host == "www.vicorpower.com":
        return json_response(request)
    return httpx.Response(404, request=request)


# --- URL allowlist --------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://www.deltaww.com/x",  # 非 https
        "https://evil.example.com/x",  # host 不在 allowlist
        "https://www.deltaww.com.evil.com/x",  # 近似網域
        "https://user:pw@www.deltaww.com/x",  # 帶帳密
        "https://www.deltaww.com:8443/x",  # 自訂 port
    ],
)
def test_validate_url_rejects_unsafe_urls(url):
    with pytest.raises(FetchRejected):
        validate_url(url, get_source("delta-official"))


def test_validate_url_accepts_allowlisted_host():
    assert validate_url(DELTA_URL, get_source("delta-official")) == DELTA_URL


# --- 解析 -----------------------------------------------------------------


def test_extract_text_strips_script_style_and_tags():
    text = extract_text((SOURCES / "delta_dc_dc.html").read_bytes(), "text/html")

    assert "800V to 48V DC-DC Power Module" in text  # &nbsp; 已還原
    assert "window.analytics" not in text
    assert "display: none" not in text
    assert "<" not in text


def test_extract_text_rejects_malformed_json():
    with pytest.raises(FetchRejected):
        extract_text(b"{not json", "application/json")


def test_extract_text_truncates():
    assert len(extract_text(b"<p>" + b"a" * 5000 + b"</p>", "text/html", max_chars=100)) == 100


# --- 正常抓取 -------------------------------------------------------------


def test_collect_produces_valid_evidence():
    collector = make_collector(default_handler, [DELTA_TARGET, VICOR_TARGET])
    raw = collector.collect("run-1", {})

    assert collector.last_errors == []
    assert len(raw) == 2

    evidence = parse_evidence_list(raw)
    assert validate_evidence(evidence).is_valid

    delta = evidence[0]
    assert delta.source_id == "delta-official"
    assert delta.source_url == DELTA_URL
    assert delta.company == "Delta Electronics"
    assert delta.confidence == "high"
    assert "48VDC rack busbar" in delta.evidence_text

    assert "Factorized Power" in evidence[1].evidence_text


def test_configured_targets_file_is_loadable():
    targets = load_targets(FIXTURES / "evidence_targets.json")
    assert {target.source_id for target in targets} <= {
        "delta-official",
        "vicor-official",
        "infineon-official",
    }


# --- 逐筆失敗都只跳過該筆 -------------------------------------------------


def _assert_skipped(collector, reason_fragment: str):
    assert collector.collect("run-1", {}) == []
    assert len(collector.last_errors) == 1
    assert reason_fragment in collector.last_errors[0][1]


def test_untrusted_host_is_skipped():
    target = EvidenceTarget(source_id="delta-official", url="https://evil.example.com/x")
    _assert_skipped(make_collector(default_handler, [target]), "allowlist")


def test_unknown_source_is_skipped():
    target = EvidenceTarget(source_id="random-blog", url="https://blog.example.com/x")
    _assert_skipped(make_collector(default_handler, [target]), "信任清單")


def test_unexpected_content_type_is_skipped():
    def handler(request):
        return httpx.Response(
            200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}, request=request
        )

    _assert_skipped(make_collector(handler, [DELTA_TARGET]), "content-type")


def test_declared_oversized_response_is_skipped():
    def handler(request):
        return httpx.Response(
            200,
            content=b"<p>ok</p>",
            headers={
                "content-type": "text/html",
                "content-length": str(DEFAULT_MAX_BYTES + 1),
            },
            request=request,
        )

    _assert_skipped(make_collector(handler, [DELTA_TARGET]), "content-length")


def test_actual_oversized_body_is_skipped():
    def handler(request):
        return httpx.Response(
            200, content=b"a" * 5000, headers={"content-type": "text/html"}, request=request
        )

    _assert_skipped(make_collector(handler, [DELTA_TARGET], max_bytes=1000), "過大")


def test_non_200_is_skipped():
    def handler(request):
        return httpx.Response(500, request=request)

    _assert_skipped(make_collector(handler, [DELTA_TARGET]), "HTTP 500")


def test_timeout_is_skipped():
    def handler(request):
        raise httpx.ConnectTimeout("timeout", request=request)

    _assert_skipped(make_collector(handler, [DELTA_TARGET]), "timeout")


# --- redirect -------------------------------------------------------------


def test_redirect_within_allowlist_is_followed():
    final_url = "https://www.deltaww.com/en-US/products/dc-dc-power-module-v2"

    def handler(request):
        if str(request.url) == DELTA_URL:
            return httpx.Response(301, headers={"location": final_url}, request=request)
        return html_response(request)

    collector = make_collector(handler, [DELTA_TARGET])
    evidence = collector.collect("run-1", {})

    assert collector.last_errors == []
    # sourceUrl 記錄最終位置，審核者看到的是真正被引用的頁面。
    assert evidence[0]["sourceUrl"] == final_url


def test_redirect_to_untrusted_host_is_skipped():
    def handler(request):
        return httpx.Response(
            302, headers={"location": "https://evil.example.com/x"}, request=request
        )

    _assert_skipped(make_collector(handler, [DELTA_TARGET]), "allowlist")


def test_redirect_loop_is_skipped():
    def handler(request):
        return httpx.Response(302, headers={"location": DELTA_URL}, request=request)

    _assert_skipped(make_collector(handler, [DELTA_TARGET], max_redirects=2), "redirect 次數")


def test_redirect_without_location_is_skipped():
    def handler(request):
        return httpx.Response(302, request=request)

    _assert_skipped(make_collector(handler, [DELTA_TARGET]), "Location")


# --- fail closed ----------------------------------------------------------


def test_all_targets_failing_yields_invalid_evidence():
    def handler(request):
        return httpx.Response(503, request=request)

    collector = make_collector(handler, [DELTA_TARGET, VICOR_TARGET])
    evidence = parse_evidence_list(collector.collect("run-1", {}))

    assert evidence == []
    assert not validate_evidence(evidence).is_valid


def test_collector_refuses_when_registry_unresolved(monkeypatch):
    monkeypatch.setattr(
        "maya_sawa.research_pipeline.collectors.http_collector.registry_is_resolved",
        lambda: False,
    )
    collector = make_collector(default_handler, [DELTA_TARGET])
    with pytest.raises(FetchRejected):
        collector.collect("run-1", {})
