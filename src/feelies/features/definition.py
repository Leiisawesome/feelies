"""Declarative feature definitions for registry-based computation.

A FeatureDefinition describes a single feature's identity, dependencies,
warm-up requirements, and computation logic.  Alpha modules declare
feature definitions; the CompositeFeatureEngine collects and executes
them in dependency order.

Deduplication: when multiple alphas declare the same feature_id with
the same version, the feature is computed once.  Version conflicts
(same feature_id, different version) are rejected at registration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from feelies.core.events import NBBOQuote, Trade


# ── Warm-up specification ────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class WarmUpSpec:
    """Declares the minimum history a feature needs before it is reliable.

    A feature is considered warm once BOTH thresholds are met:
    at least ``min_events`` updates AND at least ``min_duration_ns``
    nanoseconds since first update.  Set either to 0 to disable
    that dimension.
    """

    min_events: int = 0
    min_duration_ns: int = 0

    def __post_init__(self) -> None:
        if self.min_events < 0:
            raise ValueError(
                f"WarmUpSpec.min_events must be >= 0, got {self.min_events}"
            )
        if self.min_duration_ns < 0:
            raise ValueError(
                f"WarmUpSpec.min_duration_ns must be >= 0, got {self.min_duration_ns}"
            )


# ── Feature computation protocol ────────────────────────────────────


class FeatureComputation(Protocol):
    """Incremental update logic for a single feature.

    Implementations must be deterministic: same event sequence and
    state produce the same output value (invariant 5).

    State is owned by the composite engine and passed in as a mutable
    dict.  The computation reads/writes state entries but never
    replaces the dict itself.
    """

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        """Compute the feature value given the current quote and state.

        Must advance state exactly once per call (incremental).
        """
        ...

    def initial_state(self) -> dict[str, Any]:
        """Return the starting state for a new symbol.

        The returned dict is owned by the engine; the computation
        mutates it in-place via ``update()``.
        """
        ...

    def update_trade(self, trade: Trade, state: dict[str, Any]) -> float | None:
        """Optionally update state on trade events.

        Returns the updated feature value, or ``None`` if this feature
        does not consume trade events.  The default is no-op (``None``),
        preserving backward compatibility for quote-only features.
        """
        return None


# ── Feature definition ──────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class FeatureDefinition:
    """Declarative description of a single feature.

    Registered with the CompositeFeatureEngine via AlphaModule.
    Multiple alphas may declare the same feature_id + version
    (deduplicated); conflicting versions are rejected.
    """

    feature_id: str
    version: str
    description: str
    depends_on: frozenset[str] = frozenset()
    warm_up: WarmUpSpec = WarmUpSpec()
    memory_budget_bytes: int = 1_048_576  # 1 MB default
    compute: FeatureComputation
