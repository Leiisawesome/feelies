"""Health check protocol — per-component health reporting and aggregation.

Every component reports its health through a standardized interface.
The health registry aggregates reports into a system-wide health view.

Degraded or failed health feeds into the alert manager and may
activate safety controls (capital throttle, circuit breaker).

Health checks are a monitoring concern that spans all layers.
Individual layers implement ``HealthCheck``; the monitoring layer
owns the ``HealthRegistry`` that aggregates them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol


class ComponentHealth(Enum):
    """Component health states."""

    HEALTHY = auto()
    DEGRADED = auto()
    FAILED = auto()


@dataclass(frozen=True, kw_only=True)
class HealthStatus:
    """Health report from a single component."""

    component: str
    layer: str
    status: ComponentHealth
    message: str = ""
    last_check_ns: int = 0


class HealthCheck(Protocol):
    """Health reporting interface for a single component.

    Each layer implements this for its key components.
    Must complete quickly — health checks must not block
    the critical tick-to-trade path.
    """

    def check(self) -> HealthStatus:
        """Return current health status."""
        ...


class HealthRegistry(Protocol):
    """Aggregates health checks from all registered components.

    Owned by the monitoring layer.  Other layers register their
    health checks at startup; the registry polls them on demand
    or on a schedule.

    Failure mode: degrade.  If a registered check raises, that
    component is reported as FAILED rather than crashing the
    registry.
    """

    def register(self, name: str, check: HealthCheck) -> None:
        """Register a component's health check."""
        ...

    def check_all(self) -> dict[str, HealthStatus]:
        """Run all registered health checks and return results."""
        ...

    def system_healthy(self) -> bool:
        """True only if every registered component reports HEALTHY."""
        ...
