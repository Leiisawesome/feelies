"""Risk-layer exit composer — actuates the §2.4 dual-permission table.

Stage-0 dual-permission decoupling (``dual_permission_actuation_design`` rev 5)
splits *"no new exposure"* (the regime gate's safety meaning) from *"flatten
this open book now"* (an actuation policy).  The regime gate publishes a typed
:class:`~feelies.core.events.SafetyStateChange` on every path that used to force
a gate-close FLAT — the clean ON→OFF transition and the three fail-closed error
paths.  This composer consumes those events and decides, per **strategy slice**,
whether an open book HOLDs (bounded deferral) or EXITs (fail-closed unwind).

It is a risk-layer author co-located with
:class:`~feelies.risk.hazard_exit.HazardExitController` (design §3.3):

- It reads **strategy-slice** position state
  (:class:`~feelies.portfolio.strategy_position_store.StrategyPositionStore`), so
  a flatten never crosses into another strategy's slice on a shared symbol — a
  symbol-net unwind under a multi-strategy book is a defect (§3.3).
- Its ``EXIT`` emits a **raw** flatten :class:`~feelies.core.events.OrderRequest`
  that the kernel routes through the same non-vetoable bridge the hazard
  controller uses (``check_order``, not ``check_sized_intent``): a cost/edge gate
  may suppress an *entry*, never a mandated safety exit (§3.3, Inv-11).
- ``Signal`` stays stateless; book-indexed HOLD/EXIT lives here, not in
  :class:`~feelies.signals.horizon_engine.HorizonSignalEngine` (Inv-8).

The composer runs **synchronously** on the same bus dispatch as the triggering
``SafetyStateChange`` (the bus is synchronous — see
:class:`~feelies.bus.event_bus.EventBus`), so a fail-closed error-path unwind has
exactly the liveness the old inline gate-close FLAT had: no async/batched
consumer, no window in which an errored gate leaves an open book with no exit
author (§3.6 "never silent — routing changes, fail-closed behavior does not").

Stage-0 scope
-------------
Only Stage 0 is built here.  ``P_story`` is always ``UNKNOWN`` (no story map is
configured), so the composer never emits the Stage-1 rows (mercy, net-new
safe-ON/story-OFF, cold-map fail-closed).  Concretely, for a decoupled alpha:

* clean ON→OFF transition ⇒ **HOLD** — the bounded deferral; the
  :class:`~feelies.risk.deferral_cap.DeferralCapController` owns the timed EXIT
  at the §2.3 ``min()`` deadline.
* missing-binding / gate-error / arithmetic-error ⇒ **EXIT** — fail-closed; the
  Phase-1 temporary SIGNAL-layer error FLAT is removed and this composer author
  the unwind instead.
* any hard cap already hit ⇒ **EXIT** (caps dominate the table).

Determinism (Inv-5): integer nanosecond timestamps carried through from the
event, content-derived order IDs, a dedicated sequence generator, and
lex-sorted policy iteration.  The full §2.4 table is realized by the pure
:func:`compose_exit` for testability and Stage-1 readiness even though the
Stage-0 wiring only ever drives it with ``P_story = UNKNOWN``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    OrderRequest,
    OrderType,
    SafetyReason,
    SafetyStateChange,
    Side,
)
from feelies.core.identifiers import SequenceGenerator, derive_order_id
from feelies.portfolio.strategy_position_store import StrategyPositionStore

_logger = logging.getLogger(__name__)

# ── Exit-composer OrderRequest signature (single source of truth) ────────
# The kernel's forced-exit bridge (``Orchestrator._on_bus_hazard_order``) routes
# any ``OrderRequest`` carrying this source layer and one of these reasons
# through the non-vetoable submission path — mirroring the hazard controller's
# signature so the two authors share one routing contract (Inv-11).
EXIT_COMPOSER_SOURCE_LAYER: str = "RISK"
# Fail-closed unwind driven by a gate error path (missing binding / gate error /
# arithmetic error).  The specific ``SafetyReason`` and full gate provenance ride
# the correlated ``SafetyStateChange`` (same ``correlation_id``), so forensics
# keyed on the old gate-close FLAT reconstruct attribution from this reason code
# plus that event (design §3.1.6, Inv-13).
EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED: str = "SAFETY_FAIL_CLOSED"
# Revocation-symmetry unwind (design rev 5 §2.5 / §3.6): removing a decoupled
# alpha's Stage-0 authorization — quarantine, de-promotion, or a config revert to
# ``gate_close_flat`` — immediately flattens any open deferred book.  The deferral
# never outlives its authorization, so the position flattens on the revocation
# transition, not at the old ``max_hold_after_safe_off`` / age ceiling.
EXIT_COMPOSER_REASON_DECOUPLING_REVOKED: str = "DECOUPLING_REVOKED"
EXIT_COMPOSER_EXIT_REASONS: frozenset[str] = frozenset(
    {
        EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED,
        EXIT_COMPOSER_REASON_DECOUPLING_REVOKED,
    }
)

# The three fail-closed gate-error reasons.  ``clean_transition`` is the only
# ``SafetyReason`` that is *not* fail-closed: under Stage-0 decoupling it becomes
# a bounded HOLD, while every error reason forces an immediate EXIT (§3.1, §3.6).
_FAIL_CLOSED_SAFETY_REASONS: frozenset[SafetyReason] = frozenset(
    {"missing_binding", "gate_error", "arithmetic_error"}
)


class BookState(Enum):
    """Per-strategy-slice book state consumed by :func:`compose_exit`."""

    FLAT = auto()
    LONG = auto()
    SHORT = auto()


class SafetyPermission(Enum):
    """Hysteretic environment permission ``P_safe`` (regime gate)."""

    ON = auto()
    OFF = auto()


class StoryPermission(Enum):
    """Hold-desire map ``P_story`` for an open book.

    Always ``UNKNOWN`` under Stage 0 (no story map configured, or a cold/errored
    map).  Stage 1 adds the ``ON`` (mercy) / ``OFF`` (early story-death) values.
    """

    ON = auto()
    OFF = auto()
    UNKNOWN = auto()


class ExitDecision(Enum):
    """Result of :func:`compose_exit` — HOLD (no flatten) or EXIT (flatten)."""

    HOLD = auto()
    EXIT = auto()


def compose_exit(
    *,
    book: BookState,
    p_safe: SafetyPermission,
    p_story: StoryPermission,
    caps_hit: bool,
    story_configured: bool,
    safe_off_fail_closed: bool,
) -> ExitDecision:
    """Pure realization of the §2.4 dual-permission actuation table.

    Returns ``EXIT`` when the open book must flatten and ``HOLD`` otherwise.  A
    ``FLAT`` book is never actuated by the composer — ``NO_ENTRY`` /
    ``ENTER_ELIGIBLE`` are the signal path's concern — so it always returns
    ``HOLD`` (no flatten order).

    Precedence (§2.6):

    1. Hard caps dominate: ``caps_hit`` ⇒ ``EXIT`` regardless of permissions.
    2. A fail-closed safety-OFF (``p_safe == OFF and safe_off_fail_closed``) ⇒
       ``EXIT``.  This is the gate-error unwind that must survive even the
       Stage-0 ``OFF ∧ Unknown`` HOLD reading (§3.1, §3.6): an *errored* gate is
       not the *intentional* absence of a story map.
    3. Otherwise the open-book rows of §2.4:

       ===========  ============  ==========================================
       ``p_safe``   ``p_story``   actuation
       ===========  ============  ==========================================
       ON           ON            HOLD
       ON           OFF           EXIT   (Stage-1 net-new early exit)
       ON           UNKNOWN       HOLD   (today's behavior; weather fine)
       OFF          ON            HOLD   (Stage-1 mercy cell)
       OFF          OFF           EXIT
       OFF          UNKNOWN       HOLD if not ``story_configured`` (Stage 0);
                                  EXIT otherwise (Stage-1 fail-closed)
       ===========  ============  ==========================================

    ``story_configured`` disambiguates the ``OFF ∧ Unknown`` row: Stage 0 (no
    story map) reads ``Unknown`` as the *intentional* absence of a map and HOLDs
    until a cap fires; Stage 1 (map configured) reads it as a cold/errored map
    and EXITs — no mercy under uncertainty (§2.4).

    The function is deliberately total over every ``(book, p_safe, p_story)``
    combination so it is exhaustively truth-table testable and Stage-1 ready,
    even though the Stage-0 wiring only ever calls it with
    ``p_story = UNKNOWN`` and ``story_configured = False``.
    """
    if book is BookState.FLAT:
        return ExitDecision.HOLD

    if caps_hit:
        return ExitDecision.EXIT

    if p_safe is SafetyPermission.OFF and safe_off_fail_closed:
        return ExitDecision.EXIT

    if p_safe is SafetyPermission.ON:
        # Weather fine: only a live story-OFF (Stage-1) forces an early exit.
        return ExitDecision.EXIT if p_story is StoryPermission.OFF else ExitDecision.HOLD

    # p_safe is OFF (clean): entries are already blocked; decide the open book.
    if p_story is StoryPermission.ON:
        return ExitDecision.HOLD  # Stage-1 mercy cell.
    if p_story is StoryPermission.OFF:
        return ExitDecision.EXIT
    # p_story is UNKNOWN: Stage 0 holds (bounded by a cap); Stage 1 fails closed.
    return ExitDecision.EXIT if story_configured else ExitDecision.HOLD


@dataclass(frozen=True)
class ExitComposerPolicy:
    """Per-alpha exit-composer configuration.

    A policy is registered only for a **decoupled** alpha
    (``RegisteredSignal.decouple_gate_close``); non-decoupled alphas keep their
    SIGNAL-layer gate-close FLAT and must have no composer policy, or the
    composer would double-flatten alongside that FLAT.

    ``story_configured`` is ``False`` under Stage 0 (no story map).  It exists so
    the Stage-1 wiring can flip the ``OFF ∧ Unknown`` reading to fail-closed
    without changing this controller's shape.  ``universe`` optionally restricts
    the policy to a symbol set (empty ⇒ all symbols the alpha may trade).
    """

    strategy_id: str
    universe: tuple[str, ...] = ()
    story_configured: bool = False


class ExitComposer:
    """Bus-attached exit-composer author for decoupled SIGNAL alphas.

    Construction is **opt-in**: bootstrap instantiates it only when at least one
    alpha is decoupled.  With no policies :meth:`attach` is a no-op, so default
    deployments never subscribe and stay bit-identical (Inv-5).

    The composer subscribes to :class:`~feelies.core.events.SafetyStateChange`
    and, on a ``safe=False`` event for an *open* slice it owns, emits a raw
    strategy-slice flatten :class:`~feelies.core.events.OrderRequest` when
    :func:`compose_exit` returns ``EXIT``.  Per-episode dedup keeps two safety
    events (e.g. an error path arriving while a prior exit is still in flight
    under async fills) from double-flattening one slice.
    """

    __slots__ = (
        "_bus",
        "_seq",
        "_position_store",
        "_policies",
        "_attached",
        # Duplicate-close guard: (strategy_id, symbol) -> (opened_at_ns, quantity).
        # Suppresses a re-fire against a slice already flattened this episode; a
        # quantity change (partial fill) or a new episode releases it.
        "_pending_exit",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        position_store: StrategyPositionStore,
        policies: Mapping[str, ExitComposerPolicy] | None = None,
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self._position_store = position_store
        self._policies: dict[str, ExitComposerPolicy] = dict(policies or {})
        self._attached = False
        self._pending_exit: dict[tuple[str, str], tuple[int | None, int]] = {}

    # ── Public API ───────────────────────────────────────────────────

    @property
    def policies(self) -> Mapping[str, ExitComposerPolicy]:
        return dict(self._policies)

    def register_policy(self, policy: ExitComposerPolicy) -> None:
        """Add or replace a strategy's exit-composer policy."""
        self._policies[policy.strategy_id] = policy

    def attach(self) -> None:
        if self._attached:
            return
        if not self._policies:
            _logger.debug(
                "ExitComposer.attach() — no policies registered; skipping bus subscription"
            )
            return
        self._bus.subscribe(SafetyStateChange, self._on_safety_state_change)
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_safety_state_change(self, event: SafetyStateChange) -> None:
        """Actuate the §2.4 table for one decoupled slice, synchronously.

        Runs inline on the publishing dispatch (the bus is synchronous), so a
        fail-closed error-path EXIT is emitted before the gate's dispatch
        returns — matching the old inline gate-close FLAT's liveness (§3.6).
        """
        policy = self._policies.get(event.strategy_id)
        if policy is None:
            return
        if policy.universe and event.symbol not in policy.universe:
            return
        # Only a safe->OFF transition actuates; a safe->ON re-arm never flattens
        # (loosening requires human re-authorization, Inv-11 / §2.5).
        if event.safe:
            return

        self._clear_episode_if_flat(event.strategy_id, event.symbol)

        position = self._position_store.get(event.strategy_id, event.symbol)
        if position.quantity == 0:
            # Flat slice: entries are already blocked while safe is OFF, and
            # there is nothing to flatten.  NO_ENTRY is the signal path's job.
            return

        opened = self._position_store.opened_at_ns(event.strategy_id, event.symbol)
        book = BookState.LONG if position.quantity > 0 else BookState.SHORT
        decision = compose_exit(
            book=book,
            p_safe=SafetyPermission.OFF,
            p_story=StoryPermission.UNKNOWN,
            # Independent hard-cap authors (deferral, hazard) own the timed exit;
            # at the safety-event instant the composer defers to them and only
            # acts on the fail-closed error paths.
            caps_hit=False,
            story_configured=policy.story_configured,
            safe_off_fail_closed=event.reason in _FAIL_CLOSED_SAFETY_REASONS,
        )
        if decision is ExitDecision.HOLD:
            # Clean ON→OFF under Stage-0 decoupling: bounded HOLD.  The deferral
            # cap forces the timed EXIT at the §2.3 deadline; nothing to emit.
            return

        self._emit_flatten(event, position.quantity, opened)

    # ── Public API: revocation symmetry ──────────────────────────────

    def revoke_and_flatten(
        self,
        strategy_id: str,
        *,
        now_ns: int,
        correlation_id: str,
    ) -> list[OrderRequest]:
        """Immediately flatten a decoupled strategy's open deferred book (§2.5).

        The revocation-symmetry hook for Inv-11: when a decoupled alpha's Stage-0
        authorization is removed — a lifecycle demotion (quarantine /
        decommission), a de-promotion, or an operator config revert to
        ``gate_close_flat`` — the deferral no longer holds, so every open slice
        the composer governs flattens **now**, not at the old
        ``max_hold_after_safe_off`` / age ceiling (design §3.6: "the position
        flattens on the transition, not at the old ceiling").

        The flatten is unconditional (it does not consult :func:`compose_exit`;
        revocation is a mandated EXIT, not a permission decision) and
        **strategy-slice scoped** — only the revoked strategy's slices are
        touched, never another strategy's book on a shared symbol.  Each emitted
        order carries :data:`EXIT_COMPOSER_REASON_DECOUPLING_REVOKED`, so the
        kernel routes it through the same non-vetoable forced-exit bridge as the
        fail-closed unwind (a cost/edge gate can never suppress it, Inv-11).

        No-ops (returns ``[]``) when ``strategy_id`` has no composer policy — a
        non-decoupled alpha keeps its SIGNAL-layer ``gate_close_flat``, so its
        book is not the composer's to flatten.  Returns the emitted orders (also
        published to the bus) for caller assertions / forensics.
        """
        policy = self._policies.get(strategy_id)
        if policy is None:
            return []
        emitted: list[OrderRequest] = []
        open_slices = self._position_store.open_positions(strategy_id)
        # Lex-sorted so the emitted order IDs / sequence are replayable (Inv-5).
        for symbol in sorted(open_slices):
            if policy.universe and symbol not in policy.universe:
                continue
            quantity = open_slices[symbol].quantity
            opened = self._position_store.opened_at_ns(strategy_id, symbol)
            order = self._emit_flatten_order(
                strategy_id=strategy_id,
                symbol=symbol,
                quantity=quantity,
                opened=opened,
                timestamp_ns=now_ns,
                correlation_id=correlation_id,
                reason=EXIT_COMPOSER_REASON_DECOUPLING_REVOKED,
                id_seed=f"{correlation_id}:{now_ns}:{symbol}:{strategy_id}:"
                f"{EXIT_COMPOSER_REASON_DECOUPLING_REVOKED}",
            )
            if order is not None:
                emitted.append(order)
        if emitted:
            _logger.info(
                "ExitComposer revoked decoupling for strategy=%s: flattened %d "
                "open slice(s) immediately (%s)",
                strategy_id,
                len(emitted),
                EXIT_COMPOSER_REASON_DECOUPLING_REVOKED,
            )
        return emitted

    # ── Internals ────────────────────────────────────────────────────

    def _emit_flatten(
        self,
        event: SafetyStateChange,
        quantity: int,
        opened: int | None,
    ) -> None:
        reason = EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED
        # Strategy slice + the specific SafetyReason in the seed so two strategies
        # (or two error causes) flattening the same symbol on one event derive
        # distinct, replayable order IDs (Inv-5).
        self._emit_flatten_order(
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            quantity=quantity,
            opened=opened,
            timestamp_ns=event.timestamp_ns,
            correlation_id=event.correlation_id,
            reason=reason,
            id_seed=f"{event.correlation_id}:{event.timestamp_ns}:{event.symbol}:"
            f"{event.strategy_id}:{reason}:{event.reason}",
        )

    def _emit_flatten_order(
        self,
        *,
        strategy_id: str,
        symbol: str,
        quantity: int,
        opened: int | None,
        timestamp_ns: int,
        correlation_id: str,
        reason: str,
        id_seed: str,
    ) -> OrderRequest | None:
        """Emit one strategy-slice flatten ``OrderRequest``, dedup-guarded.

        Shared by the safety-event fail-closed path (:meth:`_emit_flatten`) and
        the revocation path (:meth:`revoke_and_flatten`).  Returns the published
        order, or ``None`` when the per-episode duplicate-close guard suppresses
        a re-fire against a slice already flattened this episode.
        """
        key = (strategy_id, symbol)

        # Duplicate-close guard: stay silent against a slice already flattened
        # this episode until the position changes (fill) or the episode resets.
        pending = self._pending_exit.get(key)
        if pending is not None:
            if pending == (opened, quantity):
                return None
            del self._pending_exit[key]

        side = Side.SELL if quantity > 0 else Side.BUY
        exit_quantity = abs(quantity)
        order_id = derive_order_id(id_seed)

        order = OrderRequest(
            timestamp_ns=timestamp_ns,
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            source_layer=EXIT_COMPOSER_SOURCE_LAYER,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=exit_quantity,
            strategy_id=strategy_id,
            reason=reason,
        )
        self._pending_exit[key] = (opened, quantity)
        self._bus.publish(order)
        _logger.info(
            "ExitComposer emitted %s EXIT for %s (strategy=%s, qty=%d, side=%s)",
            reason,
            symbol,
            strategy_id,
            exit_quantity,
            side.name,
        )
        return order

    def _clear_episode_if_flat(self, strategy_id: str, symbol: str) -> None:
        """Release the duplicate-close guard once the slice returns to flat."""
        if self._position_store.get(strategy_id, symbol).quantity == 0:
            self._pending_exit.pop((strategy_id, symbol), None)


__all__ = [
    "BookState",
    "SafetyPermission",
    "StoryPermission",
    "ExitDecision",
    "compose_exit",
    "ExitComposerPolicy",
    "ExitComposer",
    "EXIT_COMPOSER_SOURCE_LAYER",
    "EXIT_COMPOSER_REASON_SAFETY_FAIL_CLOSED",
    "EXIT_COMPOSER_REASON_DECOUPLING_REVOKED",
    "EXIT_COMPOSER_EXIT_REASONS",
]
