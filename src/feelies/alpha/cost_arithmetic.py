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

Cost basis (audit P1-1)
-----------------------

``cost_total_bps`` sums a **single** crossing: ``half_spread`` is half
the quoted spread (one side) and ``fee`` is one taker fee.  This is a
**one-way** cost.  Inv-12 ("expected_edge > 1.5x round_trip_cost", and
survive 1.5x cost / 2x latency) is stated on a **round-trip** basis,
which crosses the spread and pays fees twice — roughly
``2 x cost_total_bps`` (see
:func:`feelies.execution.cost_model.estimate_round_trip_cost_bps`, which
prices entry + exit legs).  Therefore the disclosed ``margin_ratio`` is a
one-way figure and is ~2x more generous than the round-trip survival
margin; a disclosed ``margin_ratio`` of 1.6 corresponds to an
``edge / round_trip`` of ~0.8.

The disclosed ``cost_basis`` field (default ``"one_way"``) records this
explicitly so downstream consumers do not mistake the one-way disclosure
for a round-trip survival margin.  The authoritative round-trip Inv-12
check is the orchestrator's runtime **B4 gate**
(``signal_min_edge_cost_ratio`` x round-trip cost,
``kernel/orchestrator.py``); this load-time gate is a coarse disclosure
floor, not the round-trip survival test.

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

# Accepted ``cost_basis`` declarations (audit P1-1).  ``one_way`` (the
# default and the basis the component fields actually express) sums a
# single crossing; ``round_trip`` declares the author has already
# doubled the crossing costs.  The round-trip approximation factor below
# converts a one-way ``cost_total_bps`` into a round-trip estimate.
_VALID_COST_BASES: frozenset[str] = frozenset({"one_way", "round_trip"})
DEFAULT_COST_BASIS: str = "one_way"
ROUND_TRIP_FACTOR: float = 2.0


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
    cost_basis: str = DEFAULT_COST_BASIS

    @property
    def cost_total_bps(self) -> float:
        """Arithmetic sum of the three cost components (as disclosed)."""
        return self.half_spread_bps + self.impact_bps + self.fee_bps

    @property
    def round_trip_cost_bps(self) -> float:
        """Round-trip cost estimate for the Inv-12 survival comparison.

        When ``cost_basis == "one_way"`` (the default) the disclosed
        components describe a single crossing, so the round-trip estimate
        is ``ROUND_TRIP_FACTOR x cost_total_bps``.  When the author has
        already disclosed round-trip components (``cost_basis ==
        "round_trip"``) the total is used as-is.  This is an approximation
        (it ignores entry/exit asymmetry); the authoritative round-trip
        figure is the runtime B4 cost model.
        """
        if self.cost_basis == "round_trip":
            return self.cost_total_bps
        return ROUND_TRIP_FACTOR * self.cost_total_bps

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
                f"alpha {alpha_id!r}: cost_arithmetic block is mandatory for layer: SIGNAL alphas"
            )
        if not isinstance(spec, Mapping):
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic must be a mapping, got {type(spec).__name__}"
            )

        missing = tuple(f for f in _REQUIRED_FIELDS if f not in spec)
        if missing:
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic missing required "
                f"field(s) {missing}; required: {_REQUIRED_FIELDS}"
            )

        # cost_basis (audit P1-1) — optional; defaults to one-way, the
        # basis the component fields actually express.  Reject anything
        # other than the two documented values so a typo can't silently
        # disable the round-trip survival reconciliation downstream.
        cost_basis = spec.get("cost_basis", DEFAULT_COST_BASIS)
        if not isinstance(cost_basis, str) or cost_basis not in _VALID_COST_BASES:
            raise CostArithmeticError(
                f"alpha {alpha_id!r}: cost_arithmetic.cost_basis must be "
                f"one of {sorted(_VALID_COST_BASES)}, got {cost_basis!r}"
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
                    f"alpha {alpha_id!r}: cost_arithmetic.{f} must be finite, got {v!r}"
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
                    f"alpha {alpha_id!r}: cost_arithmetic.{f} must be >= 0, got {values[f]!r}"
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
            cost_basis=cost_basis,
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
    "DEFAULT_COST_BASIS",
    "ROUND_TRIP_FACTOR",
    "compute_margin_ratio",
]
