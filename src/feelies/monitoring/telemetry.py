"""Monitoring and telemetry — cross-cutting observability layer.

Every other layer emits telemetry into this layer via MetricEvent
on the bus.  This layer defines HOW metrics are collected, stored,
and surfaced.  Individual layers define WHAT they emit.

Metrics collected at p50, p95, p99, p99.9 where applicable.
"""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import MetricEvent


class MetricCollector(Protocol):
    """Collects and aggregates metrics emitted by all layers."""

    def record(self, metric: MetricEvent) -> None:
        """Record a metric observation."""
        ...

    def flush(self) -> None:
        """Flush buffered metrics to storage."""
        ...
