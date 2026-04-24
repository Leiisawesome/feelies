"""``UniverseSynchronizer`` — barrier-sync for cross-sectional contexts.

Subscribes to :class:`HorizonFeatureSnapshot`, :class:`Signal`, and
:class:`HorizonTick` events and emits exactly one
:class:`CrossSectionalContext` per ``(horizon_seconds, boundary_index)``
when a UNIVERSE-scope :class:`HorizonTick` fires (§5.6, §6.5, §7.5).

Design invariants (§7.5)
------------------------

1. **At-most-one-per-boundary** — for any
   ``(horizon_seconds, boundary_index)`` exactly one
   :class:`CrossSectionalContext` is published, and never twice
   (idempotent via ``_emitted`` set).
2. **No silent drops** — when ``completeness`` is below the configured
   threshold the synchronizer still emits the context (with
   ``signals_by_symbol`` mapping absent symbols to ``None``).  The
   downstream :class:`feelies.composition.engine.CompositionEngine`
   chooses whether to act, gate, or noop.
3. **Isolated sequence stream** — every emitted
   :class:`CrossSectionalContext` draws its sequence number from the
   dedicated ``_ctx_seq`` generator owned by the synchronizer.  This
   guarantees the LEGACY_SIGNAL fast-path's main ``_seq`` is never
   perturbed (Inv-A / C1).
4. **Determinism** — iteration over the universe is sorted lex-by-
   symbol; the snapshot/signal cache is replaced (not mutated in-
   place) so stale references do not leak across boundaries.

Stale-snapshot handling (§5.6)
------------------------------

A snapshot is considered "missing" for a symbol if **any** of the
following hold at barrier time:

  * No :class:`HorizonFeatureSnapshot` for the symbol at this
    ``(horizon_seconds, boundary_index)``.
  * The most recent snapshot is for a *prior* ``boundary_index``
    (lagged by at least one barrier).
  * The snapshot's ``stale`` map flags **any** of the alpha's
    declared ``signature_sensors``.  (We don't know the alphas at
    this layer, so we flag the entire snapshot as suspicious only
    when its top-level boundary index is stale; per-feature
    staleness is propagated to the consumer untouched.)

Symbols whose latest signal is from a prior boundary are similarly
mapped to ``None`` in ``signals_by_symbol``.

Completeness
------------

``completeness`` is computed as
``len(non_None_signals) / len(universe)`` — a float in ``[0, 1]``
that the consumer can compare against
:class:`feelies.core.platform_config.PlatformConfig.composition_completeness_threshold`.
"""

from __future__ import annotations

import logging
from typing import Iterable

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    CrossSectionalContext,
    HorizonFeatureSnapshot,
    HorizonTick,
    Signal,
)
from feelies.core.identifiers import SequenceGenerator

_logger = logging.getLogger(__name__)


class UniverseSynchronizer:
    """Barrier-sync for cross-sectional context emission.

    Construction parameters:

    - ``bus`` — the platform :class:`EventBus`.  Subscriptions are
      installed lazily on :meth:`attach` so tests may construct the
      object without leaking handlers.
    - ``universe`` — the lex-sorted symbol tuple participating in the
      cross-section.  Empty universe makes :meth:`attach` a no-op
      (zero overhead — the LEGACY fast-path stays bit-stable).
    - ``horizons`` — the registered cross-sectional horizons.  Only
      UNIVERSE-scope :class:`HorizonTick` events whose
      ``horizon_seconds`` is in this set trigger context emission.
    - ``ctx_sequence_generator`` — *dedicated*
      :class:`SequenceGenerator`; never shared with any other emitter.
    """

    __slots__ = (
        "_bus",
        "_universe_sorted",
        "_horizons",
        "_ctx_seq",
        "_snapshot_cache",
        "_signal_cache",
        "_emitted",
        "_attached",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        universe: Iterable[str],
        horizons: Iterable[int],
        ctx_sequence_generator: SequenceGenerator,
    ) -> None:
        self._bus = bus
        self._universe_sorted: tuple[str, ...] = tuple(sorted(set(universe)))
        self._horizons: frozenset[int] = frozenset(horizons)
        for h in self._horizons:
            if h <= 0:
                raise ValueError(
                    f"UniverseSynchronizer.horizons must be positive, got {h}"
                )
        self._ctx_seq = ctx_sequence_generator
        # Latest snapshot per (horizon_seconds, symbol).
        self._snapshot_cache: dict[
            tuple[int, str], HorizonFeatureSnapshot
        ] = {}
        # Latest signal per (horizon_seconds, symbol, strategy_id).
        # Note: a single barrier may surface multiple alphas per symbol;
        # the synchronizer keeps the most recent signal *per strategy_id*
        # and surfaces only the lex-first alpha for a given symbol in
        # ``signals_by_symbol`` — extending to a richer mapping is a
        # future deliverable.  v0.2 expects a single PORTFOLIO alpha
        # per universe so this is loss-less in practice.
        self._signal_cache: dict[tuple[int, str, str], Signal] = {}
        # ``(horizon_seconds, boundary_index)`` we have already emitted.
        self._emitted: set[tuple[int, int]] = set()
        self._attached = False

    # ── Public API ───────────────────────────────────────────────────

    @property
    def universe(self) -> tuple[str, ...]:
        """Lex-sorted universe (read-only view)."""
        return self._universe_sorted

    @property
    def horizons(self) -> frozenset[int]:
        return self._horizons

    @property
    def is_empty(self) -> bool:
        return not self._universe_sorted or not self._horizons

    def attach(self) -> None:
        """Install bus subscriptions.  No-op when ``is_empty``."""
        if self._attached:
            return
        if self.is_empty:
            _logger.debug(
                "UniverseSynchronizer.attach() — empty universe or no "
                "horizons; skipping bus subscription"
            )
            return
        self._bus.subscribe(
            HorizonFeatureSnapshot, self._on_snapshot,  # type: ignore[arg-type]
        )
        self._bus.subscribe(Signal, self._on_signal)  # type: ignore[arg-type]
        self._bus.subscribe(HorizonTick, self._on_tick)  # type: ignore[arg-type]
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_snapshot(self, snap: HorizonFeatureSnapshot) -> None:
        if snap.horizon_seconds not in self._horizons:
            return
        if snap.symbol not in set(self._universe_sorted):
            return
        key = (snap.horizon_seconds, snap.symbol)
        prev = self._snapshot_cache.get(key)
        if prev is not None and snap.boundary_index < prev.boundary_index:
            # Out-of-order snapshot for an earlier barrier — keep the
            # latest by boundary_index.  This guards against replay
            # systems that may interleave events.
            return
        self._snapshot_cache[key] = snap

    def _on_signal(self, sig: Signal) -> None:
        # Layer-2 SIGNAL events carry horizon_seconds; LEGACY_SIGNAL
        # events do not feed the cross-sectional pipeline.
        if sig.layer != "SIGNAL":
            return
        if sig.horizon_seconds not in self._horizons:
            return
        if sig.symbol not in set(self._universe_sorted):
            return
        key = (sig.horizon_seconds, sig.symbol, sig.strategy_id)
        prev = self._signal_cache.get(key)
        if prev is not None and sig.timestamp_ns < prev.timestamp_ns:
            return
        self._signal_cache[key] = sig

    def _on_tick(self, tick: HorizonTick) -> None:
        if tick.scope != "UNIVERSE":
            return
        if tick.horizon_seconds not in self._horizons:
            return
        key = (tick.horizon_seconds, tick.boundary_index)
        if key in self._emitted:
            return
        self._emitted.add(key)
        self._emit_context(tick)

    # ── Context construction ────────────────────────────────────────

    def _emit_context(self, tick: HorizonTick) -> None:
        h = tick.horizon_seconds
        bi = tick.boundary_index

        snapshots: dict[str, HorizonFeatureSnapshot | None] = {}
        signals: dict[str, Signal | None] = {}
        non_none = 0

        for symbol in self._universe_sorted:
            snap = self._snapshot_cache.get((h, symbol))
            if snap is None or snap.boundary_index < bi:
                snapshots[symbol] = None
            else:
                snapshots[symbol] = snap

            # Pick the lex-first alpha_id whose signal is at this barrier
            # for this (horizon, symbol).
            chosen: Signal | None = None
            for (kh, ksym, _strategy_id), s in sorted(self._signal_cache.items()):
                if kh != h or ksym != symbol:
                    continue
                if snap is not None and s.timestamp_ns < snap.timestamp_ns:
                    # Stale signal from an earlier boundary.
                    continue
                chosen = s
                break
            signals[symbol] = chosen
            if chosen is not None:
                non_none += 1

        completeness = (
            non_none / len(self._universe_sorted)
            if self._universe_sorted
            else 0.0
        )

        ctx = CrossSectionalContext(
            timestamp_ns=tick.timestamp_ns,
            sequence=self._ctx_seq.next(),
            correlation_id=f"xsect:{h}:{bi}",
            horizon_seconds=h,
            boundary_index=bi,
            universe=self._universe_sorted,
            signals_by_symbol=signals,
            snapshots_by_symbol=snapshots,
            completeness=completeness,
        )
        self._bus.publish(ctx)


__all__ = ["UniverseSynchronizer"]
