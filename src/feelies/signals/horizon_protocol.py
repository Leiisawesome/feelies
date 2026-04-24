"""HorizonSignal protocol — Layer-2 signal contract (Phase 3).

A ``HorizonSignal`` is a pure, stateless function that maps a
:class:`feelies.core.events.HorizonFeatureSnapshot` (the Layer-2
feature aggregate at a horizon boundary) and the latest
:class:`feelies.core.events.RegimeState` for the same symbol to an
optional :class:`feelies.core.events.Signal`.

Three-layer architecture (§5.5, §6.4 of
``design_docs/three_layer_architecture.md``):

    Sensor (Layer 1) ──► HorizonAggregator (Layer 2)
                          │
                          ▼
                    HorizonFeatureSnapshot
                          │
                          ▼
                  HorizonSignalEngine ──► Signal(layer="SIGNAL")

Design choices:

- **Pure function** — Implementations must be deterministic, hold no
  per-instance mutable state, and avoid wall-clock reads.  The
  :class:`feelies.signals.horizon_engine.HorizonSignalEngine` may
  call ``evaluate`` from multiple call sites (live, replay, smoke
  test); identical inputs must produce identical outputs (Inv-5).
- **Regime in, regime not consulted internally** — The engine
  resolves the latest ``RegimeState`` for the snapshot's symbol and
  threads it in as an argument.  Implementations must never reach
  into the regime engine themselves; this preserves the read-only
  boundary on the regime layer (§5.4).
- **Optional signal** — Returning ``None`` is the canonical "no
  trade this boundary" answer.  The engine never publishes a
  ``Signal`` event when ``evaluate`` returns ``None``.

This protocol is **strictly additive**: the legacy per-tick
:class:`feelies.signals.engine.SignalEngine` Protocol is preserved
verbatim under ``layer="LEGACY_SIGNAL"`` (§7.6 / Inv-A in the Phase-3
plan).  No existing code path is modified by adding this protocol.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from feelies.core.events import HorizonFeatureSnapshot, RegimeState, Signal


@runtime_checkable
class HorizonSignal(Protocol):
    """Layer-2 horizon-anchored signal contract.

    Implementations satisfy a single method, ``evaluate``, that maps
    ``(snapshot, regime, params)`` to ``Signal | None``.

    Determinism (Inv-5) — two identical input triples must produce
    identical outputs.  ``params`` is treated as immutable; mutating
    it is undefined behavior.

    Stateless — implementations carry no per-instance fields beyond
    metadata (``signal_id``, ``signal_version``).  All per-symbol
    state lives in upstream sensors / horizon features and reaches
    ``evaluate`` via the snapshot.
    """

    signal_id: str
    signal_version: str

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        params: Mapping[str, Any],
    ) -> Signal | None:
        """Evaluate a horizon-feature snapshot into an optional signal.

        Parameters
        ----------
        snapshot :
            Layer-2 horizon-bucketed feature aggregate emitted by
            :class:`feelies.features.aggregator.HorizonAggregator` at
            the current horizon boundary.
        regime :
            Latest ``RegimeState`` for ``snapshot.symbol`` (read-only
            view from :class:`feelies.services.regime_engine.RegimeEngine`).
            ``None`` when the regime engine has not produced a
            posterior yet for this symbol; implementations should
            treat this as "regime unknown" and typically return
            ``None`` to suppress emission.
        params :
            Bound alpha parameters (the validated ``parameters:``
            block from the YAML spec).  Must be treated as immutable.

        Returns
        -------
        Signal | None
            A new :class:`Signal` with ``layer="SIGNAL"`` when a
            tradeable condition is detected, or ``None`` when no
            action is warranted at this boundary.  The engine wraps
            the returned signal with sequence / correlation_id /
            ``regime_gate_state`` / ``consumed_features`` provenance
            before publishing on the bus.
        """
        ...


__all__ = ["HorizonSignal"]
