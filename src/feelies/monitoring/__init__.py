"""Monitoring layer — cross-cutting observability."""

from feelies.monitoring.alerting import AlertManager
from feelies.monitoring.in_memory import (
    InMemoryAlertManager,
    InMemoryKillSwitch,
    InMemoryMetricCollector,
)
from feelies.monitoring.kill_switch import KillSwitch
from feelies.monitoring.telemetry import MetricCollector

__all__ = [
    "AlertManager",
    "InMemoryAlertManager",
    "InMemoryKillSwitch",
    "InMemoryMetricCollector",
    "KillSwitch",
    "MetricCollector",
]
