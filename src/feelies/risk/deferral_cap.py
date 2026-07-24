"""Bounded-deferral cap — strategy-slice forced-exit author (design §2.3).

Stage-0 dual-permission decoupling (``dual_permission_actuation_design`` rev 5)
replaces the gate-close FLAT with a *bounded* hold: once safety "weather" goes
OFF for an open book, the position may be held, but only until an enumerated
deadline.  This controller owns that deadline as a risk-layer author mirroring
:class:`~feelies.risk.hazard_exit.HazardExitController`, but scoped to the
**strategy slice** (:class:`StrategyPositionStore`) rather than symbol-net — a
symbol-net backstop under a multi-strategy book would cross-flatten another
strategy's slice, which the design rules a defect (§3.3).

The episode's forced-exit deadline is the earliest of three caps::

    deadline = min(
        opened_at      + hard_exit_age_seconds,       # position-age backstop (from open)
        first_safe_off + max_hold_after_safe_off,     # deferral ceiling (from FIRST safe->OFF)
        session_flatten,                              # wall-clock backstop of last resort
    )

The deferral clock is anchored to the **first** ``SafetyStateChange(safe=False)``
of the *open episode* and is **monotonic**: an ``OFF->ON->OFF`` gate flicker
never re-anchors it (design §2.3, §2.8) — otherwise hysteresis chatter could
hold indefinitely, which the design calls a defect.  The anchor is bound to the
episode via the slice's ``opened_at`` so a later episode never inherits a stale
anchor.

Evaluation is **event-time** on ``Trade`` arrival (Inv-7 — the platform polls
nothing), the same deterministic clock proxy the hazard controller uses for its
age cap: the cap forces ``EXIT`` on the first ``Trade`` on the symbol at/after
the deadline.  ``session_flatten`` (from :mod:`feelies.core.session_clock`) is
the wall-clock backstop of last resort: during a post-safety-OFF quote freeze
the book is held past the nominal ceiling until the next event, and exits by the
session boundary at latest.  A tighter sub-session wall-clock guarantee would
require a deterministic replayable heartbeat event, which the platform does not
yet provide (§2.8).

Determinism (Inv-5): integer nanosecond math throughout, content-derived order
IDs, a dedicated sequence generator, and lex-sorted policy iteration.  This
phase builds the cap only; wiring it beside the hazard controller and routing it
through the risk-layer exit composer land in later phases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    OrderRequest,
    OrderType,
    SafetyStateChange,
    Side,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator, derive_order_id
from feelies.core.session_clock import rth_close_ns
from feelies.portfolio.strategy_position_store import StrategyPositionStore

_logger = logging.getLogger(__name__)

_NS_PER_SECOND: int = 1_000_000_000

# ── Deferral-cap OrderRequest signature (single source of truth) ─────────
DEFERRAL_EXIT_SOURCE_LAYER: str = "RISK"
# ``HARD_EXIT_AGE`` deliberately reuses HazardExitController's reason token so
# forensics keyed on the age backstop read one lineage across both authors.
DEFERRAL_REASON_HARD_AGE: str = "HARD_EXIT_AGE"
DEFERRAL_REASON_MAX_HOLD: str = "MAX_HOLD_AFTER_SAFE_OFF"
DEFERRAL_REASON_SESSION_FLATTEN: str = "SESSION_FLATTEN"
DEFERRAL_EXIT_REASONS: frozenset[str] = frozenset(
    {
        DEFERRAL_REASON_HARD_AGE,
        DEFERRAL_REASON_MAX_HOLD,
        DEFERRAL_REASON_SESSION_FLATTEN,
    }
)

# Tie-break when two caps share a deadline ns.  The age backstop is anchored to
# the (flicker-immune) open time, so it wins ties; session flatten is the last
# resort and loses them.  Purely for deterministic reason selection (Inv-5).
_REASON_TIE_BREAK: dict[str, int] = {
    DEFERRAL_REASON_HARD_AGE: 0,
    DEFERRAL_REASON_MAX_HOLD: 1,
    DEFERRAL_REASON_SESSION_FLATTEN: 2,
}


@dataclass(frozen=True)
class DeferralPolicy:
    """Per-alpha bounded-deferral configuration (design §3.4).

    Both ceilings are **mandatory** under decoupling: ``max_hold_after_safe_off``
    is the deferral ceiling that turns "no immediate flatten" into a bounded
    delay rather than a removal, and ``hard_exit_age_seconds`` is the monotonic
    position-age backstop that holds even if the first-safe-OFF anchor is
    mis-derived (§2.3).  This ``__post_init__`` reject is the Phase-2 stub for
    the load/promotion guard; the full loader wiring lands in Phase 4 (§3.6:
    "Stage 0 without ``max_hold_after_safe_off`` or ``hard_exit_age_seconds`` →
    reject load").

    ``universe`` optionally restricts the policy to a symbol set (empty ⇒ all).
    """

    strategy_id: str
    max_hold_after_safe_off_seconds: int
    hard_exit_age_seconds: int
    universe: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_hold_after_safe_off_seconds <= 0:
            raise ValueError(
                "DeferralPolicy requires a positive max_hold_after_safe_off_seconds "
                f"under decoupling (strategy {self.strategy_id!r}); "
                f"got {self.max_hold_after_safe_off_seconds!r}"
            )
        if self.hard_exit_age_seconds <= 0:
            raise ValueError(
                "DeferralPolicy requires a positive hard_exit_age_seconds "
                f"under decoupling (strategy {self.strategy_id!r}); "
                f"got {self.hard_exit_age_seconds!r}"
            )


class DeferralCapController:
    """Bus-attached bounded-deferral exit emitter.

    Construction is **opt-in**: bootstrap only instantiates it when at least one
    decoupled alpha declares a ``safety_exit_policy``.  With no policies the
    ``attach`` is a no-op, so default deployments stay bit-identical (Inv-5).
    """

    __slots__ = (
        "_bus",
        "_seq",
        "_position_store",
        "_policies",
        "_attached",
        "_session_flatten_enabled",
        "_session_flatten_buffer_ns",
        # Episode anchor: (strategy_id, symbol) -> (opened_at_ns, first_safe_off_ns).
        # The opened_at binds the anchor to one open episode so a later episode
        # never inherits a stale (previous-episode) first-safe-OFF.
        "_first_safe_off_ns",
        # Duplicate-close guard: (strategy_id, symbol) -> (opened_at_ns, quantity).
        # Suppresses a re-fire against the same stale slice; a quantity change
        # (partial fill) or new episode releases it so a residual still closes.
        "_pending_exit",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        position_store: StrategyPositionStore,
        policies: Mapping[str, DeferralPolicy] | None = None,
        session_flatten_enabled: bool = True,
        session_flatten_seconds_before_close: int = 0,
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self._position_store = position_store
        self._policies: dict[str, DeferralPolicy] = dict(policies or {})
        self._attached = False
        self._session_flatten_enabled = session_flatten_enabled
        self._session_flatten_buffer_ns = (
            int(session_flatten_seconds_before_close) * _NS_PER_SECOND
        )
        self._first_safe_off_ns: dict[tuple[str, str], tuple[int, int]] = {}
        self._pending_exit: dict[tuple[str, str], tuple[int | None, int]] = {}

    # ── Public API ───────────────────────────────────────────────────

    @property
    def policies(self) -> Mapping[str, DeferralPolicy]:
        return dict(self._policies)

    def register_policy(self, policy: DeferralPolicy) -> None:
        """Add or replace a strategy's bounded-deferral policy."""
        self._policies[policy.strategy_id] = policy

    def attach(self) -> None:
        if self._attached:
            return
        if not self._policies:
            _logger.debug(
                "DeferralCapController.attach() — no policies registered; "
                "skipping bus subscription"
            )
            return
        self._bus.subscribe(SafetyStateChange, self._on_safety_state_change)
        self._bus.subscribe(Trade, self._on_trade)
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_safety_state_change(self, event: SafetyStateChange) -> None:
        """Anchor the deferral clock to the FIRST safe->OFF of the open episode.

        Only ``safe=False`` transitions anchor; a ``safe=True`` re-arm never
        re-anchors (monotonic).  A repeated ``safe=False`` within the same open
        episode — the second OFF of an ``OFF->ON->OFF`` flicker — is ignored, so
        chatter cannot push the deadline out (design §2.3).
        """
        if event.safe:
            return
        policy = self._policies.get(event.strategy_id)
        if policy is None:
            return
        if policy.universe and event.symbol not in policy.universe:
            return
        key = (event.strategy_id, event.symbol)
        opened = self._position_store.opened_at_ns(event.strategy_id, event.symbol)
        if opened is None:
            # Safe went OFF while the slice is flat — entries are blocked when
            # safe is OFF, so there is no open episode to defer.  Prune any stale
            # anchor and record nothing.
            self._first_safe_off_ns.pop(key, None)
            return
        existing = self._first_safe_off_ns.get(key)
        if existing is None or existing[0] != opened:
            # First safe->OFF of *this* open episode (existing anchor, if any,
            # belongs to a prior episode with a different opened_at).
            self._first_safe_off_ns[key] = (opened, event.timestamp_ns)
        # else: same episode, already anchored — monotonic; do not re-anchor.

    def _on_trade(self, trade: Trade) -> None:
        """Evaluate the ``min()`` deadline in event-time on ``Trade`` arrival.

        ``Trade`` is the deterministic clock proxy (identical to the hazard
        controller's hard-age cap): the deadline is enforced on the first trade
        on the symbol at/after it.
        """
        for sid in sorted(self._policies):
            policy = self._policies[sid]
            if policy.universe and trade.symbol not in policy.universe:
                continue
            self._maybe_emit_exit(
                strategy_id=sid,
                symbol=trade.symbol,
                now_ns=trade.timestamp_ns,
                correlation_id=trade.correlation_id,
                policy=policy,
            )

    # ── Internals ────────────────────────────────────────────────────

    def _maybe_emit_exit(
        self,
        *,
        strategy_id: str,
        symbol: str,
        now_ns: int,
        correlation_id: str,
        policy: DeferralPolicy,
    ) -> None:
        key = (strategy_id, symbol)
        self._clear_episode_if_flat(strategy_id, symbol)

        position = self._position_store.get(strategy_id, symbol)
        if position.quantity == 0:
            return

        opened = self._position_store.opened_at_ns(strategy_id, symbol)

        # Duplicate-close guard: stay silent against a slice we already flattened
        # until the position actually changes (fill) or the episode resets.
        pending = self._pending_exit.get(key)
        if pending is not None:
            if pending == (opened, position.quantity):
                return
            del self._pending_exit[key]

        resolved = self._episode_deadline(policy, key, opened, now_ns)
        if resolved is None:
            return
        deadline_ns, reason = resolved
        if now_ns < deadline_ns:
            return

        side = Side.SELL if position.quantity > 0 else Side.BUY
        quantity = abs(position.quantity)
        # Strategy slice in the seed so two strategies flattening the same symbol
        # at one trade derive distinct, replayable order IDs (Inv-5).
        order_id = derive_order_id(f"{correlation_id}:{now_ns}:{symbol}:{strategy_id}:{reason}")

        order = OrderRequest(
            timestamp_ns=now_ns,
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            source_layer=DEFERRAL_EXIT_SOURCE_LAYER,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_id=strategy_id,
            reason=reason,
        )
        self._pending_exit[key] = (opened, position.quantity)
        self._bus.publish(order)
        _logger.info(
            "DeferralCapController emitted %s exit for %s (strategy=%s, qty=%d, side=%s)",
            reason,
            symbol,
            strategy_id,
            quantity,
            side.name,
        )

    def _episode_deadline(
        self,
        policy: DeferralPolicy,
        key: tuple[str, str],
        opened: int | None,
        now_ns: int,
    ) -> tuple[int, str] | None:
        """Earliest of the enumerated caps for a *deferred* open episode.

        Returns ``None`` when the episode is not deferred (no first-safe-OFF
        anchor bound to this ``opened``) — the cap only bounds a hold once
        safety weather has gone OFF; a healthy (safe-ON) book is managed by the
        signal path and the platform session flatten, not by this author.
        """
        first_off = self._episode_first_safe_off(key, opened)
        if first_off is None:
            return None

        candidates: list[tuple[int, str]] = [
            (
                first_off + policy.max_hold_after_safe_off_seconds * _NS_PER_SECOND,
                DEFERRAL_REASON_MAX_HOLD,
            )
        ]
        if opened is not None:
            candidates.append(
                (
                    opened + policy.hard_exit_age_seconds * _NS_PER_SECOND,
                    DEFERRAL_REASON_HARD_AGE,
                )
            )
        if self._session_flatten_enabled:
            candidates.append(
                (
                    rth_close_ns(now_ns) - self._session_flatten_buffer_ns,
                    DEFERRAL_REASON_SESSION_FLATTEN,
                )
            )
        return min(candidates, key=lambda c: (c[0], _REASON_TIE_BREAK[c[1]]))

    def _episode_first_safe_off(
        self,
        key: tuple[str, str],
        opened: int | None,
    ) -> int | None:
        """First-safe-OFF ns for the *current* episode, else ``None``.

        The stored anchor is validated against ``opened`` so a stale anchor from
        a prior (now-closed) episode is never used — the clock is episode-precise
        without depending on lazy flat-clearing.
        """
        anchor = self._first_safe_off_ns.get(key)
        if anchor is None or opened is None or anchor[0] != opened:
            return None
        return anchor[1]

    def _clear_episode_if_flat(self, strategy_id: str, symbol: str) -> None:
        """Prune per-episode state when the strategy slice is flat.

        Memory hygiene only — episode correctness rests on the ``opened_at``
        validation in :meth:`_episode_first_safe_off` and the duplicate-close
        guard's content check, not on this running promptly.
        """
        if self._position_store.get(strategy_id, symbol).quantity == 0:
            key = (strategy_id, symbol)
            self._first_safe_off_ns.pop(key, None)
            self._pending_exit.pop(key, None)


__all__ = [
    "DeferralCapController",
    "DeferralPolicy",
    "DEFERRAL_EXIT_REASONS",
    "DEFERRAL_EXIT_SOURCE_LAYER",
    "DEFERRAL_REASON_HARD_AGE",
    "DEFERRAL_REASON_MAX_HOLD",
    "DEFERRAL_REASON_SESSION_FLATTEN",
]
