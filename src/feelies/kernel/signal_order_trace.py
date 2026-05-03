"""Per-signal diagnostics for the standalone SIGNAL → order pipeline.

Used when operators need an explicit audit trail of why each bus-emitted
:class:`~feelies.core.events.Signal` did or did not produce an
:class:`~feelies.core.events.OrderRequest` on its quote tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["SignalOrderTraceRow"]


@dataclass(frozen=True, slots=True)
class SignalOrderTraceRow:
    """One row per :class:`~feelies.core.events.Signal` evaluated on a quote."""

    quote_timestamp_ns: int
    quote_correlation_id: str
    quote_sequence: int
    signal_sequence: int
    signal_timestamp_ns: int
    strategy_id: str
    symbol: str
    signal_direction: str
    trading_intent: str
    outcome: Literal["ORDER_SUBMITTED", "NO_ORDER"]
    reasons: tuple[str, ...]
