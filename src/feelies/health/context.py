"""Inputs bundled for health checks — tolerant of missing artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, kw_only=True)
class HealthCheckContext:
    """All information needed to evaluate alpha health.

    Tabular artifacts are represented as sequences of row mappings (e.g. CSV rows).
    """

    alpha_name: str
    run_id: str
    created_at_ns: int
    config: Any  # HealthConfig — avoid circular import in typing-only usage
    metadata: Mapping[str, Any] = field(default_factory=dict)
    feature_names: tuple[str, ...] = ()
    signals: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    trades: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    pnl_series: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    orders: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    fills: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    regime_rows: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    execution_variants: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    robustness_summary: Mapping[str, Any] = field(default_factory=dict)
    existing_strategy_equity: Mapping[str, Sequence[float]] = field(default_factory=dict)
    artifacts_path: Path | None = None
    repo_commit: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["HealthCheckContext"]
