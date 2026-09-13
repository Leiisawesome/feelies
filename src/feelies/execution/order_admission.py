"""Session, regulatory, and minimum-size admission gates — one definition each.

These five gates decide whether a concrete order may be *submitted at all*.
They were previously expressed only over :class:`~feelies.execution.intent.OrderIntent`
and applied only on the standalone SIGNAL path; the PORTFOLIO composition path
reached ``order_router.submit`` without passing any of them.  That asymmetry ran
the wrong way under Inv-11: the path the configs described as production-bound
was the *less* gated of the two.

The *policy* lives in :func:`admission_block_reason` and is stated over two
booleans — does this order open/increase exposure, and does it open/increase
short exposure — so both paths run the same decision in the same order.

Both paths answer those questions from one basis: :class:`ExposureDelta`, the
signed position before the order plus the order's signed size.  Composition
carries it on every :class:`~feelies.execution.sized_intent_legs.PlannedLeg`;
standalone derives it via :func:`exposure_delta_from_intent`.

An earlier revision let standalone answer from ``TradingIntent`` membership
instead.  That disagreed with the book on one reachable case: a ``REVERSE_*``
whose ``target_quantity`` is ``0`` (the sizer returned zero against an open
position) trades ``|qty|`` shares and lands *flat*.  The enum classified it as
an opening, so a halt blackout, the session-flatten window, SSR or a missing
locate could refuse a pure flatten — a safety control trapping an open
position, which is the failure Inv-11 exists to prevent.  The book is the
authority; ``test_zero_target_reversal_is_a_flatten_not_an_opening`` pins it.

Scope (deliberate).  This module owns the **Inv-11 admission** gates: they can
only ever suppress an order, never enlarge or reroute one.  Everything here is
pure — no clock, no bus, no position store, no cost model.  The caller evaluates
the environment (is the symbol in a halt blackout? is SSR active?) and passes
booleans, which keeps the policy testable without a kernel.

The Inv-12 B4 edge/cost gate is **not** here, because pricing a round trip needs
the live quote and the cost model.  It is applied by the kernel to both paths
from one implementation (``Orchestrator._edge_clears_round_trip_cost``); the two
suppression tokens it can raise on a PORTFOLIO leg are defined above so the
operator-visible vocabulary stays in one file.

That gate reaches composition legs only because
:class:`~feelies.core.events.TargetPosition` now carries
``expected_edge_bps``.  It has to: ``CrossSectionalRanker`` folds each signal's
``edge_estimate_bps`` into a raw score and ``_standardize`` z-scores that into a
*relative rank*, so a final weight of +1.2 is a cross-sectional ordering, not an
expected return.  The edge is therefore captured while the units are still bps
(``_aligned_mean_edge``) and propagated.  Deliberately **not** substituted with
the alpha's static ``cost_arithmetic.edge_estimate_bps``: one constant per alpha
against per-leg cost either always passes or always fails, which is worse than
no gate because it looks like one.

Still asymmetric: composition legs route MARKET unconditionally rather than
resolving a passive/MOC route.  ``_resolve_order_route`` is also edge-conditioned
and could now be fed, but changing a leg's ``order_type`` moves
``EXPECTED_LEVEL4_PORTFOLIO_ORDER_HASH`` and changes fill economics, so it is a
separate, argued change.  Recorded in ``configs/bt_multialpha.yaml``.
"""

from __future__ import annotations

from typing import Any

from feelies.core.events import AlertSeverity
from feelies.core.order_admission import (
    BLOCK_BELOW_MIN_ORDER_SHARES as BLOCK_BELOW_MIN_ORDER_SHARES,
)
from feelies.core.order_admission import BLOCK_HALT_BLACKOUT as BLOCK_HALT_BLACKOUT
from feelies.core.order_admission import (
    BLOCK_LOCATE_UNAVAILABLE as BLOCK_LOCATE_UNAVAILABLE,
)
from feelies.core.order_admission import (
    BLOCK_SESSION_FLATTEN_WINDOW as BLOCK_SESSION_FLATTEN_WINDOW,
)
from feelies.core.order_admission import BLOCK_SSR as BLOCK_SSR
from feelies.core.order_admission import ExposureDelta as ExposureDelta
from feelies.core.order_admission import admission_block_reason as admission_block_reason
from feelies.core.order_admission import blocks_for_min_size as blocks_for_min_size
from feelies.core.order_admission import (
    exposure_delta_from_intent as exposure_delta_from_intent,
)
from feelies.core.order_admission import side_for_intent as side_for_intent
from feelies.execution.intent import OrderIntent

# Inv-12 B4 on a PORTFOLIO leg. Applied by the kernel rather than
# admission_block_reason: pricing round-trip cost needs the live quote and the
# cost model, neither of which belongs in this pure module.
BLOCK_EDGE_BELOW_COST: str = "portfolio_leg_edge_below_min_edge_cost_ratio"
BLOCK_EDGE_UNPRICEABLE: str = "portfolio_leg_edge_unpriceable_no_quote"


def _emit_ssr_suppression_alert(
    self: Any,
    intent: OrderIntent,
    correlation_id: str,
) -> None:
    """Publish the forensic marker for a refused SSR short entry."""
    self._publish_alert(
        timestamp_ns=self._clock.now_ns(),
        correlation_id=correlation_id,
        severity=AlertSeverity.WARNING,
        alert_name="ssr_short_suppressed",
        message=f"SSR active for {intent.symbol!r}: refused short entry ({intent.intent.name}); retries next boundary (Reg-SHO 201).",
        context={"symbol": intent.symbol, "intent": intent.intent.name},
    )


__all__ = [
    "BLOCK_BELOW_MIN_ORDER_SHARES",
    "BLOCK_EDGE_BELOW_COST",
    "BLOCK_EDGE_UNPRICEABLE",
    "BLOCK_HALT_BLACKOUT",
    "BLOCK_LOCATE_UNAVAILABLE",
    "BLOCK_SESSION_FLATTEN_WINDOW",
    "BLOCK_SSR",
    "ExposureDelta",
    "admission_block_reason",
    "blocks_for_min_size",
    "exposure_delta_from_intent",
]
