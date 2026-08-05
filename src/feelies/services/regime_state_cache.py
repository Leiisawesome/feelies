"""Last-published ``RegimeState`` per ``(symbol, engine_name)``.

Regime is a *shared* input: the signal layer gates entries on it and the risk
layer scales limits by it.  They used to read it two different ways — the signal
engine from ``RegimeState`` events on the bus, the risk engine and position sizer
by calling ``current_state()`` on the live :class:`~feelies.services.regime_engine.RegimeEngine`
object.

Within a tick those agree by construction: ``posterior()`` is the only tick-path
mutator and :meth:`Orchestrator._update_regime` publishes immediately after it.
But "agree by construction" is a property of two call sites staying in step, not
something the types enforce, and it breaks the moment posteriors are populated
without a publish.  ``restore()`` already does exactly that — it is only harmless
today because no disk-backed ``FeatureSnapshotStore`` exists to restore from.

This cache makes the published event the single read path, so a consumer cannot
observe engine state that was never announced.  It holds only what crossed the
bus; an engine mutation that publishes nothing is invisible here, which is the
point.

Determinism (Inv-5): pure storage keyed on event fields, no clock reads.  The
multi-engine fallback selects by highest ``timestamp_ns`` so the choice never
depends on dict insertion order.
"""

from __future__ import annotations

import logging

from feelies.bus.event_bus import EventBus
from feelies.core.events import RegimeState

_logger = logging.getLogger(__name__)


class RegimeStateCache:
    """Bus-attached read model over published :class:`RegimeState` events."""

    __slots__ = ("_bus", "_by_key", "_attached")

    def __init__(self, *, bus: EventBus) -> None:
        self._bus = bus
        self._by_key: dict[tuple[str, str], RegimeState] = {}
        self._attached = False

    # ── Wiring ───────────────────────────────────────────────────────

    def attach(self) -> None:
        if self._attached:
            return
        self._bus.subscribe(RegimeState, self.record)
        self._attached = True

    def record(self, event: RegimeState) -> None:
        """Store the latest state for ``(symbol, engine_name)``."""
        self._by_key[(event.symbol, event.engine_name)] = event

    # ── Reads ────────────────────────────────────────────────────────

    def for_engine(self, symbol: str, engine_name: str) -> RegimeState | None:
        """The latest state published by a named engine, or ``None``."""
        return self._by_key.get((symbol, engine_name))

    def latest(self, symbol: str) -> RegimeState | None:
        """The most recently published state for *symbol*, across engines.

        ``None`` when nothing has been published yet — a cold start, or a symbol
        whose regime has not been announced.  Every consumer must treat that as
        missing data and tighten, never as permission (Inv-11).

        Ambiguity is resolved by highest ``timestamp_ns`` rather than insertion
        order so replays agree, and logged so a multi-engine deployment that
        forgot to declare an engine name is visible in production.
        """
        best: RegimeState | None = None
        best_engine: str | None = None
        count = 0
        for (sym, engine), state in self._by_key.items():
            if sym != symbol:
                continue
            count += 1
            if best is None or state.timestamp_ns > best.timestamp_ns:
                best = state
                best_engine = engine
        if count > 1:
            _logger.warning(
                "RegimeStateCache: regime lookup for symbol %s found %d engines "
                "(%r selected by latest timestamp); declare engine_name to remove "
                "the ambiguity",
                symbol,
                count,
                best_engine,
            )
        return best

    def forget(self, symbol: str) -> None:
        """Drop every cached state for *symbol* (delisting / clean restart)."""
        self._by_key = {k: v for k, v in self._by_key.items() if k[0] != symbol}


__all__ = ["RegimeStateCache"]
