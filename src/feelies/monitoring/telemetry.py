"""Monitoring and telemetry — cross-cutting observability layer.

Every other layer emits telemetry into this layer via MetricEvent
on the bus.  This layer defines HOW metrics are collected, stored,
and surfaced.  Individual layers define WHAT they emit.

Metrics collected at p50, p95, p99, p99.9 where applicable.

The Protocol lives in :mod:`feelies.core.metric_collector` so engines 2
and 4 can name it without importing the monitoring package. This module
re-exports it; Engine 11 implementations keep importing from here.
"""

from __future__ import annotations

from feelies.core.metric_collector import MetricCollector

__all__ = ["MetricCollector"]
