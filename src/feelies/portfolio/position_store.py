"""Position store interface — shared across backtest and live (invariant 9).

This is the PositionStore interface defined by the system-architect skill.
Mode-specific implementations (broker-backed live, simulated backtest)
live behind ExecutionBackend.

PnL decomposition and attribution: risk-engine skill.
Capital allocation and risk budgets: risk-engine (portfolio governor).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass
class Position:
    """Current position in a single symbol."""

    symbol: str
    quantity: int = 0
    avg_entry_price: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    cumulative_fees: Decimal = Decimal("0")


class PositionStore(Protocol):
    """Read/write interface to position state."""

    def get(self, symbol: str) -> Position:
        """Get current position for a symbol (returns zero-position if absent)."""
        ...

    def update(
        self,
        symbol: str,
        quantity_delta: int,
        fill_price: Decimal,
        fees: Decimal = Decimal("0"),
    ) -> Position:
        """Update position after a fill.  Returns updated position."""
        ...

    def debit_fees(self, symbol: str, fees: Decimal) -> None:
        """Record fees without a fill (e.g. cancel fees)."""
        ...

    def all_positions(self) -> dict[str, Position]:
        """Snapshot of all current positions."""
        ...

    def total_exposure(self) -> Decimal:
        """Gross notional exposure across all positions."""
        ...
