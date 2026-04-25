"""Alpha module protocol — the pluggable unit of the trading system.

An AlphaModule is the atomic unit of plug/unplug.  It bundles:
  - Metadata (AlphaManifest): hypothesis, falsification, version, risk budget
  - Feature declarations (FeatureDefinition): what features it introduces/needs
  - Signal logic (evaluate): the pure function from features to signal

Alpha modules are registered with the AlphaRegistry before the
orchestrator boots.  The system constructs composite FeatureEngine
and SignalEngine implementations from the registered modules.

The orchestrator never sees AlphaModule directly — it interacts with
the composite engines through the standard FeatureEngine/SignalEngine
protocols (invariant 9: no mode-specific branching, invariant 8:
layer separation preserved).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from feelies.core.events import FeatureVector, Signal
from feelies.features.definition import FeatureDefinition

_TYPE_MAP: dict[str, type] = {
    "int": int,
    "float": float,
    "bool": bool,
    "str": str,
}


# ── Typed parameter schema ──────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ParameterDef:
    """Typed definition for a single alpha parameter.

    Used by the AlphaLoader to validate parameter values from YAML specs
    against declared types and ranges before registration.
    """

    name: str
    param_type: str  # "int", "float", "bool", "str"
    default: int | float | bool | str
    range: tuple[float, float] | None = None
    description: str = ""

    def validate_value(self, value: Any) -> list[str]:
        """Check *value* against this definition's type and range.

        Returns a list of error strings (empty = valid).
        """
        errors: list[str] = []
        expected_type = _TYPE_MAP.get(self.param_type)
        if expected_type is None:
            errors.append(
                f"parameter '{self.name}': unknown type '{self.param_type}'"
            )
            return errors

        if not isinstance(value, expected_type):
            # int is acceptable where float is expected
            if not (self.param_type == "float" and isinstance(value, int)):
                errors.append(
                    f"parameter '{self.name}': expected {self.param_type}, "
                    f"got {type(value).__name__}"
                )
                return errors

        if self.range is not None and isinstance(value, (int, float)):
            lo, hi = self.range
            if value < lo or value > hi:
                errors.append(
                    f"parameter '{self.name}': value {value} "
                    f"outside range [{lo}, {hi}]"
                )

        return errors


# ── Per-alpha risk budget ────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class AlphaRiskBudget:
    """Risk constraints scoped to a single alpha module.

    These feed into the risk engine's per-strategy budget allocation.
    The risk engine is free to enforce tighter limits than declared
    here; these are the alpha's self-declared operating envelope.
    """

    max_position_per_symbol: int
    max_gross_exposure_pct: float
    max_drawdown_pct: float
    capital_allocation_pct: float


# ── Alpha manifest ──────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class AlphaManifest:
    """Immutable metadata for an alpha module (invariant 13: provenance).

    Carries the hypothesis, falsification criteria, versioning, symbol
    scope, parameters, and risk budget — everything needed to audit,
    reproduce, and lifecycle-manage the alpha without opening its code.

    Three-layer architecture additive fields (Phase 1 / 1.1 of
    design_docs/three_layer_architecture.md):

      ``layer`` — declared layer for the alpha.  Post-D.2 the only
                  values produced by the loader are ``"SIGNAL"`` and
                  ``"PORTFOLIO"``.  ``None`` and ``"LEGACY_SIGNAL"``
                  may still appear on hand-built manifests but are
                  rejected at load time.

      ``trend_mechanism`` — opt-in v0.3 ``trend_mechanism:`` block as a
                            raw dict (parsed but not enforced in Phase 1.1
                            per §20.1; consumed by the v0.3 mechanism
                            classification gate G16 in Phase 3.1).

      ``hazard_exit`` — opt-in v0.3 ``hazard_exit:`` block as a raw dict
                        (parsed but not enforced in Phase 1.1 per §20.1;
                        consumed by the composition layer in Phase 4.1).
    """

    alpha_id: str
    version: str
    description: str
    hypothesis: str
    falsification_criteria: tuple[str, ...]
    required_features: frozenset[str]
    symbols: frozenset[str] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    parameter_schema: tuple[ParameterDef, ...] = ()
    risk_budget: AlphaRiskBudget = AlphaRiskBudget(
        max_position_per_symbol=100,
        max_gross_exposure_pct=5.0,
        max_drawdown_pct=1.0,
        capital_allocation_pct=10.0,
    )
    layer: str | None = None
    trend_mechanism: dict[str, Any] | None = None
    hazard_exit: dict[str, Any] | None = None


# ── Alpha module protocol ───────────────────────────────────────────


class AlphaModule(Protocol):
    """Self-contained alpha: features + signal logic + metadata.

    Implementations must satisfy:
      - ``evaluate()`` is a pure function (invariant 5): deterministic,
        no side effects, no state mutation, no I/O.
      - ``feature_definitions()`` returns the features this alpha
        introduces.  Shared features are deduplicated by feature_id +
        version across all registered modules.
      - ``validate()`` performs self-checks and returns a list of error
        strings (empty = valid).
    """

    @property
    def manifest(self) -> AlphaManifest:
        """Immutable metadata describing this alpha."""
        ...

    def feature_definitions(self) -> Sequence[FeatureDefinition]:
        """Feature definitions this alpha introduces.

        May be empty if the alpha only consumes features defined by
        other modules.  Features with the same feature_id + version
        across modules are deduplicated; version conflicts are
        rejected at registration.
        """
        ...

    def evaluate(self, features: FeatureVector) -> Signal | None:
        """Evaluate features into a trading signal.

        Pure function: deterministic, no side effects, no state
        mutation, no I/O (invariant 5).

        Returns Signal when a tradeable condition is detected,
        None when no action is warranted this tick.
        """
        ...

    def validate(self) -> list[str]:
        """Run self-checks before registration.

        Returns a list of error messages.  Empty list means the
        module is valid and ready for registration.
        """
        ...
