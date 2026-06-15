"""Command-line entry points for Maya Sawa."""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="maya", description="Run the Maya Sawa API server.")
    parser.add_argument("--host", default="0.0.0.0", help="Host interface to bind.")
    parser.add_argument("--port", default=8000, type=int, help="Port to bind.")
    parser.add_argument("--log-level", default="debug", help="Uvicorn log level.")
    parser.add_argument(
        "--no-reload",
        action="store_true",
        help="Disable auto-reload for local development.",
    )
    args = parser.parse_args()

    uvicorn.run(
        "maya_sawa.main:app",
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        reload=not args.no_reload,
    )
