"""Alpha metadata and layer-specific module protocols.

Modules register metadata and feature requirements before startup. Signal and
portfolio subclasses expose the evaluation hooks used by the event pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

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
    # ``range`` marks an optimization knob; ``bounds`` only validates values.
    range: tuple[float, float] | None = None
    bounds: tuple[float, float] | None = None
    description: str = ""

    def validate_value(self, value: Any) -> list[str]:
        """Check *value* against this definition's type, range, and bounds.

        Returns a list of error strings (empty = valid).
        """
        errors: list[str] = []
        expected_type = _TYPE_MAP.get(self.param_type)
        if expected_type is None:
            errors.append(f"parameter '{self.name}': unknown type '{self.param_type}'")
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
                errors.append(f"parameter '{self.name}': value {value} outside range [{lo}, {hi}]")

        # Reject overrides outside the YAML validation envelope.
        if self.bounds is not None and isinstance(value, (int, float)):
            blo, bhi = self.bounds
            if value < blo or value > bhi:
                errors.append(
                    f"parameter '{self.name}': value {value} outside bounds [{blo}, {bhi}]"
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

    Three-layer architecture fields:

      ``layer`` — declared ``SIGNAL`` or ``PORTFOLIO`` layer.

      ``trend_mechanism`` — optional mechanism classification block.

      ``hazard_exit`` — optional hazard-exit policy block.

      ``safety_exit_policy`` — optional Stage-0 dual-permission actuation
      block (``mode`` + bounded-deferral ceilings).  Absent ⇒ the default
      ``gate_close_flat`` behaviour (immediate flatten on gate-OFF).

      ``gate_thresholds_overrides`` — validated per-alpha promotion thresholds.
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
    safety_exit_policy: dict[str, Any] | None = None
    gate_thresholds_overrides: dict[str, Any] | None = None
    lifecycle_cap: str | None = None


# ── Alpha module protocol ───────────────────────────────────────────


class AlphaModule(Protocol):
    """Self-contained alpha: feature declarations + manifest metadata.

    Implementations must satisfy:
      - ``feature_definitions()`` returns the features this alpha
        introduces.  Shared features are deduplicated by feature_id +
        version across all registered modules.
      - ``validate()`` performs self-checks and returns a list of error
        strings (empty = valid).

    Layer-specific subclasses expose evaluation through the signal and
    composition pipelines.
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

    def validate(self) -> list[str]:
        """Run self-checks before registration.

        Returns a list of error messages.  Empty list means the
        module is valid and ready for registration.
        """
        ...
