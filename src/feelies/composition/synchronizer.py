"""Barrier synchronization for cross-sectional contexts.

A universe-scope horizon tick emits at most one context per boundary. Missing
or stale symbol data is represented as ``None`` rather than dropping the
context. Sorted symbols and a dedicated sequence generator preserve replay
determinism.

Cross-horizon feeders cache the latest causal signal per symbol and strategy.
``completeness`` is the share of universe symbols with any feeder signal; the
composition engine decides whether that share is sufficient.
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
    """Barrier-sync signals into cross-sectional contexts.

    Universe ticks at portfolio horizons trigger emission. Signal horizons may
    include shorter feeder horizons, and context sequences use a dedicated
    generator for deterministic replay.
    """

    __slots__ = (
        "_bus",
        "_universe_sorted",
        "_universe_frozenset",
        "_context_horizons",
        "_signal_horizons",
        "_signal_horizons_sorted",
        "_upstream_strategy_ids",
        "_ctx_seq",
        "_snapshot_cache",
        "_signal_cache",
        "_emitted",
        "_attached",
        "_signal_max_age_seconds",
    )

    def __init__(
        self,
        *,
        bus: EventBus,
        universe: Iterable[str],
        horizons: Iterable[int],
        ctx_sequence_generator: SequenceGenerator,
        signal_horizons: Iterable[int] | None = None,
        upstream_strategy_ids: tuple[str, ...] | None = None,
        signal_max_age_seconds: int | None = None,
    ) -> None:
        self._bus = bus
        self._universe_sorted: tuple[str, ...] = tuple(sorted(set(universe)))
        self._universe_frozenset: frozenset[str] = frozenset(self._universe_sorted)
        self._context_horizons: frozenset[int] = frozenset(horizons)
        self._signal_horizons: frozenset[int] = (
            frozenset(signal_horizons)
            if signal_horizons is not None
            else frozenset(self._context_horizons)
        )
        self._signal_horizons_sorted: tuple[int, ...] = tuple(
            sorted(self._signal_horizons),
        )
        self._upstream_strategy_ids: tuple[str, ...] = tuple(
            sorted(set(upstream_strategy_ids or ())),
        )
        for h in self._context_horizons:
            if h <= 0:
                raise ValueError(f"UniverseSynchronizer.horizons must be positive, got {h}")
        for h in self._signal_horizons:
            if h <= 0:
                raise ValueError(f"UniverseSynchronizer.signal_horizons must be positive, got {h}")
        if signal_max_age_seconds is not None and signal_max_age_seconds <= 0:
            raise ValueError(
                "UniverseSynchronizer.signal_max_age_seconds must be positive, "
                f"got {signal_max_age_seconds}"
            )
        # None uses the decision horizon as the feeder-signal age limit.
        self._signal_max_age_seconds: int | None = signal_max_age_seconds
        self._ctx_seq = ctx_sequence_generator
        # Latest snapshot per (horizon_seconds, symbol).
        self._snapshot_cache: dict[tuple[int, str], HorizonFeatureSnapshot] = {}
        # Latest signal per (horizon_seconds, symbol, strategy_id).
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
        """Portfolio decision horizons that emit contexts."""
        return self._context_horizons

    @property
    def is_empty(self) -> bool:
        return not self._universe_sorted or not self._context_horizons

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
        self._bus.subscribe(HorizonFeatureSnapshot, self._on_snapshot)
        self._bus.subscribe(Signal, self._on_signal)
        self._bus.subscribe(HorizonTick, self._on_tick)
        self._attached = True

    # ── Bus handlers ─────────────────────────────────────────────────

    def _on_snapshot(self, snap: HorizonFeatureSnapshot) -> None:
        if snap.horizon_seconds not in self._context_horizons:
            return
        if snap.symbol not in self._universe_frozenset:
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
        if sig.layer != "SIGNAL":
            return
        if sig.horizon_seconds not in self._signal_horizons:
            return
        if sig.symbol not in self._universe_frozenset:
            return
        key = (sig.horizon_seconds, sig.symbol, sig.strategy_id)
        prev = self._signal_cache.get(key)
        if prev is not None and sig.timestamp_ns < prev.timestamp_ns:
            return
        self._signal_cache[key] = sig

    def _on_tick(self, tick: HorizonTick) -> None:
        if tick.scope != "UNIVERSE":
            return
        if tick.horizon_seconds not in self._context_horizons:
            return
        key = (tick.horizon_seconds, tick.boundary_index)
        if key in self._emitted:
            return
        self._emitted.add(key)
        self._emit_context(tick)

    def _max_age_ns(self, portfolio_h: int) -> int:
        """Stale-feeder window in nanos for a context at horizon *portfolio_h*."""
        window_s = (
            self._signal_max_age_seconds
            if self._signal_max_age_seconds is not None
            else portfolio_h
        )
        return window_s * 1_000_000_000

    def _pick_feeder_signal(
        self,
        *,
        symbol: str,
        strategy_id: str,
        portfolio_h: int,
        boundary_ts_ns: int,
        snap: HorizonFeatureSnapshot | None,
        boundary_index: int,
    ) -> Signal | None:
        """Latest causal, non-stale ``Signal`` for *strategy_id* at the barrier."""
        max_age_ns = self._max_age_ns(portfolio_h)
        candidates: list[tuple[int, Signal]] = []
        for kh in self._signal_horizons_sorted:
            s = self._signal_cache.get((kh, symbol, strategy_id))
            if s is not None:
                candidates.append((kh, s))
        if not candidates:
            return None
        # Causal (ts ≤ barrier) AND non-stale (age ≤ window): a signal carried
        # Signals from an earlier boundary are dropped, not counted.
        candidates = [
            (kh, s)
            for kh, s in candidates
            if s.timestamp_ns <= boundary_ts_ns and boundary_ts_ns - s.timestamp_ns <= max_age_ns
        ]
        if not candidates:
            return None

        same_h = [(kh, s) for kh, s in candidates if kh == portfolio_h]
        if same_h and snap is not None and snap.boundary_index >= boundary_index:
            aligned = [s for kh, s in same_h if s.timestamp_ns >= snap.timestamp_ns]
            if aligned:
                return max(aligned, key=lambda s: s.timestamp_ns)

        # Cross-horizon feeders: latest observation at or before the barrier.
        return max((s for _, s in candidates), key=lambda s: s.timestamp_ns)

    # ── Context construction ───────────────────────────────────────

    def _emit_context(self, tick: HorizonTick) -> None:
        h = tick.horizon_seconds
        bi = tick.boundary_index

        snapshots: dict[str, HorizonFeatureSnapshot | None] = {}
        for symbol in self._universe_sorted:
            snap = self._snapshot_cache.get((h, symbol))
            if snap is None or snap.boundary_index < bi:
                snapshots[symbol] = None
            else:
                snapshots[symbol] = snap

        signals_by_strategy: dict[str, dict[str, Signal | None]] = {}
        if self._upstream_strategy_ids:
            for symbol in self._universe_sorted:
                snap = snapshots[symbol]
                signals_by_strategy[symbol] = {
                    sid: self._pick_feeder_signal(
                        symbol=symbol,
                        strategy_id=sid,
                        portfolio_h=h,
                        boundary_ts_ns=tick.timestamp_ns,
                        snap=snap,
                        boundary_index=bi,
                    )
                    for sid in self._upstream_strategy_ids
                }

        signals: dict[str, Signal | None] = {}
        non_none = 0
        # Feeder-signal age limit for the single-slot path.
        legacy_max_age_ns = self._max_age_ns(h)

        # Hoisted out of the per-symbol loop below: the cache sort is
        # independent of ``symbol`` so computing it once is O(S log S)
        # instead of O(U x S log S).  Same key order, same break-on-first
        # selection, so the emitted context is bit-identical (Inv-5).
        sorted_signal_cache = (
            sorted(self._signal_cache.items()) if not self._upstream_strategy_ids else []
        )

        for symbol in self._universe_sorted:
            snap = snapshots[symbol]

            if self._upstream_strategy_ids:
                row = signals_by_strategy[symbol]
                chosen: Signal | None = None
                for sid in self._upstream_strategy_ids:
                    s = row.get(sid)
                    if s is not None:
                        chosen = s
                        break
                signals[symbol] = chosen
                if any(v is not None for v in row.values()):
                    non_none += 1
                continue

            chosen = None
            for (kh, ksym, _strategy_id), s in sorted_signal_cache:
                if kh != h or ksym != symbol:
                    continue
                # Never admit a signal stamped after the barrier.
                if s.timestamp_ns > tick.timestamp_ns:
                    continue
                # Stale signals cannot inflate completeness.
                if tick.timestamp_ns - s.timestamp_ns > legacy_max_age_ns:
                    continue
                if snap is not None and s.timestamp_ns < snap.timestamp_ns:
                    continue
                chosen = s
                break
            signals[symbol] = chosen
            if chosen is not None:
                non_none += 1

        # Completeness counts signals that pass barrier, snapshot, and age filters.
        completeness = non_none / len(self._universe_sorted) if self._universe_sorted else 0.0

        ctx = CrossSectionalContext(
            timestamp_ns=tick.timestamp_ns,
            sequence=self._ctx_seq.next(),
            correlation_id=f"xsect:{h}:{bi}",
            horizon_seconds=h,
            boundary_index=bi,
            universe=self._universe_sorted,
            signals_by_symbol=signals,
            signals_by_strategy_by_symbol=signals_by_strategy,
            snapshots_by_symbol=snapshots,
            completeness=completeness,
        )
        self._bus.publish(ctx)


__all__ = ["UniverseSynchronizer"]
