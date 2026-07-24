"""Reconstruct gate-close attribution across the SIGNAL→RISK stream migration.

Before Stage-0 dual-permission decoupling
(``dual_permission_actuation_design`` rev 5), a regime gate's ON→OFF force-close
rode a single ``Signal`` FLAT on the **SIGNAL** stream, and post-trade forensics
keyed on that FLAT to recover the unwind's alpha-level provenance
(``trend_mechanism``, ``regime_gate_state``, ``consumed_features``,
``expected_half_life_seconds`` and the G12 disclosed-cost totals).

Under decoupling that FLAT no longer exists for a **promoted** (decoupled)
alpha: the gate publishes a typed
:class:`~feelies.core.events.SafetyStateChange` on the SIGNAL layer and a
risk-layer author (the :class:`~feelies.risk.exit_composer.ExitComposer` on the
fail-closed error paths, or the
:class:`~feelies.risk.deferral_cap.DeferralCapController` at the bounded-deferral
deadline) emits the actual flatten :class:`~feelies.core.events.OrderRequest` on
the **RISK** stream at a new sequence.  The design (§3.1.6, Inv-13) mandates that
"forensics keyed on the SIGNAL-layer FLAT migrates to the composer's reason code
+ this provenance" — i.e. the same attribution must be recoverable from the
flatten order joined to its correlated ``SafetyStateChange``.

This module makes that migration a concrete, reusable capability rather than a
claim.  :class:`GateCloseAttribution` is the path-independent attribution
record; :func:`from_gate_close_flat` extracts it from the legacy SIGNAL FLAT,
and :func:`reconstruct_from_safety_flatten` reconstructs the *identical*
provenance from the decoupled path's ``(OrderRequest, SafetyStateChange)`` pair.
Both expose :attr:`GateCloseAttribution.provenance_key`, so a forensic query can
assert byte-for-byte that promotion preserved attribution while the *actuation
lineage* (which layer flattened, and the reason token) legitimately changed.

Pure and read-only: no clocks, no bus, no I/O — safe for replayable forensics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from feelies.core.events import (
    OrderRequest,
    SafetyStateChange,
    Signal,
    SignalDirection,
    TrendMechanism,
)
from feelies.risk.deferral_cap import DEFERRAL_EXIT_REASONS
from feelies.risk.exit_composer import EXIT_COMPOSER_EXIT_REASONS

# Every RISK-layer reason token that represents a gate-close-derived flatten,
# i.e. an unwind that (pre-decoupling) would have ridden the SIGNAL-layer FLAT.
# The composer authors the fail-closed / revocation exits; the deferral cap
# authors the bounded-deferral deadline exits.
SAFETY_DERIVED_EXIT_REASONS: frozenset[str] = EXIT_COMPOSER_EXIT_REASONS | DEFERRAL_EXIT_REASONS

# Composer reasons copy the triggering ``SafetyStateChange.correlation_id`` onto
# the flatten order, so the join is exact on ``correlation_id``.  Deferral-cap
# reasons instead stamp the triggering ``Trade.correlation_id`` (the event-time
# clock proxy), so those orders join to their safety episode on
# ``(strategy_id, symbol)`` — never on ``correlation_id`` (§2.3, §3.3).
_CORRELATION_JOINED_REASONS: frozenset[str] = EXIT_COMPOSER_EXIT_REASONS

Actuation = Literal["SIGNAL_FLAT", "RISK_FLATTEN"]

# The path-independent provenance identity of a gate-close attribution: the
# alpha-level fields Inv-13 requires to survive the SIGNAL→RISK migration.  The
# actuation lineage (``actuation``, ``source_layer``, ``reason``) is recorded on
# the record but excluded from this key because it *is* what promotion changes.
ProvenanceKey = tuple[
    str,  # strategy_id
    str,  # symbol
    str,  # trend_mechanism name, or "-" when unspecified
    str,  # regime_gate_state
    tuple[str, ...],  # consumed_features
    int,  # expected_half_life_seconds
    float,  # disclosed_cost_total_bps
    float,  # disclosed_margin_ratio
]


class GateCloseAttributionError(ValueError):
    """Raised when a ``(OrderRequest, SafetyStateChange)`` pair cannot be joined.

    A mis-joined pair (wrong strategy/symbol, an order that is not a
    safety-derived flatten, a ``safe=True`` re-arm, or a composer order whose
    ``correlation_id`` does not match its safety event) would silently fabricate
    attribution.  Failing loudly keeps forensics honest.
    """


@dataclass(frozen=True, slots=True)
class GateCloseAttribution:
    """One gate-close unwind's attribution, independent of how it was actuated.

    ``actuation`` records *how* the unwind reached the book — ``"SIGNAL_FLAT"``
    for the legacy inline gate-close FLAT, ``"RISK_FLATTEN"`` for a decoupled
    alpha's risk-layer flatten — and ``reason`` records the specific token
    (a :data:`~feelies.core.events.SafetyReason` on the decoupled path; empty on
    the legacy FLAT, which never carried one).  Neither participates in
    :attr:`provenance_key`, so the same alpha-level provenance compares equal
    across the migration.
    """

    strategy_id: str
    symbol: str
    correlation_id: str
    trend_mechanism: TrendMechanism | None
    regime_gate_state: str
    consumed_features: tuple[str, ...]
    expected_half_life_seconds: int
    disclosed_cost_total_bps: float
    disclosed_margin_ratio: float
    actuation: Actuation
    source_layer: str
    reason: str

    @property
    def provenance_key(self) -> ProvenanceKey:
        """Path-independent Inv-13 provenance identity (excludes actuation)."""
        return (
            self.strategy_id,
            self.symbol,
            self.trend_mechanism.name if self.trend_mechanism is not None else "-",
            self.regime_gate_state,
            self.consumed_features,
            self.expected_half_life_seconds,
            self.disclosed_cost_total_bps,
            self.disclosed_margin_ratio,
        )


def from_gate_close_flat(signal: Signal) -> GateCloseAttribution:
    """Extract attribution from a legacy SIGNAL-layer gate-close FLAT.

    This is the pre-decoupling (non-promoted) path: the ``Signal`` is a FLAT with
    ``regime_gate_state == "OFF"``.  The FLAT carries no
    :data:`~feelies.core.events.SafetyReason`, so ``reason`` is empty — the
    reason token is exactly the extra fidelity the decoupled path's
    ``SafetyStateChange`` adds.
    """
    if signal.direction is not SignalDirection.FLAT:
        raise GateCloseAttributionError(
            f"not a gate-close FLAT: direction={signal.direction.name}"
        )
    if signal.regime_gate_state != "OFF":
        raise GateCloseAttributionError(
            f"gate-close FLAT must carry regime_gate_state='OFF', got {signal.regime_gate_state!r}"
        )
    return GateCloseAttribution(
        strategy_id=signal.strategy_id,
        symbol=signal.symbol,
        correlation_id=signal.correlation_id,
        trend_mechanism=signal.trend_mechanism,
        regime_gate_state=signal.regime_gate_state,
        consumed_features=signal.consumed_features,
        expected_half_life_seconds=signal.expected_half_life_seconds,
        disclosed_cost_total_bps=signal.disclosed_cost_total_bps,
        disclosed_margin_ratio=signal.disclosed_margin_ratio,
        actuation="SIGNAL_FLAT",
        source_layer=signal.source_layer,
        reason="",
    )


def reconstruct_from_safety_flatten(
    order: OrderRequest,
    safety: SafetyStateChange,
) -> GateCloseAttribution:
    """Reconstruct gate-close attribution from a decoupled-path flatten.

    ``order`` is the RISK-layer flatten emitted by the exit composer or deferral
    cap; ``safety`` is the ``SafetyStateChange(safe=False)`` that force-closed the
    gate for the same strategy slice.  The alpha-level provenance is read from
    ``safety`` (which carries the Inv-13 fields), and the actuation lineage from
    ``order``.  The result's :attr:`~GateCloseAttribution.provenance_key` equals
    the one :func:`from_gate_close_flat` would produce for the same gate close —
    that equality *is* the migration guarantee (§3.1.6).

    The join is validated so a mismatched pair cannot fabricate attribution:

    * ``order.reason`` must be a safety-derived flatten reason
      (:data:`SAFETY_DERIVED_EXIT_REASONS`) and ``order.source_layer`` RISK;
    * ``safety.safe`` must be ``False`` (a ``safe=True`` re-arm never flattens);
    * the two must agree on ``(strategy_id, symbol)``;
    * for a composer reason (which copies the safety ``correlation_id``), the
      ``correlation_id`` must match exactly.  A deferral-cap reason carries the
      triggering trade's ``correlation_id`` instead, so that field is *not*
      required to match — the association is the ``(strategy_id, symbol)``
      episode (§2.3).
    """
    if order.reason not in SAFETY_DERIVED_EXIT_REASONS:
        raise GateCloseAttributionError(
            f"order.reason {order.reason!r} is not a safety-derived flatten "
            f"(expected one of {sorted(SAFETY_DERIVED_EXIT_REASONS)})"
        )
    if safety.safe:
        raise GateCloseAttributionError(
            "cannot reconstruct a gate-close from a safe=True (re-arm) event"
        )
    if order.strategy_id != safety.strategy_id or order.symbol != safety.symbol:
        raise GateCloseAttributionError(
            "order/safety slice mismatch: "
            f"order=({order.strategy_id!r},{order.symbol!r}) "
            f"safety=({safety.strategy_id!r},{safety.symbol!r})"
        )
    if order.reason in _CORRELATION_JOINED_REASONS and (
        order.correlation_id != safety.correlation_id
    ):
        raise GateCloseAttributionError(
            f"composer flatten {order.reason!r} must share the safety event's "
            f"correlation_id: order={order.correlation_id!r} "
            f"safety={safety.correlation_id!r}"
        )
    return GateCloseAttribution(
        strategy_id=safety.strategy_id,
        symbol=safety.symbol,
        correlation_id=safety.correlation_id,
        trend_mechanism=safety.trend_mechanism,
        regime_gate_state=safety.regime_gate_state,
        consumed_features=safety.consumed_features,
        expected_half_life_seconds=safety.expected_half_life_seconds,
        disclosed_cost_total_bps=safety.disclosed_cost_total_bps,
        disclosed_margin_ratio=safety.disclosed_margin_ratio,
        actuation="RISK_FLATTEN",
        source_layer=order.source_layer,
        reason=safety.reason,
    )


__all__ = [
    "Actuation",
    "ProvenanceKey",
    "GateCloseAttribution",
    "GateCloseAttributionError",
    "from_gate_close_flat",
    "reconstruct_from_safety_flatten",
    "SAFETY_DERIVED_EXIT_REASONS",
]
