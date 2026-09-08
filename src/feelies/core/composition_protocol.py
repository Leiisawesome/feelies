"""CompositionContextError — Layer-3 construct failure.

Raised when a portfolio alpha cannot construct a valid intent. The type
lives in core so the loaded PORTFOLIO module can name it without importing
the composition package.
"""

from __future__ import annotations


class CompositionContextError(Exception):
    """Raised when a portfolio alpha cannot construct a valid intent."""
