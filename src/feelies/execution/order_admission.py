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

from dataclasses import dataclass

from feelies.core.events import Side
from feelies.core.gate_registry import record_verdict
from feelies.execution.intent import OrderIntent, TradingIntent

# ── Stable suppression tokens ────────────────────────────────────────────
# These strings reach the signal-order trace and the no-order reason path, so
# they are part of the operator-visible contract; do not reword casually.
BLOCK_HALT_BLACKOUT: str = "halt_resolution_blackout"
BLOCK_SESSION_FLATTEN_WINDOW: str = "session_flatten_window"
BLOCK_SSR: str = "ssr_suppressed"
BLOCK_LOCATE_UNAVAILABLE: str = "locate_unavailable"
BLOCK_BELOW_MIN_ORDER_SHARES: str = "quantity_below_platform_min_order_shares"
# Inv-12 B4 on a PORTFOLIO leg. Applied by the kernel rather than
# admission_block_reason: pricing round-trip cost needs the live quote and the
# cost model, neither of which belongs in this pure module.
BLOCK_EDGE_BELOW_COST: str = "portfolio_leg_edge_below_min_edge_cost_ratio"
BLOCK_EDGE_UNPRICEABLE: str = "portfolio_leg_edge_unpriceable_no_quote"


@dataclass(frozen=True, kw_only=True)
class ExposureDelta:
    """Signed book position before an order, and what the order would add.

    ``current_quantity`` is the symbol-net position (``+`` long, ``-`` short).
    ``signed_quantity`` is the order's own signed size (``+`` buy, ``-`` sell).
    """

    current_quantity: int
    signed_quantity: int

    @property
    def post_quantity(self) -> int:
        """Position the order would leave behind."""
        return self.current_quantity + self.signed_quantity

    @property
    def opens_or_increases_exposure(self) -> bool:
        """True when the order adds risk rather than only shedding it.

        Two ways to add exposure: grow the magnitude on the side already held,
        or cross through zero onto the other side.  Crossing is strict
        (``current * post < 0``) so a clean flatten to zero is never an opening
        — that distinction is the same one Inv-11's forced-exit clamp turns on.
        """
        current = self.current_quantity
        post = self.post_quantity
        if current * post < 0:
            return True
        return abs(post) > abs(current)

    @property
    def opens_or_increases_short(self) -> bool:
        """True when the order opens or deepens SHORT exposure (Reg-SHO).

        ``post < min(current, 0)`` — the order must end the book short *and*
        shorter than it started.  Buys, covers, partial covers and long-side
        exits are never short sales, whatever their side.
        """
        return self.post_quantity < min(self.current_quantity, 0)


def side_for_intent(intent: OrderIntent) -> Side:
    """Order side for a :class:`OrderIntent`.

    Pure function of the intent, so both the exposure basis and the kernel's
    order construction resolve a side the same way.
    """
    kind = intent.intent
    if kind in (TradingIntent.ENTRY_LONG, TradingIntent.REVERSE_SHORT_TO_LONG):
        return Side.BUY
    if kind in (TradingIntent.ENTRY_SHORT, TradingIntent.REVERSE_LONG_TO_SHORT):
        return Side.SELL
    if kind is TradingIntent.EXIT:
        return Side.SELL if intent.current_quantity > 0 else Side.BUY
    if kind is TradingIntent.SCALE_UP:
        return Side.BUY if intent.current_quantity >= 0 else Side.SELL
    raise ValueError(
        f"Cannot determine Side for intent {kind!r}. Fail-safe: aborting order construction."
    )


def exposure_delta_from_intent(intent: OrderIntent) -> ExposureDelta:
    """Derive the exposure delta an :class:`OrderIntent` would produce.

    ``OrderIntent.target_quantity`` is the *unsigned trade size* (see the matrix
    on :class:`~feelies.execution.intent.SignalPositionTranslator`), so the
    signed delta is that size carrying the resolved side.

    This is the single admission basis: what the order does to the book, not
    which enum arm produced it.  The enum classification disagrees on one case
    (a ``REVERSE_*`` with ``target_quantity == 0``, which trades ``|qty|``
    shares and lands flat); the book is the authority there.
    """
    side = side_for_intent(intent)
    signed = intent.target_quantity if side is Side.BUY else -intent.target_quantity
    return ExposureDelta(
        current_quantity=intent.current_quantity,
        signed_quantity=signed,
    )


def blocks_for_min_size(
    quantity: int,
    min_order_shares: int,
    *,
    exempt: bool,
) -> bool:
    """True when *quantity* is below the platform floor and not exempt.

    Exits and stop-exits are exempt: a position must always be closable, and a
    residual smaller than the floor would otherwise be untradeable forever.
    """
    if exempt:
        return False
    return quantity < min_order_shares


def admission_block_reason(
    *,
    opens_exposure: bool,
    opens_short: bool,
    in_halt_blackout: bool,
    in_session_flatten_window: bool,
    ssr_active: bool,
    locate_unavailable: bool,
    quantity: int | None = None,
    min_order_shares: int = 1,
    exempt_from_min_size: bool = False,
) -> str | None:
    """First blocking reason for this order, or ``None`` to admit.

    Check order matches the standalone SIGNAL path's historical sequence so a
    suppression token stays stable when more than one gate would fire: halt
    blackout, session-flatten window, SSR, locate, then minimum size.

    Every gate here is conditioned on the order *adding* risk, so a reduction
    admits under any environment — Inv-11's "a position must always be
    closable", stated once instead of per call site.

    ``quantity=None`` skips the size check, for callers that gate before the
    final risk-scaled quantity is known and re-check it at construction.
    """
    if opens_exposure:
        if in_halt_blackout:
            record_verdict("RT.SESSION_ADMISSION", "FAIL", BLOCK_HALT_BLACKOUT)
            return BLOCK_HALT_BLACKOUT
        if in_session_flatten_window:
            record_verdict("RT.SESSION_ADMISSION", "FAIL", BLOCK_SESSION_FLATTEN_WINDOW)
            return BLOCK_SESSION_FLATTEN_WINDOW
    if opens_short:
        if ssr_active:
            record_verdict("RT.SESSION_ADMISSION", "FAIL", BLOCK_SSR)
            return BLOCK_SSR
        if locate_unavailable:
            record_verdict("RT.SESSION_ADMISSION", "FAIL", BLOCK_LOCATE_UNAVAILABLE)
            return BLOCK_LOCATE_UNAVAILABLE
    if quantity is not None and blocks_for_min_size(
        quantity, min_order_shares, exempt=exempt_from_min_size
    ):
        record_verdict("RT.MIN_SIZE", "FAIL", BLOCK_BELOW_MIN_ORDER_SHARES)
        return BLOCK_BELOW_MIN_ORDER_SHARES
    record_verdict("RT.SESSION_ADMISSION", "PASS")
    if quantity is not None:
        record_verdict("RT.MIN_SIZE", "PASS")
    return None


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
