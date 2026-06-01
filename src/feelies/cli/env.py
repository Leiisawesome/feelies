"""Environment bootstrap for operator scripts (backtest, paper, tests)."""

from __future__ import annotations

import os

MASSIVE_API_KEY_ENV = "MASSIVE_API_KEY"

MASSIVE_API_KEY_ERROR = (
    "ERROR: MASSIVE_API_KEY not set.\n"
    "Set it in your environment or in a .env file.\n"
    "  export MASSIVE_API_KEY=your_key_here"
)


def load_dotenv_optional() -> None:
    """Load a local ``.env`` when ``python-dotenv`` is installed."""
    try:
        from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
        load_dotenv()
    except ImportError:
        pass


def massive_api_key_from_env() -> str | None:
    """Return ``MASSIVE_API_KEY`` when set and non-empty."""
    value = os.getenv(MASSIVE_API_KEY_ENV)
    if value is None or not value.strip():
        return None
    return value
