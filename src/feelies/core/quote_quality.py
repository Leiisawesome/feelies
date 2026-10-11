"""Quote quality for the book mark. One pure rule, no market-data imports."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum, auto


class QuoteQuality(Enum):
    """NBBO quality, checked in order NONPOS, CROSSED, LOCKED, ZERO_SZ, else VALID."""

    VALID = auto()
    NONPOS = auto()
    CROSSED = auto()
    LOCKED = auto()
    ZERO_SZ = auto()


def classify(bid: Decimal, ask: Decimal, bid_size: int, ask_size: int) -> QuoteQuality:
    """Classify one quote. Earlier classes win."""
    if bid <= 0 or ask <= 0:
        return QuoteQuality.NONPOS
    if bid > ask:
        return QuoteQuality.CROSSED
    if bid == ask:
        return QuoteQuality.LOCKED
    if bid_size == 0 or ask_size == 0:
        return QuoteQuality.ZERO_SZ
    return QuoteQuality.VALID
