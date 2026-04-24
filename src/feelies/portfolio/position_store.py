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
        timestamp_ns: int | None = None,
    ) -> Position:
        """Update position after a fill.  Returns updated position.

        ``timestamp_ns`` (Phase-4-finalize, optional) records the wall-
        time of the underlying fill.  When provided and the update
        causes a flat → non-zero transition, the implementation records
        the timestamp under :meth:`opened_at_ns` for the symbol.  When
        omitted, position-age tracking is disabled for that fill (Inv-A
        legacy callers see no behavioural change).
        """
        ...

    def debit_fees(self, symbol: str, fees: Decimal) -> None:
        """Record fees without a fill (e.g. cancel fees)."""
        ...

    def update_mark(self, symbol: str, mark_price: Decimal) -> None:
        """Record the latest mark price for a symbol.

        The mark price is used to compute unrealized PnL and a
        mark-to-market view of ``total_exposure``.  Callers should feed
        a mark on every quote so risk checks see live exposure rather
        than cost-basis exposure.  Implementations must be cheap — this
        is called on the hot quote path.
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
        """Timestamp (ns) of the fill that took ``symbol`` from flat → non-zero.

        Returns ``None`` when the symbol is currently flat or has never
        been filled.  When a position is closed (``quantity → 0``) and
        later reopened, the returned timestamp reflects the **most
        recent** open — never the original.

        Phase-4-finalize uses this to enforce the hazard-exit
        ``min_age_seconds`` safeguard and the optional
        ``hard_exit_age_seconds`` reconciliation guard (§20.7.3).

        Implementations that do not track this MUST return ``None`` so
        the hazard controller falls back to the no-min-age behaviour
        (Inv-A: legacy v0.2 deployments unaffected).
        """
        ...

    def latest_mark(self, symbol: str) -> Decimal | None:
        """Return the most recent mark recorded via :meth:`update_mark`.

        Returns ``None`` when no mark has been recorded for ``symbol``.
        Used by the Phase-4 risk-engine helper to translate intent
        ``target_usd`` into share counts (see
        :meth:`feelies.risk.basic_risk.BasicRiskEngine.check_sized_intent`).
        """
        ...
