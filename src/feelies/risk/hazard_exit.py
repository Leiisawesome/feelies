"""``HazardExitController`` — Phase-4.1 hazard-rate-driven exit emitter.

Subscribes to two events on the bus:

* :class:`RegimeHazardSpike` (Phase 3.1) — publishes a per-symbol
  hazard score when the dominant regime is about to flip.  When the
  score exceeds an alpha-declared ``hazard_score_threshold`` and the
  position has been open at least ``min_age_seconds``, an
  :class:`OrderRequest` with ``reason='HAZARD_SPIKE'`` is emitted to
  exit the position.
* :class:`Trade` (M9 reconciliation) — used as the deterministic
  clock for the optional ``hard_exit_age_seconds`` guard: if any
  position has been open longer than the configured cap at the time
  of any trade print on its symbol, an exit order is emitted with
  ``reason='HARD_EXIT_AGE'``.

Determinism (Inv-5)
-------------------

Both triggers fire from event timestamps — the controller never reads
wall-clock time.  Order ID derivation is SHA-256 of
``(correlation_id, sequence, symbol, reason)`` so two replays produce
identical IDs.

Idempotency / suppression
-------------------------

Once a hazard exit has been emitted for a symbol, subsequent spikes on
the *same* ``(symbol, departing_state)`` are suppressed until the
position returns to flat (Inv-11 fail-safe — never re-enter a hazard
exit chain in a single regime departure).  Hard-age exits are
suppressed identically — at most one per symbol per open episode.

Per-alpha configuration
-----------------------

Each PORTFOLIO alpha that opts in declares::

    hazard_exit:
      enabled: true
      hazard_score_threshold: 0.85       # exit when score > threshold
      min_age_seconds: 30                # ignore until position is this old
      hard_exit_age_seconds: 1800        # forcibly exit at this age (optional)

The controller fans the configuration out per ``strategy_id`` so a
universe with mixed-policy alphas behaves correctly.
"""

from __future__ import annotations

import hashlib
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
from feelies.core.identifiers import SequenceGenerator
from feelies.portfolio.position_store import PositionStore

_logger = logging.getLogger(__name__)

# Default thresholds when an alpha opts in without specifying values.
_DEFAULT_HAZARD_SCORE_THRESHOLD: float = 0.85
_DEFAULT_MIN_AGE_SECONDS: int = 30


@dataclass(frozen=True)
class HazardPolicy:
    """Per-alpha hazard-exit configuration."""

    strategy_id: str
    hazard_score_threshold: float = _DEFAULT_HAZARD_SCORE_THRESHOLD
    min_age_seconds: int = _DEFAULT_MIN_AGE_SECONDS
    hard_exit_age_seconds: int | None = None
    universe: tuple[str, ...] = ()


class HazardExitController:
    """Bus-attached hazard-exit emitter (Phase 4.1).

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
                "HazardExitController.attach() — no policies registered; "
                "skipping bus subscription"
            )
            return
        self._bus.subscribe(
            RegimeHazardSpike, self._on_spike,  # type: ignore[arg-type]
        )
        self._bus.subscribe(Trade, self._on_trade)  # type: ignore[arg-type]
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
            self._maybe_emit_exit(
                strategy_id=sid,
                symbol=spike.symbol,
                trigger_ts_ns=spike.timestamp_ns,
                correlation_id=spike.correlation_id,
                policy=policy,
                reason="HAZARD_SPIKE",
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
                reason="HARD_EXIT_AGE",
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
        # Min-age safeguard only applies to hazard-spike triggers; the
        # hard-exit-age trigger has already reasoned about age.
        if reason == "HAZARD_SPIKE" and opened is not None:
            age_ns = trigger_ts_ns - opened
            if age_ns < int(policy.min_age_seconds) * 1_000_000_000:
                return

        side = Side.SELL if position.quantity > 0 else Side.BUY
        quantity = abs(position.quantity)

        order_id = hashlib.sha256(
            f"{correlation_id}:{trigger_ts_ns}:{symbol}:{reason}".encode()
        ).hexdigest()[:16]

        order = OrderRequest(
            timestamp_ns=trigger_ts_ns,
            correlation_id=correlation_id,
            sequence=self._seq.next(),
            source_layer="RISK",
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            strategy_id=strategy_id,
            reason=reason,
        )
        self._emitted_for_episode.add(key)
        self._bus.publish(order)
        _logger.info(
            "HazardExitController emitted %s exit for %s (strategy=%s, "
            "qty=%d, side=%s)",
            reason, symbol, strategy_id, quantity, side.name,
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


__all__ = [
    "HazardExitController",
    "HazardPolicy",
]
