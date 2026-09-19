"""Layer-2 horizon signal contract.

``HorizonSignal`` maps a feature snapshot and the symbol's latest regime to an
optional signal:

    Sensor (Layer 1) ──► HorizonAggregator (Layer 2)
                          │
                          ▼
                    HorizonFeatureSnapshot
                          │
                          ▼
                  HorizonSignalEngine ──► Signal(layer="SIGNAL")

Implementations are pure and stateless. The engine supplies regime state, so
implementations do not query the regime layer. ``None`` means no signal at the
current boundary.

The Protocol lives in core so alpha can name it without importing the
signals package.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from feelies.core.events import (
    Event,
    HorizonFeatureSnapshot,
    HorizonTick,
    RegimeState,
    Signal,
)


@runtime_checkable
class HorizonSignal(Protocol):
    """Pure mapping from ``(snapshot, regime, params)`` to ``Signal | None``."""

    signal_id: str
    signal_version: str

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        params: Mapping[str, Any],
    ) -> Signal | None:
        """Return a signal for a horizon snapshot, or ``None``.

        Treat ``regime=None`` as unknown and ``params`` as immutable. The engine
        adds sequence, correlation, gate, and feature provenance before publish.
        """
        ...


class HorizonScheduler(Protocol):
    """Emits horizon-boundary ticks from quote and trade events."""

    def on_event(self, event: Event) -> tuple[HorizonTick, ...]:
        """Return ticks whose boundaries the event crossed, or an empty tuple."""
        ...


class HorizonSignalEngine(Protocol):
    """Layer-2 engine over registered ``HorizonSignal`` implementations."""

    @property
    def is_empty(self) -> bool:
        """True iff no SIGNAL alphas have been registered."""
        ...


__all__ = ["HorizonSignal", "HorizonScheduler", "HorizonSignalEngine"]
