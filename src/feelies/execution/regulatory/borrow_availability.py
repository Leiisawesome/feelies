"""Static per-symbol borrow-availability tiers for backtest short entries (BT-7).

Lightweight locate model: a symbol is ``available`` (easy to borrow — no HTB
fee), ``hard`` (HTB fee path when ``cost_htb_borrow_annual_bps > 0``), or
``unavailable`` (short entries refused with ``LOCATE_UNAVAILABLE``).  Symbols
omitted from the table default to ``available`` (conservative for large-cap
universes).  No intraday rate-spike or dynamic locate modeling.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum

from feelies.core.events import SignalDirection
from feelies.execution.intent import OrderIntent, TradingIntent

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


def is_short_sale_intent(intent: OrderIntent) -> bool:
    """True when the order would open or increase SHORT exposure.

    Shared by SSR (BT-6) and borrow-availability (BT-7) gates: only these
    intents are short *sales* subject to Reg-SHO / locate constraints.  Buys,
    covers, and long-side exits are never short sales.
    """
    if intent.intent in (
        TradingIntent.ENTRY_SHORT,
        TradingIntent.REVERSE_LONG_TO_SHORT,
    ):
        return True
    return (
        intent.intent == TradingIntent.SCALE_UP
        and intent.signal.direction == SignalDirection.SHORT
    )


def htb_fee_applies(tier: BorrowTier, short_sale: bool) -> bool:
    """True when the fill should carry ``OrderRequest.is_short`` for HTB fees."""
    return short_sale and tier == BorrowTier.HARD
