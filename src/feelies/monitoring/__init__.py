"""Monitoring layer — cross-cutting observability."""

from feelies.monitoring.alerting import AlertManager
from feelies.monitoring.health import ComponentHealth, HealthCheck, HealthRegistry, HealthStatus
from feelies.monitoring.kill_switch import KillSwitch
from feelies.monitoring.structured_logging import LogLevel, StructuredLogger
from feelies.monitoring.telemetry import MetricCollector

__all__ = [
    "AlertManager",
    "ComponentHealth",
    "HealthCheck",
    "HealthRegistry",
    "HealthStatus",
    "KillSwitch",
    "LogLevel",
    "MetricCollector",
    "StructuredLogger",
]
