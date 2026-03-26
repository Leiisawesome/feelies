"""Exit-priority order aggregation for multi-alpha intents.

When multiple alphas generate orders for the same symbol in the same
tick, intents are aggregated into net orders via two-bucket logic:

  Bucket 1 — Exits (position-reducing):
    Always generate orders.  Never cancelled by opposing entries.

  Bucket 2 — Entries (position-opening):
    Netted across alphas per symbol.

Reversals are split: the exit component goes to bucket 1, the entry
component to bucket 2.

Invariants preserved:
  - Inv 5 (deterministic): aggregation order is deterministic
  - Inv 11 (fail-safe): exits are non-cancellable
"""

from __future__ import annotations

from dataclasses import dataclass

from feelies.core.events import Side
from feelies.execution.intent import OrderIntent, TradingIntent


@dataclass(frozen=True)
class AggregatedOrders:
    """Result of exit-priority intent aggregation for a single symbol."""

    exit_order: tuple[Side, int] | None
    entry_order: tuple[Side, int] | None
    contributing_intents: tuple[OrderIntent, ...]


def _to_signed_quantity(intent: OrderIntent) -> int:
    """Convert an OrderIntent to a signed quantity for aggregation.

    Exhaustiveness guard: raises ValueError for unhandled intent
    types (Inv-11 fail-safe).
    """
    if intent.intent == TradingIntent.ENTRY_LONG:
        return intent.target_quantity
    if intent.intent == TradingIntent.ENTRY_SHORT:
        return -intent.target_quantity
    if intent.intent == TradingIntent.SCALE_UP:
        if intent.current_quantity >= 0:
            return intent.target_quantity
        return -intent.target_quantity
    if intent.intent == TradingIntent.EXIT:
        if intent.current_quantity > 0:
            return -intent.target_quantity
        if intent.current_quantity < 0:
            return intent.target_quantity
        return 0

    raise ValueError(
        f"Unhandled TradingIntent in _to_signed_quantity: "
        f"{intent.intent!r}. Fail-safe: aborting aggregation."
    )


def aggregate_intents(
    intents: tuple[OrderIntent, ...],
) -> dict[str, AggregatedOrders]:
    """Aggregate per-alpha intents with exit priority.

    NO_ACTION intents are excluded from contributing_intents to
    keep the provenance trail clean (v2.3).
    """
    by_symbol: dict[str, list[OrderIntent]] = {}
    for intent in intents:
        by_symbol.setdefault(intent.symbol, []).append(intent)

    result: dict[str, AggregatedOrders] = {}
    for symbol, sym_intents in by_symbol.items():
        exit_qty = 0
        entry_qty = 0

        for intent in sym_intents:
            if intent.intent == TradingIntent.NO_ACTION:
                continue

            if intent.intent == TradingIntent.REVERSE_LONG_TO_SHORT:
                exit_qty -= intent.current_quantity
                entry_qty -= (
                    intent.target_quantity - intent.current_quantity
                )
            elif intent.intent == TradingIntent.REVERSE_SHORT_TO_LONG:
                exit_qty += abs(intent.current_quantity)
                entry_qty += (
                    intent.target_quantity - abs(intent.current_quantity)
                )
            elif intent.intent == TradingIntent.EXIT:
                exit_qty += _to_signed_quantity(intent)
            else:
                entry_qty += _to_signed_quantity(intent)

        exit_order = None
        if exit_qty != 0:
            side = Side.BUY if exit_qty > 0 else Side.SELL
            exit_order = (side, abs(exit_qty))

        entry_order = None
        if entry_qty != 0:
            side = Side.BUY if entry_qty > 0 else Side.SELL
            entry_order = (side, abs(entry_qty))

        active_intents = tuple(
            i for i in sym_intents
            if i.intent != TradingIntent.NO_ACTION
        )

        result[symbol] = AggregatedOrders(
            exit_order=exit_order,
            entry_order=entry_order,
            contributing_intents=active_intents,
        )

    return result
