"""Experiment tracker protocol — reproducible research lifecycle.

Defines the interface for tracking experiments from hypothesis
through backtest to promotion.  Concrete implementations are
future work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, kw_only=True)
class ExperimentRecord:
    """Immutable record of a completed experiment."""

    experiment_id: str
    hypothesis_id: str
    config_snapshot: dict[str, Any]
    result_summary: dict[str, Any]
    timestamp_ns: int
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class ExperimentTracker(Protocol):
    """Track experiments from creation through analysis."""

    def start_experiment(
        self,
        hypothesis_id: str,
        config: dict[str, Any],
    ) -> str:
        """Create a new experiment and return its ID."""
        ...

    def log_result(
        self,
        experiment_id: str,
        result: dict[str, Any],
    ) -> None:
        """Record results for an experiment."""
        ...

    def list_experiments(
        self,
        *,
        hypothesis_id: str | None = None,
        tag: str | None = None,
    ) -> list[ExperimentRecord]:
        """Query completed experiments."""
        ...
