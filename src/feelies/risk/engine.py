"""Risk engine protocol — the sole gatekeeper between signal and execution.

The risk engine is independent and dominant.  It can veto any order
and trigger risk lockdown.  No strategy layer can bypass it (invariant 11).

Every order intent transits the risk engine; no direct
signal-to-execution path exists.
"""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import (
    OrderRequest,
    RiskVerdict,
    Signal,
    SizedPositionIntent,
)
from feelies.portfolio.position_store import PositionStore


class RiskEngine(Protocol):
    """Validates proposed actions against risk constraints.

    Checks performed per the system diagram's RISK_CHECK step:
      - Position limits
      - Volatility scaling
      - Drawdown guard
      - Regime throttle
    """

    def check_signal(
        self,
        signal: Signal,
        positions: PositionStore,
    ) -> RiskVerdict:
        """Evaluate whether a signal may proceed to order generation."""
        ...

    def check_order(
        self,
        order: OrderRequest,
        positions: PositionStore,
    ) -> RiskVerdict:
        """Final pre-submission validation on a concrete order."""
        ...

    def check_sized_intent(
        self,
        intent: SizedPositionIntent,
        positions: PositionStore,
    ) -> tuple[OrderRequest, ...]:
        """Translate a Phase-4 ``SizedPositionIntent`` to per-leg orders.

        Each non-zero ``TargetPosition`` delta vs the current position
        is converted into one :class:`OrderRequest`.  Symbol iteration
        order is **lexicographically sorted** so the emitted tuple is
        bit-identical across replays (Inv-5).

        Per-leg veto semantics (Inv-11): when the per-symbol order
        cannot be admitted (post-fill quantity over the cap, exposure
        breach, etc.) the offending leg is **dropped silently** from
        the returned tuple — the rest of the intent proceeds.  The
        intent is never rejected wholesale.

        Implementations MUST NOT raise.  An empty tuple ``()`` means
        the intent reduces to "hold all current positions" (Inv-11
        fail-safe).

        The legacy :meth:`check_signal` and :meth:`check_order` paths
        are unchanged; this method is purely additive.
        """
        ...
