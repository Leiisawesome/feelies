"""MetricCollector — cross-layer metric recording protocol.

The Protocol lives in core so sensors and signals can name it without
importing the monitoring package.
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
