"""StrategyPositionStore — injected per-strategy position protocol.

The Protocol lives in core so kernel can name it without importing the
portfolio package.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from feelies.core.position import Position


class StrategyPositionStore(Protocol):
    """Injected slice book. Kernel names get, update, debit_fees, update_mark, strategy_ids."""

    def get(self, strategy_id: str, symbol: str) -> Position:
        """Get position for a specific strategy + symbol."""
        ...

    def update(
        self,
        strategy_id: str,
        symbol: str,
        quantity_delta: int,
        fill_price: Decimal,
        fees: Decimal = Decimal("0"),
        timestamp_ns: int | None = None,
    ) -> Position:
        """Update position for a specific strategy."""
        ...

    def debit_fees(
        self,
        strategy_id: str,
        symbol: str,
        fees: Decimal,
    ) -> None:
        """Record fees for a specific strategy + symbol without a fill."""
        ...

    def update_mark(
        self,
        symbol: str,
        mark_price: Decimal,
        *,
        bid: Decimal | None = None,
        ask: Decimal | None = None,
    ) -> None:
        """Propagate a mark price to every per-strategy book."""
        ...

    def strategy_ids(self) -> frozenset[str]:
        """Set of all strategy IDs with positions."""
        ...
