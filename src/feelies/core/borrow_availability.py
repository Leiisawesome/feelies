"""Static per-symbol borrow tiers for backtest short entries.

The enum and parsers live in core so kernel can name them without
importing the execution package.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

_VALID_TIER_LABELS: frozenset[str] = frozenset(
    {
        "available",
        "hard",
        "unavailable",
    }
)


class BorrowTier(Enum):
    """Per-symbol short-locate availability."""

    AVAILABLE = "available"
    HARD = "hard"
    UNAVAILABLE = "unavailable"


def parse_borrow_tier(label: str) -> BorrowTier:
    """Parse a YAML/config tier label; raises ``ValueError`` when unknown."""
    key = label.strip().lower()
    if key not in _VALID_TIER_LABELS:
        raise ValueError(
            f"invalid borrow tier {label!r}; expected one of {sorted(_VALID_TIER_LABELS)}"
        )
    return BorrowTier(key)


def build_borrow_table(raw: Mapping[str, str]) -> dict[str, BorrowTier]:
    """Normalize a config mapping to upper-case symbol → :class:`BorrowTier`."""
    out: dict[str, BorrowTier] = {}
    for sym, tier_label in raw.items():
        sym_u = str(sym).strip().upper()
        if not sym_u:
            raise ValueError("borrow_availability keys must be non-empty symbols")
        out[sym_u] = parse_borrow_tier(str(tier_label))
    return out
