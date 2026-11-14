"""Mark-rail protocol. contracts.md §1. P-10."""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import MarkRailUpdate, NBBOQuote
from feelies.core.quote_quality import QuoteQuality


class MarkRailProtocol(Protocol):
    """Quote to rail update. contracts.md §1. P-10."""

    def on_quote(self, quote: NBBOQuote, *, quality: QuoteQuality) -> MarkRailUpdate:
        """Return the rail update for one quote."""
        ...
