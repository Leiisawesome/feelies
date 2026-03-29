"""Per-strategy position store with aggregate view.

Wraps multiple per-strategy ``MemoryPositionStore`` instances behind
a composite that provides both strategy-level and aggregate-level
access.  The aggregate view satisfies the ``PositionStore`` protocol,
so the risk engine and orchestrator signatures don't change.

Design: composite pattern.
  - ``get(strategy_id, symbol)`` — strategy-level position
  - ``get_aggregate(symbol)`` — net position across all strategies
  - The aggregate view (accessed via ``as_aggregate()``) implements
    ``PositionStore`` for backward compatibility with the risk engine.
"""

from __future__ import annotations

from decimal import Decimal

from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.portfolio.position_store import Position


class StrategyPositionStore:
    """Per-strategy position isolation with aggregate view.

    Each strategy gets its own position book.  The aggregate view
    sums across strategies for risk checks.
    """

    def __init__(self) -> None:
        self._stores: dict[str, MemoryPositionStore] = {}
        self._aggregate = _AggregateView(self)

    def _get_store(self, strategy_id: str) -> MemoryPositionStore:
        store = self._stores.get(strategy_id)
        if store is None:
            store = MemoryPositionStore()
            self._stores[strategy_id] = store
        return store

    def get(self, strategy_id: str, symbol: str) -> Position:
        """Get position for a specific strategy + symbol."""
        return self._get_store(strategy_id).get(symbol)

    def update(
        self,
        strategy_id: str,
        symbol: str,
        quantity_delta: int,
        fill_price: Decimal,
        fees: Decimal = Decimal("0"),
    ) -> Position:
        """Update position for a specific strategy."""
        return self._get_store(strategy_id).update(symbol, quantity_delta, fill_price, fees=fees)

    def get_aggregate(self, symbol: str) -> Position:
        """Net position across all strategies for a symbol.

        ``avg_entry_price`` is a position-size-weighted average across
        strategies, not a true cost basis.  For multi-strategy
        reconciliation, use per-strategy positions via ``get()``.
        """
        total_qty = 0
        total_cost = Decimal("0")
        total_realized = Decimal("0")
        total_unrealized = Decimal("0")
        total_fees = Decimal("0")

        for store in self._stores.values():
            pos = store.get(symbol)
            total_realized += pos.realized_pnl
            total_unrealized += pos.unrealized_pnl
            total_fees += pos.cumulative_fees
            if pos.quantity != 0:
                total_qty += pos.quantity
                total_cost += pos.avg_entry_price * abs(pos.quantity)

        avg_price = total_cost / abs(total_qty) if total_qty != 0 else Decimal("0")

        return Position(
            symbol=symbol,
            quantity=total_qty,
            avg_entry_price=avg_price,
            realized_pnl=total_realized,
            unrealized_pnl=total_unrealized,
            cumulative_fees=total_fees,
        )

    def all_aggregate_positions(self) -> dict[str, Position]:
        """Aggregate positions across all strategies, keyed by symbol."""
        symbols: set[str] = set()
        for store in self._stores.values():
            symbols.update(store.all_positions().keys())
        return {sym: self.get_aggregate(sym) for sym in symbols}

    def total_exposure(self) -> Decimal:
        """Gross notional exposure across all strategies."""
        total = Decimal("0")
        for store in self._stores.values():
            total += store.total_exposure()
        return total

    def get_strategy_exposure(self, strategy_id: str) -> Decimal:
        """Gross notional exposure for a single strategy across all symbols."""
        store = self._stores.get(strategy_id)
        if store is None:
            return Decimal("0")
        return store.total_exposure()

    def get_strategy_realized_pnl(self, strategy_id: str) -> Decimal:
        """Total realized PnL for a single strategy across all symbols.

        Used by AlphaBudgetRiskWrapper for per-alpha drawdown
        enforcement.  Returns Decimal("0") if the strategy has no
        positions.
        """
        store = self._stores.get(strategy_id)
        if store is None:
            return Decimal("0")
        return sum(
            (pos.realized_pnl for pos in store.all_positions().values()),
            Decimal("0"),
        )

    def get_strategy_cumulative_fees(self, strategy_id: str) -> Decimal:
        """Total cumulative fees for a single strategy across all symbols.

        Used by AlphaBudgetRiskWrapper for per-alpha drawdown
        enforcement (net equity = budget + pnl - fees).
        """
        store = self._stores.get(strategy_id)
        if store is None:
            return Decimal("0")
        return sum(
            (pos.cumulative_fees for pos in store.all_positions().values()),
            Decimal("0"),
        )

    def strategy_ids(self) -> frozenset[str]:
        """Set of all strategy IDs with positions."""
        return frozenset(self._stores.keys())

    def as_aggregate(self) -> _AggregateView:
        """Return a PositionStore-compatible aggregate view.

        The risk engine and orchestrator can use this without knowing
        about per-strategy isolation.
        """
        return self._aggregate


class _AggregateView:
    """PositionStore protocol adapter over StrategyPositionStore aggregate."""

    __slots__ = ("_parent",)

    def __init__(self, parent: StrategyPositionStore) -> None:
        self._parent = parent

    def get(self, symbol: str) -> Position:
        return self._parent.get_aggregate(symbol)

    def update(
        self,
        symbol: str,
        quantity_delta: int,
        fill_price: Decimal,
        fees: Decimal = Decimal("0"),
    ) -> Position:
        raise RuntimeError(
            "Cannot update aggregate view directly — use "
            "StrategyPositionStore.update(strategy_id, symbol, ...) instead"
        )

    def all_positions(self) -> dict[str, Position]:
        return self._parent.all_aggregate_positions()

    def total_exposure(self) -> Decimal:
        return self._parent.total_exposure()
