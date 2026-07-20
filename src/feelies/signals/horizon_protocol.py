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
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from feelies.core.events import HorizonFeatureSnapshot, RegimeState, Signal


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


__all__ = ["HorizonSignal"]
