"""Risk engine protocol — the sole gatekeeper between signal and execution.

The risk engine is independent and dominant.  It can veto any order
and trigger risk lockdown.  No strategy layer can bypass it (invariant 11).

Every order intent transits the risk engine; no direct
signal-to-execution path exists.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from feelies.core.events import (
    OrderRequest,
    RiskVerdict,
    Signal,
    SizedPositionIntent,
)
from feelies.portfolio.position_store import PositionStore
from feelies.risk.sized_intent_result import SizedIntentRiskResult


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
        *,
        additional_exposure: Decimal = Decimal("0"),
    ) -> RiskVerdict:
        """Final pre-submission validation on a concrete order.

        ``additional_exposure`` (default ``0``) is the signed gross-notional
        already committed by *earlier* legs of the same in-flight
        ``SizedPositionIntent`` that are not yet reflected in ``positions``
        (fills happen after the whole intent is vetted).  The per-leg
        decomposition in :func:`feelies.risk.sized_intent_orders.build_sized_intent_orders`
        passes the running total so the gross-exposure and buying-power caps
        are enforced *cumulatively* across legs rather than each leg seeing
        only the pre-intent snapshot. The standalone SIGNAL path
        leaves it at the default and is unchanged.
        """
        ...

    def check_sized_intent(
        self,
        intent: SizedPositionIntent,
        positions: PositionStore,
    ) -> SizedIntentRiskResult:
        """Translate a ``SizedPositionIntent`` to per-leg orders.

        Each non-zero ``TargetPosition`` delta vs the current position
        is converted into one :class:`OrderRequest`.  Symbol iteration
        order is **lexicographically sorted** so the emitted tuple is
        bit-identical across replays (Inv-5).

        Per-leg veto semantics (Inv-11): when the per-symbol order
        cannot be admitted (post-fill quantity over the cap, gross
        exposure breach, etc.) the offending leg is **dropped silently**
        from ``orders`` — the rest of the intent proceeds.

        Drawdown breach is different: any leg whose :meth:`check_order`
        returns ``RiskAction.FORCE_FLATTEN`` sets
        ``requires_global_risk_escalation=True`` and yields **empty**
        ``orders`` so the orchestrator runs emergency flatten +
        risk LOCKED (same global halt as the standalone SIGNAL path).

        Implementations MUST NOT raise.  Empty ``orders`` with the flag
        false means the intent reduced to no trades after vetoes.

        :meth:`check_signal` and :meth:`check_order` remain separate paths.
        """
        ...
