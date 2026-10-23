"""Process-wide logging setup (called once from main.py; covered by tests/test_log_config.py).

The app logs at DEBUG, but the HTTP client libraries log every request URL at INFO and every header exchange at
DEBUG. OpenDART takes its key as the crtfc_key query parameter, so those lines would put the key in the pod log
(seen 2026-10-23). They are kept to warnings and errors, which carry no request line.
"""
import logging

URL_LOGGERS = ("httpx", "httpcore", "urllib3", "requests")


def configure_logging() -> None:
    logging.basicConfig(level=logging.DEBUG)
    for name in URL_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
