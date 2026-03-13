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
    """

    alpha_id: str
    version: str
    description: str
    hypothesis: str
    falsification_criteria: tuple[str, ...]
    required_features: frozenset[str]
    symbols: frozenset[str] | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    risk_budget: AlphaRiskBudget = AlphaRiskBudget(
        max_position_per_symbol=100,
        max_gross_exposure_pct=5.0,
        max_drawdown_pct=1.0,
        capital_allocation_pct=10.0,
    )


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
