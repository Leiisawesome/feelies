"""Session-end reconciliation (close-the-loop: the operational boundary job).

Run **once per session / epoch** (never per-tick) over a rolling window of
fills to close the loop:

1. **Automate** — the cost circuit-breaker auto-quarantines LIVE alphas that
   persistently fail cost survival (``cost_circuit_breaker``).
2. **Calibrate** — rebuild the per-alpha edge realization factors and write
   them to the durable, versioned :class:`EdgeCalibrationStore` that the
   next run's B4 gate reads at construction (``edge_calibration``).

Both are **boundary actions** writing versioned durable state (promotion
ledger + calibration JSON); the *next* run reads that state at load, so
replay within any single run stays bit-identical (Inv-5).

Wiring point: call :func:`reconcile_session` from a PAPER/LIVE session-end /
EOD job with (a) the rolling fill window from the trade journal, (b) the LIVE
alpha lifecycles, (c) the disclosed edges from the loaded alphas, and (d) the
``EdgeCalibrationStore`` pointed at the same path the platform config's
``edge_calibration_path`` references.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from feelies.forensics.cost_circuit_breaker import (
    CircuitBreakerDecision,
    CircuitBreakerPolicy,
    _Quarantinable,
    apply_cost_circuit_breaker,
    evaluate_cost_circuit_breaker,
)
from feelies.forensics.edge_calibration import (
    DEFAULT_LCB_Z,
    DEFAULT_MIN_FILLS,
    EdgeCalibration,
    EdgeCalibrationStore,
    build_edge_calibrations,
)
from feelies.storage.trade_journal import TradeRecord


@dataclass(frozen=True, kw_only=True)
class SessionReconcileResult:
    """Outcome of a session-end reconciliation."""

    decisions: list[CircuitBreakerDecision]
    quarantined: list[CircuitBreakerDecision]
    calibrations: dict[str, EdgeCalibration]


def reconcile_session(
    records: Iterable[TradeRecord],
    *,
    disclosed_edges: Mapping[str, float],
    lifecycles: Mapping[str, _Quarantinable] | None = None,
    calibration_store: EdgeCalibrationStore | None = None,
    calibration_version: str = "session",
    policy: CircuitBreakerPolicy | None = None,
    z: float = DEFAULT_LCB_Z,
    min_fills: int = DEFAULT_MIN_FILLS,
    correlation_id: str = "",
) -> SessionReconcileResult:
    """Run the circuit-breaker + edge-calibration update over a fill window.

    ``records`` is the rolling window (caller-chosen — that is what makes a
    quarantine "persistent").  ``lifecycles`` (LIVE alphas) and
    ``calibration_store`` are optional: omit ``lifecycles`` to compute
    decisions without demoting; omit ``calibration_store`` to skip persisting
    the new factors.  Pure aside from the two durable writes (ledger +
    calibration JSON).

    The ``min_fills`` kwarg is the *shared* persistence bar for both layers
    in this single boundary job: it gates the edge-calibration build **and**
    the circuit-breaker's ``INSUFFICIENT_EVIDENCE`` floor, so a fill window
    can never simultaneously yield a calibrated haircut and a "not enough
    fills to demote" abstention (and vice-versa).  Any ``policy.min_fills``
    is overridden by this kwarg for that reason.
    """
    materialized = list(records)

    effective_policy = replace(policy or CircuitBreakerPolicy(), min_fills=min_fills)
    decisions = evaluate_cost_circuit_breaker(materialized, policy=effective_policy)
    quarantined: list[CircuitBreakerDecision] = []
    if lifecycles:
        quarantined = apply_cost_circuit_breaker(
            decisions, lifecycles, correlation_id=correlation_id
        )

    calibrations = build_edge_calibrations(
        materialized, disclosed_edges, z=z, min_fills=min_fills
    )
    if calibration_store is not None:
        calibration_store.save(calibrations, version=calibration_version)

    return SessionReconcileResult(
        decisions=decisions,
        quarantined=quarantined,
        calibrations=calibrations,
    )


def disclosed_edges_from_registry(registry: object) -> dict[str, float]:
    """Best-effort ``strategy_id -> edge_estimate_bps`` from a loaded
    alpha registry/modules.

    Accepts (in order of preference) an :class:`AlphaRegistry` exposing
    ``active_alphas()``, an object exposing ``modules()``, or any iterable
    of loaded modules exposing ``manifest.alpha_id`` and a ``cost``
    (``CostArithmetic``) with ``edge_estimate_bps``.  Returns an empty
    dict when the shape is unknown (the caller can always supply
    ``disclosed_edges`` directly).
    """
    out: dict[str, float] = {}
    iterable: object
    active_alphas = getattr(registry, "active_alphas", None)
    modules = getattr(registry, "modules", None)
    if callable(active_alphas):
        iterable = active_alphas()
    elif callable(modules):
        iterable = modules()
    else:
        iterable = registry
    try:
        for module in iterable:  # type: ignore[union-attr]
            manifest = getattr(module, "manifest", None)
            cost = getattr(module, "cost", None)
            alpha_id = getattr(manifest, "alpha_id", None)
            edge = getattr(cost, "edge_estimate_bps", None)
            if isinstance(alpha_id, str) and isinstance(edge, (int, float)):
                out[alpha_id] = float(edge)
    except TypeError:
        return out
    return out


__all__ = [
    "SessionReconcileResult",
    "reconcile_session",
    "disclosed_edges_from_registry",
]
