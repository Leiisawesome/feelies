"""Structured result for PORTFOLIO :meth:`~feelies.risk.engine.RiskEngine.check_sized_intent`.

Layer-3 path uses per-leg veto for ordinary rejections, but a drawdown-driven
``RiskAction.FORCE_FLATTEN`` on any leg requires **global** orchestrator
escalation (emergency flatten + risk LOCKED), not silent leg dropping.
"""

from __future__ import annotations

from dataclasses import dataclass

from feelies.core.events import OrderRequest


@dataclass(frozen=True, kw_only=True)
class SizedIntentRiskResult:
    """Orders admitted after per-leg checks plus global breach signalling."""

    orders: tuple[OrderRequest, ...]
    requires_global_risk_escalation: bool = False
