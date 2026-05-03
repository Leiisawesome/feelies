"""Cost-arithmetic disclosure gate (G12).

Every ``layer: SIGNAL`` (and ``layer: PORTFOLIO``) alpha must declare
a ``cost_arithmetic:`` block:

    cost_arithmetic:
      edge_estimate_bps: 8.0
      half_spread_bps:    2.0
      impact_bps:         1.0
      fee_bps:            0.5
      margin_ratio:       1.8

The block is **disclosed** by the alpha author and **validated** by
the platform.  Validation is purely arithmetic: there is no place for
opinion in this gate.

Rules (§9 / §12 of ``docs/three_layer_architecture.md`` and
the canonical example in §6.5 of the legacy doc):

1. All five fields must be present and finite (``int`` or ``float``).
2. ``edge_estimate_bps`` and ``margin_ratio`` must be strictly
   positive.  ``half_spread_bps``, ``impact_bps``, ``fee_bps`` must be
   non-negative.
3. ``cost_total_bps = half_spread_bps + impact_bps + fee_bps``.
4. ``computed_margin_ratio = edge_estimate_bps / max(cost_total_bps, eps)``.
5. The disclosed ``margin_ratio`` must satisfy
   ``abs(computed - declared) <= 0.05`` (tolerance for rounding in
   YAML literals).
6. The declared ``margin_ratio`` must be ``>= 1.5`` per
   §9 (canonical hypothesis-survival threshold) — alphas with
   thinner margins are rejected at load time.

Failure raises :class:`CostArithmeticError` with a structured message
naming the alpha, the offending field, and the computed numbers.
The exception is a sub-class of ``ValueError`` so existing alpha
loaders that wrap parse errors in ``ValueError`` continue to surface
it without code changes.

Runtime (Inv-12 complement): :class:`HorizonSignalEngine` stamps the
validated totals onto each emitted ``Signal`` as ``disclosed_*`` fields.
The orchestrator B4 gate uses :func:`feelies.execution.cost_model.estimate_round_trip_cost_bps`;
fills whose modeled ``cost_bps`` exceed ``MIN_MARGIN_RATIO ×``
``disclosed_cost_total_bps`` emit a forensic ``Alert`` (they do not
block replay — Inv-11 prefers observability over speculative rejects).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping


_REQUIRED_FIELDS: tuple[str, ...] = (
    "edge_estimate_bps",
    "half_spread_bps",
    "impact_bps",
    "fee_bps",
    "margin_ratio",
)


# §9: minimum margin ratio.  An alpha whose disclosed (or computed)
# margin is below 1.5 cannot survive cost shocks and is refused at
# load time.  The constant is centralised here so tests and downstream
# checks (Phase 4 trader-net-edge gate) can import the same number.
MIN_MARGIN_RATIO: float = 1.5

# Tolerance for the disclosed-vs-computed margin-ratio reconciliation.
# YAML floats round to a few digits in practice; 0.05 (5%) is wide
# enough to absorb that without letting an author understate cost.
MARGIN_RATIO_TOLERANCE: float = 0.05


class CostArithmeticError(ValueError):
    """Raised when a ``cost_arithmetic:`` block fails validation.

    Sub-classes ``ValueError`` so any existing loader that catches
    ``ValueError`` to surface YAML-parse errors continues to work
    unchanged; new code can catch :class:`CostArithmeticError` to
    distinguish the gate failure path.
    """


@dataclass(frozen=True, kw_only=True)
class CostArithmetic:
    """Validated cost-arithmetic disclosure block.

    Constructed via :meth:`from_spec`; the constructor itself is
    intentionally permissive so tests can build instances directly
    with already-validated numbers.
    """

    edge_estimate_bps: float
    half_spread_bps: float
    impact_bps: float
    fee_bps: float
    margin_ratio: float

    @property
    def cost_total_bps(self) -> float:
        """Arithmetic sum of the three cost components."""
        return self.half_spread_bps + self.impact_bps + self.fee_bps

    @property
    def computed_margin_ratio(self) -> float:
        """Recomputed margin ratio from the disclosed component fields.

        Uses :func:`compute_margin_ratio` to ensure the same formula
        is used everywhere (loader, validator, tests).
        """
        return compute_margin_ratio(
            edge_bps=self.edge_estimate_bps,
            half_spread_bps=self.half_spread_bps,
            impact_bps=self.impact_bps,
            fee_bps=self.fee_bps,
        )

    @classmethod
    def from_spec(
        cls,
        *,
        alpha_id: str,
        spec: Mapping[str, Any] | None,
    ) -> "CostArithmetic":
        """Validate and parse a ``cost_arithmetic:`` mapping.

        Raises :class:`CostArithmeticError` on any failure.  The
        message always begins with ``"alpha {alpha_id!r}: ..."`` so
        log triage by alpha id is straightforward.
        """
        if spec is None:
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic block is "
                f"mandatory for layer: SIGNAL alphas"
            )
        if not isinstance(spec, Mapping):
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic must be a "
                f"mapping, got {type(spec).__name__}"
            )

        missing = tuple(f for f in _REQUIRED_FIELDS if f not in spec)
        if missing:
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic missing required "
                f"field(s) {missing}; required: {_REQUIRED_FIELDS}"
            )

        values: dict[str, float] = {}
        for f in _REQUIRED_FIELDS:
            raw = spec[f]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise CostArithmeticError(
                    f"alpha {alpha_id!r}: cost_arithmetic.{f} must be "
                    f"a number, got {type(raw).__name__}"
                )
            v = float(raw)
            if not math.isfinite(v):
                raise CostArithmeticError(
                    f"alpha {alpha_id!r}: cost_arithmetic.{f} must be "
                    f"finite, got {v!r}"
                )
            values[f] = v

        if values["edge_estimate_bps"] <= 0:
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic.edge_estimate_bps "
                f"must be > 0, got {values['edge_estimate_bps']!r}"
            )
        for f in ("half_spread_bps", "impact_bps", "fee_bps"):
            if values[f] < 0:
                raise CostArithmeticError(
                    f"alpha {alpha_id!r}: cost_arithmetic.{f} must be "
                    f">= 0, got {values[f]!r}"
                )

        declared_margin = values["margin_ratio"]
        if declared_margin < MIN_MARGIN_RATIO:
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic.margin_ratio "
                f"must be >= {MIN_MARGIN_RATIO!r} (hypothesis-survival "
                f"floor); declared {declared_margin!r}"
            )

        computed = compute_margin_ratio(
            edge_bps=values["edge_estimate_bps"],
            half_spread_bps=values["half_spread_bps"],
            impact_bps=values["impact_bps"],
            fee_bps=values["fee_bps"],
        )
        if abs(computed - declared_margin) > MARGIN_RATIO_TOLERANCE:
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: declared margin_ratio "
                f"{declared_margin!r} disagrees with computed "
                f"{computed:.4f} (tolerance "
                f"{MARGIN_RATIO_TOLERANCE!r}); reconcile the "
                f"cost_arithmetic block"
            )

        return cls(
            edge_estimate_bps=values["edge_estimate_bps"],
            half_spread_bps=values["half_spread_bps"],
            impact_bps=values["impact_bps"],
            fee_bps=values["fee_bps"],
            margin_ratio=declared_margin,
        )


def compute_margin_ratio(
    *,
    edge_bps: float,
    half_spread_bps: float,
    impact_bps: float,
    fee_bps: float,
) -> float:
    """Pure helper — ``edge_bps / (half_spread + impact + fee)``.

    Returns ``+inf`` when total cost is exactly zero (rare; only happens
    for synthetic test fixtures).  Callers in production paths should
    not encounter that branch because :class:`CostArithmetic.from_spec`
    refuses zero edge and the cost components are non-negative; if all
    three cost components are zero the ratio is mathematically
    undefined and the gate is effectively bypassed by definition.
    """
    cost = float(half_spread_bps) + float(impact_bps) + float(fee_bps)
    if cost <= 0:
        return float("inf")
    return float(edge_bps) / cost


__all__ = [
    "CostArithmetic",
    "CostArithmeticError",
    "MIN_MARGIN_RATIO",
    "MARGIN_RATIO_TOLERANCE",
    "compute_margin_ratio",
]
