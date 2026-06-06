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
    """Current position in a single symbol.

    Cost-accounting convention (audit R6, revised BT-3)
    ---------------------------------------------------

    The platform's :class:`feelies.execution.backtest_router.BacktestOrderRouter`
    fills market orders at the **executed cross price** (ask for taker
    buys, bid for taker sells) — the price IB reports — embedding the
    half-spread in the fill price rather than recording it as a separate
    ``spread_cost`` fee (the cost model is called with ``half_spread=0``).
    This means:

    * :attr:`avg_entry_price` is recorded at the **executed cross
      price**, so it INCLUDES the half-spread cost.

    * :attr:`realized_pnl` is computed against ``avg_entry_price`` and
      therefore now INCLUDES the half-spread (a taker round trip realizes
      the full spread in PnL).  ``spread_cost`` no longer flows through
      :attr:`cumulative_fees`, so a consumer reading
      :attr:`cumulative_fees` as "total transaction cost" will *understate*
      cost by the spread; the spread lives in realized/unrealized PnL.
      The platform's NAV calculation (`BasicRiskEngine._compute_current_equity`)
      and the post-trade-forensics analyzer both subtract fees explicitly,
      so platform-internal accounting is self-consistent — but external
      reporting code that pulls :attr:`realized_pnl` directly must
      apply the same fee subtraction.

    * The ``walk-the-book`` partial-fill remainder stacks its
      market-impact premium on top of the cross (above the ask for
      buys, below the bid for sells) and that adverse component is
      likewise reflected in :attr:`avg_entry_price`.  See
      :meth:`BacktestOrderRouter.submit` for the explicit comment.

    * Mark-to-market via :meth:`PositionStore.update_mark` uses the
      next quote's mid.  Because a taker enters at the cross but marks
      at the mid, a flat-to-flat round trip on a quote that never moved
      shows the round-trip spread as a (un)realized PnL loss while
      :attr:`cumulative_fees` carries only commission + regulatory
      charges (the half-spread is now in the price, not the fees).

    Live deployments must mirror this convention (or update both the
    fill model and this docstring together) to preserve Inv-9
    backtest/live parity.
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
