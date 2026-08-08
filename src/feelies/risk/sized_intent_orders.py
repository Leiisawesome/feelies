"""Admit or veto the legs of a Layer-3 ``SizedPositionIntent``.

Both :class:`feelies.risk.basic_risk.BasicRiskEngine` and the per-alpha
:class:`feelies.alpha.risk_wrapper.AlphaBudgetRiskWrapper` decompose a portfolio
intent with identical semantics; this module holds the single canonical
implementation so the two paths cannot drift.

Risk owns *whether* each leg is admitted and what exposure an admitted leg
commits.  Constructing the leg — resolving the mark, converting USD to shares,
choosing a side, minting the order, re-rounding a scale-down — is Execution
Decision work and lives in
:mod:`feelies.execution.sized_intent_legs`.

The loop stays interleaved on purpose: a leg's admission depends on the exposure
previously admitted legs already committed (``additional_exposure``), so the caps
bind cumulatively rather than every leg seeing the same pre-intent snapshot.
Separating the responsibilities does not require separating the loop.

Determinism (Inv-5): symbols are processed in lexicographic order.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Callable

from feelies.core.events import (
    OrderRequest,
    RiskAction,
    RiskVerdict,
    SizedPositionIntent,
)
from feelies.execution.sized_intent_legs import plan_leg, rescale_leg
from feelies.portfolio.position_store import PositionStore
from feelies.risk.sized_intent_result import SizedIntentRiskResult

_logger = logging.getLogger(__name__)

# Concrete engines accept additional_exposure; simple test doubles may ignore it.
CheckOrder = Callable[..., RiskVerdict]
DroppedLegsCallback = Callable[[SizedPositionIntent, list[tuple[str, str]]], None]


def build_sized_intent_orders(
    intent: SizedPositionIntent,
    positions: PositionStore,
    *,
    check_order: CheckOrder,
    on_dropped_legs: DroppedLegsCallback | None = None,
) -> SizedIntentRiskResult:
    """Translate a sized intent into independently risk-checked orders.

    Admitted exposure accumulates across legs so the intent cannot exceed a
    cap collectively. Force-flatten aborts the intent; rejection, zero scaling,
    and raised risk checks drop only the offending leg.
    """
    if not intent.target_positions:
        return SizedIntentRiskResult(orders=())

    orders: list[OrderRequest] = []
    dropped: list[tuple[str, str]] = []
    running_extra = Decimal("0")
    for symbol in sorted(intent.target_positions):
        leg = plan_leg(intent, symbol, positions)
        if leg is None:
            continue

        try:
            verdict = check_order(leg.order, positions, additional_exposure=running_extra)
        except Exception as exc:  # noqa: BLE001 — Inv-11: never raise from the risk path
            _logger.warning(
                "build_sized_intent_orders: check_order raised for leg %s "
                "(strategy_id=%s, correlation_id=%s): %r — veto-dropping the leg",
                symbol,
                intent.strategy_id,
                intent.correlation_id,
                exc,
            )
            dropped.append((symbol, f"check_order raised: {exc!r}"))
            continue
        if verdict.action == RiskAction.FORCE_FLATTEN:
            return SizedIntentRiskResult(
                orders=(),
                requires_global_risk_escalation=True,
            )
        if verdict.action == RiskAction.REJECT:
            dropped.append((symbol, verdict.reason))
            continue
        if verdict.action == RiskAction.SCALE_DOWN:
            scaled = rescale_leg(leg, verdict.scaling_factor)
            if scaled is None:
                dropped.append((symbol, f"scaled down to zero quantity: {verdict.reason}"))
                continue
            leg = scaled

        # Include each admitted leg in later legs' exposure checks.
        post_qty = leg.current_quantity + leg.signed_quantity
        running_extra += (abs(post_qty) - abs(leg.current_quantity)) * leg.mark
        orders.append(leg.order)

    if dropped and on_dropped_legs is not None:
        on_dropped_legs(intent, dropped)

    return SizedIntentRiskResult(orders=tuple(orders))
