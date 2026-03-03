"""Alert routing protocol — threshold and anomaly-based notifications.

Defines the central alert manager that receives typed alerts from all
layers and routes them based on severity.  Critical and Emergency
alerts activate safety controls autonomously (invariant 11).

Ownership boundary: individual layers define WHAT triggers an alert
and emit ``Alert`` events.  This protocol defines HOW alerts are
routed, acknowledged, and acted upon.
"""

from __future__ import annotations

from typing import Protocol

from feelies.core.events import Alert


class AlertManager(Protocol):
    """Central alert routing and response coordination.

    Severity-based routing:
      INFO      → log only (async review)
      WARNING   → log + dashboard highlight (< 15 min response)
      CRITICAL  → log + push notification (< 1 min response)
      EMERGENCY → automated safety response + notification (immediate)

    Critical and Emergency alerts activate safety controls before
    returning from ``emit()``.  Human review follows but does not
    gate the safety response (invariant 11).

    Failure mode: crash.  If the alert manager is unavailable,
    the system cannot guarantee safety responses.  This is by
    design — the alert manager is a hard dependency for safety.
    """

    def emit(self, alert: Alert) -> None:
        """Route an alert to appropriate channels based on severity.

        For CRITICAL and EMERGENCY: triggers safety controls
        synchronously before returning.
        """
        ...

    def active_alerts(self) -> list[Alert]:
        """Currently active (unresolved) alerts."""
        ...

    def acknowledge(self, alert_name: str, *, operator: str) -> None:
        """Human acknowledgment of an alert.

        Does not deactivate safety controls — those require
        explicit re-authorization via the appropriate protocol
        (e.g., KillSwitch.reset, Orchestrator.unlock_from_lockdown).
        """
        ...
