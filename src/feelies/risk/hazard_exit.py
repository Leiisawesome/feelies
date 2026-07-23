"""Hazard- and age-driven exit emitter.

``RegimeHazardSpike`` triggers threshold exits; ``Trade`` timestamps drive
optional maximum-age exits. Event time and content-derived order IDs keep
replay deterministic. Each symbol emits at most one exit per open episode.

Policies are per strategy, but exits flatten the shared symbol-net position,
not a strategy slice. Universe filters keep policies off unrelated symbols.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    OrderRequest,
    OrderType,
    RegimeHazardSpike,
    Side,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator, derive_order_id
from feelies.portfolio.position_store import PositionStore

_logger = logging.getLogger(__name__)

# Default thresholds when an alpha opts in without specifying values.
_DEFAULT_HAZARD_SCORE_THRESHOLD: float = 0.85
_DEFAULT_MIN_AGE_SECONDS: int = 30

# ── Hazard-exit OrderRequest signature (single source of truth) ──────────
# Export the controller signature used by the orchestrator's hazard bridge.
HAZARD_EXIT_SOURCE_LAYER: str = "RISK"
HAZARD_EXIT_REASON_SPIKE: str = "HAZARD_SPIKE"
HAZARD_EXIT_REASON_HARD_AGE: str = "HARD_EXIT_AGE"
HAZARD_EXIT_REASONS: frozenset[str] = frozenset(
    {HAZARD_EXIT_REASON_SPIKE, HAZARD_EXIT_REASON_HARD_AGE}
)


@dataclass(frozen=True)
class HazardPolicy:
    """Per-alpha hazard-exit configuration.

    ``applies_to_regimes`` (§20.5.3 / §20.7.1) restricts which regime
    *departures* trigger a hazard exit.  Each entry is a canonical
    ``"<departing> -> <incoming>"`` transition or a bare ``"<departing>"``
    departing-state name.  Empty ⇒ fire on **all** qualifying departures
    (the default behavior).
    """

    strategy_id: str
    hazard_score_threshold: float = _DEFAULT_HAZARD_SCORE_THRESHOLD
    min_age_seconds: int = _DEFAULT_MIN_AGE_SECONDS
    hard_exit_age_seconds: int | None = None
    universe: tuple[str, ...] = ()
    applies_to_regimes: tuple[str, ...] = ()


def _spike_matches_regimes(
    departing_state: str,
    incoming_state: str | None,
    applies_to_regimes: tuple[str, ...],
) -> bool:
    """Whether a spike's departure is selected by ``applies_to_regimes``.

    Empty filter ⇒ matches everything (backward-compatible).  Otherwise the
    spike matches iff the bare departing state, or the full
    ``"<departing> -> <incoming>"`` transition, is listed.  A tied/None
    incoming only matches a bare departing-state entry.
    """
    if not applies_to_regimes:
        return True
    candidates = {departing_state}
    if incoming_state is not None:
        candidates.add(f"{departing_state} -> {incoming_state}")
    return any(entry in candidates for entry in applies_to_regimes)


class HazardExitController:
    """Bus-attached hazard-exit emitter.

    Construction is **opt-in**: bootstrap only instantiates the
    controller when at least one PORTFOLIO alpha declares
    ``hazard_exit.enabled: true``.  Default deployments stay
    bit-identical to v0.2 (Inv-A).
    """

    __slots__ = (
        "_bus",
        "_seq",
        "_position_store",
        "_policies",
        "_attached",
        "_emitted_for_episode",
        "_pending_exit_symbols",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        sequence_generator: SequenceGenerator,
        position_store: PositionStore,
        policies: Mapping[str, HazardPolicy] | None = None,
    ) -> None:
        self._bus = bus
        self._seq = sequence_generator
        self._position_store = position_store
        self._policies: dict[str, HazardPolicy] = dict(policies or {})
        self._attached = False
        # Per-symbol "already emitted" suppression — keyed by
        # ``(strategy_id, symbol, reason)``.  Cleared when the position
        # returns to flat (see ``_clear_episode_if_flat``).
        self._emitted_for_episode: set[tuple[str, str, str]] = set()
        # Suppress duplicate asynchronous closes against one stale position.
        # Episode or quantity changes release the guard for a new residual close.
        self._pending_exit_symbols: dict[str, tuple[int | None, int]] = {}

    # ── Public API ───────────────────────────────────────────────────

    @property
    def policies(self) -> Mapping[str, HazardPolicy]:
        return dict(self._policies)

    def register_policy(self, policy: HazardPolicy) -> None:
        """Add or replace a strategy's hazard-exit policy."""
        self._policies[policy.strategy_id] = policy

    def attach(self) -> None:
        if self._attached:
            return
        if not self._policies:
            _logger.debug(
                "HazardExitController.attach() — no policies registered; skipping bus subscription"
            )
            return
        self._bus.subscribe(RegimeHazardSpike, self._on_spike)
        self._bus.subscribe(Trade, self._on_trade)
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_spike(self, spike: RegimeHazardSpike) -> None:
        # Iterate policies lex-sorted on strategy_id so two replays
        # emit any concurrent exits in the same order.
        for sid in sorted(self._policies):
            policy = self._policies[sid]
            if policy.universe and spike.symbol not in policy.universe:
                continue
            if spike.hazard_score < policy.hazard_score_threshold:
                continue
            # §20.5.3 / §20.7.1: departing-state filter. Empty ⇒ all departures.
            if not _spike_matches_regimes(
                spike.departing_state, spike.incoming_state, policy.applies_to_regimes
            ):
                continue
            self._maybe_emit_exit(
                strategy_id=sid,
                symbol=spike.symbol,
                trigger_ts_ns=spike.timestamp_ns,
                correlation_id=spike.correlation_id,
                policy=policy,
                reason=HAZARD_EXIT_REASON_SPIKE,
            )

    def _on_trade(self, trade: Trade) -> None:
        # Hard-exit-age check — uses Trade arrival as a deterministic
        # clock proxy.  We only consider trades on symbols where some
        # policy actually cares about hard-age (cheap pre-filter).
        for sid in sorted(self._policies):
            policy = self._policies[sid]
            if policy.hard_exit_age_seconds is None:
                continue
            if policy.universe and trade.symbol not in policy.universe:
                continue
            opened = self._position_store.opened_at_ns(trade.symbol)
            if opened is None:
                continue
            age_ns = trade.timestamp_ns - opened
            if age_ns < int(policy.hard_exit_age_seconds) * 1_000_000_000:
                continue
            self._maybe_emit_exit(
                strategy_id=sid,
                symbol=trade.symbol,
                trigger_ts_ns=trade.timestamp_ns,
                correlation_id=trade.correlation_id,
                policy=policy,
                reason=HAZARD_EXIT_REASON_HARD_AGE,
            )

    # ── Internals ────────────────────────────────────────────────────

    def _maybe_emit_exit(
        self,
        *,
        strategy_id: str,
        symbol: str,
        trigger_ts_ns: int,
        correlation_id: str,
        policy: HazardPolicy,
        reason: str,
    ) -> None:
        # Episode-suppression first — keeps two consecutive spikes from
        # double-firing the same exit (Inv-11 fail-safe).
        key = (strategy_id, symbol, reason)
        self._clear_episode_if_flat(strategy_id, symbol, reason)
        if key in self._emitted_for_episode:
            return

        position = self._position_store.get(symbol)
        if position.quantity == 0:
            return

        opened = self._position_store.opened_at_ns(symbol)

        # Release the duplicate-close guard when the episode or quantity changes.
        if symbol in self._pending_exit_symbols:
            if self._pending_exit_symbols[symbol] == (opened, position.quantity):
                return
            del self._pending_exit_symbols[symbol]

        # Min-age safeguard only applies to hazard-spike triggers; the
        # hard-exit-age trigger has already reasoned about age.
        if reason == HAZARD_EXIT_REASON_SPIKE and opened is not None:
            age_ns = trigger_ts_ns - opened
            if age_ns < int(policy.min_age_seconds) * 1_000_000_000:
                return

        side = Side.SELL if position.quantity > 0 else Side.BUY
        quantity = abs(position.quantity)

        order_id = derive_order_id(f"{correlation_id}:{trigger_ts_ns}:{symbol}:{reason}")

        order = OrderRequest(
            timestamp_ns=trigger_ts_ns,
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            source_layer=HAZARD_EXIT_SOURCE_LAYER,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_id=strategy_id,
            reason=reason,
        )
        self._emitted_for_episode.add(key)
        self._pending_exit_symbols[symbol] = (opened, position.quantity)
        self._bus.publish(order)
        _logger.info(
            "HazardExitController emitted %s exit for %s (strategy=%s, qty=%d, side=%s)",
            reason,
            symbol,
            strategy_id,
            quantity,
            side.name,
        )

    def _clear_episode_if_flat(
        self,
        strategy_id: str,
        symbol: str,
        reason: str,
    ) -> None:
        """Reset the episode-suppression flag when the position is flat.

        This allows the *next* open to be eligible for a new hazard
        exit without requiring the controller to listen for fills.
        """
        position = self._position_store.get(symbol)
        if position.quantity == 0:
            self._emitted_for_episode.discard((strategy_id, symbol, reason))
            self._pending_exit_symbols.pop(symbol, None)


__all__ = [
    "HazardExitController",
    "HazardPolicy",
]
