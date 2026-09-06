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
    """Current position and PnL for one symbol.

    Taker fills use the executed cross price, so spread and depth impact live in
    entry price and realized/unrealized PnL. ``cumulative_fees`` contains only
    explicit fees and therefore is not total transaction cost. Live and
    backtest implementations must use the same convention.
    """

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
        timestamp_ns: int | None = None,
    ) -> Position:
        """Update position after a fill.  Returns updated position.

        Optional ``timestamp_ns`` records the fill time. When provided and the update
        causes a flat → non-zero transition, the implementation records
        the timestamp under :meth:`opened_at_ns` for the symbol.  When
        omitted, position-age tracking is disabled for that fill.
        """
        ...

    def debit_fees(self, symbol: str, fees: Decimal) -> None:
        """Record fees without a fill (e.g. cancel fees)."""
        ...

    def update_mark(
        self,
        symbol: str,
        mark_price: Decimal,
        *,
        bid: Decimal | None = None,
        ask: Decimal | None = None,
    ) -> None:
        """Record the latest mark price for a symbol.

        The mark price is used to compute unrealized PnL and a
        mark-to-market view of ``total_exposure``.  Callers should feed
        a mark on every quote so risk checks see live exposure rather
        than cost-basis exposure.  Implementations must be cheap — this
        is called on the hot quote path.

        When ``bid`` and ``ask`` are supplied, implementations may use
        side-specific liquidation prices (longs mark to bid, shorts mark
        to ask) instead of mid-only marks.
        """
        ...

    def all_positions(self) -> dict[str, Position]:
        """Snapshot of all current positions."""
        ...

    def total_exposure(self) -> Decimal:
        """Gross notional exposure across all positions.

        Implementations should use the latest mark price when available
        (see ``update_mark``) and fall back to ``avg_entry_price`` only
        when no mark has been recorded for the symbol.
        """
        ...

    def opened_at_ns(self, symbol: str) -> int | None:
        """Timestamp (ns) of the start of the current open episode.

        Returns ``None`` when the symbol is currently flat or has never
        been filled.  When a position is closed (``quantity → 0``) and
        later reopened, or when a single fill crosses through zero and
        flips the position sign, the returned timestamp reflects the
        **most recent** open episode — never the original.

        Hazard exits use this to enforce ``min_age_seconds`` and the optional
        ``hard_exit_age_seconds`` reconciliation guard (§20.7.3).

        Implementations that do not track this must return ``None`` so the
        hazard controller falls back to no minimum age.
        """
        ...

    def latest_mark(self, symbol: str) -> Decimal | None:
        """Return the most recent mark recorded via :meth:`update_mark`.

        Returns ``None`` when no mark has been recorded for ``symbol``.
        Used by the risk engine to translate intent
        ``target_usd`` into share counts (see
        :meth:`feelies.risk.basic_risk.BasicRiskEngine.check_sized_intent`).
        """
        ...
