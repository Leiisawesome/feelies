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

    os.environ.setdefault("HYPOTHESIS_STORAGE_DIRECTORY", "/tmp/hypothesis-feelies")
    try:
        from hypothesis import settings as h_settings, database as h_db
        h_settings.register_profile(
            "ci", database=h_db.DirectoryBasedExampleDatabase("/tmp/hypothesis-feelies")
        )
        h_settings.load_profile("ci")
    except ImportError:
        pass
