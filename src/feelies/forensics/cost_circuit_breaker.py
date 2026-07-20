"""Evaluate and apply cost-based alpha quarantine decisions.

``evaluate_cost_circuit_breaker`` is a pure function of fills and policy.
``apply_cost_circuit_breaker`` writes lifecycle state and must run only at a
session or epoch boundary. Insufficient fill history produces no action.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Protocol, Sequence, runtime_checkable

from feelies.alpha.promotion_evidence import QuarantineTriggerEvidence
from feelies.forensics.cost_survival import per_alpha_cost_survival
from feelies.forensics.decay_detector import DecayDetector
from feelies.storage.trade_journal import TradeRecord

# Actions (ordered most → least severe for summaries).
ACTION_QUARANTINE = "QUARANTINE"
ACTION_WATCH = "WATCH"
ACTION_OK = "OK"
ACTION_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, kw_only=True)
class CircuitBreakerPolicy:
    """Thresholds for the cost circuit-breaker.

    ``min_fills`` is the persistence bar — below it the breaker abstains
    (``INSUFFICIENT_EVIDENCE``) rather than demote on noise.  ``cover``
    margin is the hard trip (realized edge must at least cover modeled
    cost); ``survival`` margin is the Inv-12 bar below which a still-
    profitable alpha is put on ``WATCH``.
    """

    min_fills: int = 30
    cover_margin_ratio: float = 1.0
    survival_margin_ratio: float = 1.5
    quarantine_on_decay: bool = True


@dataclass(frozen=True, kw_only=True)
class CircuitBreakerDecision:
    """One alpha's circuit-breaker decision + the evidence behind it."""

    strategy_id: str
    action: str
    reason: str
    n_fills: int
    net: float
    mean_edge_bps: float
    mean_cost_bps: float
    realized_margin_ratio: float
    decay_z: float | None


@runtime_checkable
class _Quarantinable(Protocol):
    """Structural type the driver needs from an alpha lifecycle."""

    @property
    def is_live(self) -> bool: ...

    def quarantine(
        self,
        reason: str,
        *,
        structured_evidence: Sequence[object] | None = None,
        correlation_id: str = "",
    ) -> None: ...


def evaluate_cost_circuit_breaker(
    records: Iterable[TradeRecord],
    *,
    policy: CircuitBreakerPolicy | None = None,
) -> list[CircuitBreakerDecision]:
    """Decide a circuit-breaker action per alpha from a window of fills.

    Pure and deterministic.  Decisions are returned in cost-survival order
    (worst net first is *not* imposed here — order follows
    :func:`per_alpha_cost_survival`, i.e. net descending).
    """
    pol = policy or CircuitBreakerPolicy()
    # Both cost survival and decay detection consume the records.
    records = list(records)
    rows = per_alpha_cost_survival(
        records,
        min_margin_ratio=pol.survival_margin_ratio,
        min_fills=pol.min_fills,
    )

    by_alpha: dict[str, list[TradeRecord]] = {}
    for rec in records:
        by_alpha.setdefault(rec.strategy_id, []).append(rec)
    detector = DecayDetector()

    decisions: list[CircuitBreakerDecision] = []
    for row in rows:
        decay_signals = detector.detect_edge_decay(row.strategy_id, by_alpha[row.strategy_id])
        decay_z = max((d.z_score for d in decay_signals), default=None)
        margin = row.realized_margin_ratio

        if row.n_fills < pol.min_fills:
            action, reason = (
                ACTION_INSUFFICIENT,
                f"{row.n_fills} fills (< {pol.min_fills}); not enough to demote on",
            )
        elif row.net <= 0.0:
            action, reason = (
                ACTION_QUARANTINE,
                f"net {row.net:+.2f} <= 0 over {row.n_fills} fills (paying fees for no edge)",
            )
        elif pol.quarantine_on_decay and decay_signals:
            action, reason = (
                ACTION_QUARANTINE,
                f"edge decay detected (z={decay_z:.2f})",
            )
        elif row.mean_cost_bps > 0.0 and margin < pol.cover_margin_ratio:
            action, reason = (
                ACTION_QUARANTINE,
                f"realized edge {row.mean_edge_bps:.2f} bps does not cover cost "
                f"{row.mean_cost_bps:.2f} bps (margin {margin:.2f})",
            )
        elif row.mean_cost_bps > 0.0 and margin < pol.survival_margin_ratio:
            action, reason = (
                ACTION_WATCH,
                f"profitable but margin {margin:.2f} < {pol.survival_margin_ratio:g}x (fragile)",
            )
        else:
            action, reason = (
                ACTION_OK,
                f"net {row.net:+.2f}, margin {margin:.2f}",
            )

        decisions.append(
            CircuitBreakerDecision(
                strategy_id=row.strategy_id,
                action=action,
                reason=reason,
                n_fills=row.n_fills,
                net=row.net,
                mean_edge_bps=row.mean_edge_bps,
                mean_cost_bps=row.mean_cost_bps,
                realized_margin_ratio=margin,
                decay_z=decay_z,
            )
        )
    return decisions


def apply_cost_circuit_breaker(
    decisions: Iterable[CircuitBreakerDecision],
    lifecycles: Mapping[str, _Quarantinable],
    *,
    correlation_id: str = "",
) -> list[CircuitBreakerDecision]:
    """Drive ``LIVE -> QUARANTINED`` for each QUARANTINE decision whose
    alpha is currently LIVE.  Returns the decisions actually applied.

    MUST be called at a session / epoch boundary (never per-tick) — see the
    module docstring.  Non-LIVE alphas are skipped: a RESEARCH/PAPER alpha
    cannot be quarantined (the gate that blocks its *promotion* is the
    relevant control there).
    """
    applied: list[CircuitBreakerDecision] = []
    for decision in decisions:
        if decision.action != ACTION_QUARANTINE:
            continue
        lifecycle = lifecycles.get(decision.strategy_id)
        if lifecycle is None or not lifecycle.is_live:
            continue
        lifecycle.quarantine(
            f"cost-circuit-breaker: {decision.reason}",
            structured_evidence=[_decision_to_quarantine_evidence(decision)],
            correlation_id=correlation_id,
        )
        applied.append(decision)
    return applied


def _decision_to_quarantine_evidence(
    decision: CircuitBreakerDecision,
) -> QuarantineTriggerEvidence:
    """Project a circuit-breaker decision into structured quarantine evidence.

    Inv-13: the durable ledger entry should carry *why* the alpha was demoted
    in machine-readable form, not only a free-text reason.  The cost-survival
    breaker is a different trigger model than the documented decay-metric
    thresholds, so the realized signals are recorded faithfully:

    * the qualitative trip drivers go into ``crowding_symptoms`` as tags;
    * the realized gross margin is exposed via ``pnl_compression_ratio_5d``
      (clamped to ``>= 0``) so a genuine cost bleed (margin <= 0) crosses the
      documented quarantine threshold and is not mislabelled spurious.

    A trip that keys only on a fragile-but-positive margin or a decay z-score
    may still draw a ``validate_quarantine_trigger`` "spurious-looking" flag;
    that is benign — the demotion is fail-safe (Inv-11) and the free-form
    ``reason`` records the real driver.
    """
    symptoms: list[str] = []
    if decision.net <= 0.0:
        symptoms.append("net_negative_over_window")
    if decision.mean_cost_bps > 0.0 and decision.realized_margin_ratio < 1.0:
        symptoms.append("realized_edge_below_cost")
    if decision.decay_z is not None and decision.decay_z > 2.0:
        symptoms.append("edge_decay_zscore")

    margin = decision.realized_margin_ratio
    compression = 1.0 if not math.isfinite(margin) else max(0.0, margin)

    return QuarantineTriggerEvidence(
        crowding_symptoms=tuple(symptoms),
        pnl_compression_ratio_5d=compression,
    )


__all__ = [
    "ACTION_QUARANTINE",
    "ACTION_WATCH",
    "ACTION_OK",
    "ACTION_INSUFFICIENT",
    "CircuitBreakerPolicy",
    "CircuitBreakerDecision",
    "evaluate_cost_circuit_breaker",
    "apply_cost_circuit_breaker",
]
