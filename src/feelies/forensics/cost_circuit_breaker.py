"""Evaluate cost-based alpha quarantine recommendations.

``evaluate_cost_circuit_breaker`` is a pure function of fills and policy.
``QuarantineRecommendation`` is the engine-12 output: evidence plus a
recommendation. Engine 5 performs the ``LIVE -> QUARANTINED`` write.
Insufficient fill history produces no action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

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
    run_fingerprint: str = ""


@dataclass(frozen=True, kw_only=True)
class QuarantineRecommendation:
    """Engine-12 recommendation that engine 5 may demote a LIVE alpha.

    Engine 12 emits this; it does not write lifecycle state.
    """

    strategy_id: str
    reason: str
    n_fills: int
    net: float
    mean_edge_bps: float
    mean_cost_bps: float
    realized_margin_ratio: float
    decay_z: float | None
    run_fingerprint: str = ""

    @classmethod
    def from_decision(cls, decision: CircuitBreakerDecision) -> QuarantineRecommendation:
        return cls(
            strategy_id=decision.strategy_id,
            reason=decision.reason,
            n_fills=decision.n_fills,
            net=decision.net,
            mean_edge_bps=decision.mean_edge_bps,
            mean_cost_bps=decision.mean_cost_bps,
            realized_margin_ratio=decision.realized_margin_ratio,
            decay_z=decision.decay_z,
            run_fingerprint=decision.run_fingerprint,
        )

    @classmethod
    def from_decisions(
        cls, decisions: Iterable[CircuitBreakerDecision]
    ) -> tuple[QuarantineRecommendation, ...]:
        return tuple(
            cls.from_decision(d) for d in decisions if d.action == ACTION_QUARANTINE
        )


def evaluate_cost_circuit_breaker(
    records: Iterable[TradeRecord],
    *,
    policy: CircuitBreakerPolicy | None = None,
    run_fingerprint: str = "",
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
        run_fingerprint=run_fingerprint,
    )

    by_alpha: dict[str, list[TradeRecord]] = {}
    for rec in records:
        by_alpha.setdefault(rec.strategy_id, []).append(rec)
    detector = DecayDetector()

    decisions: list[CircuitBreakerDecision] = []
    for row in rows:
        decay_signals = detector.detect_edge_decay(
            row.strategy_id,
            by_alpha[row.strategy_id],
            run_fingerprint=run_fingerprint,
        )
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
                run_fingerprint=run_fingerprint,
            )
        )
    return decisions


__all__ = [
    "ACTION_QUARANTINE",
    "ACTION_WATCH",
    "ACTION_OK",
    "ACTION_INSUFFICIENT",
    "CircuitBreakerPolicy",
    "CircuitBreakerDecision",
    "QuarantineRecommendation",
    "evaluate_cost_circuit_breaker",
]
