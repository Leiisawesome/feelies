"""Root conftest — shared fixtures and environment setup for all tests."""

from __future__ import annotations

import os


def pytest_configure() -> None:
    """Load .env before test collection so POLYGON_API_KEY is available."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if os.getenv("PYTHONIOENCODING") is None:
        os.environ["PYTHONIOENCODING"] = "utf-8"
