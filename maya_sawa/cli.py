"""Local developer CLI entrypoints for Maya Sawa."""

import uvicorn


def local() -> None:
    """Run the FastAPI app with local development defaults."""
    uvicorn.run(
        "maya_sawa.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="debug",
    )
