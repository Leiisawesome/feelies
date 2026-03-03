"""Risk engine protocol — the sole gatekeeper between signal and execution.

The risk engine is independent and dominant.  It can veto any order
and trigger risk lockdown.  No strategy layer can bypass it (invariant 11).

Every order intent transits the risk engine; no direct
signal-to-execution path exists.
"""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import OrderRequest, RiskVerdict, Signal
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
