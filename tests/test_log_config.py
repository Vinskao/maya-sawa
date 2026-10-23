"""Request URLs must not reach the logs: OpenDART takes its key as the crtfc_key query parameter.

On 2026-10-23 the pod log showed httpx's INFO line
'HTTP Request: GET https://opendart.fss.or.kr/api/list.json?...&crtfc_key=<key> "HTTP/1.1 200 OK"'.
"""
import logging

from maya_sawa.core.log_config import configure_logging


def test_http_client_request_lines_with_query_keys_are_not_logged(caplog):
    configure_logging()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("httpx").info('HTTP Request: GET https://opendart.fss.or.kr/api/list.json?crtfc_key=secret "HTTP/1.1 200 OK"')
        logging.getLogger("httpcore.http11").debug("receive_response_headers.complete")
        logging.getLogger("maya_sawa.services.dart_financials").info("OpenDART: stored 3 reports")
    assert "secret" not in caplog.text
    assert "receive_response_headers" not in caplog.text
    assert "OpenDART: stored 3 reports" in caplog.text  # the app's own logs still come through
    # Failures stay visible.
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("httpx").warning("connection reset")
    assert "connection reset" in caplog.text
