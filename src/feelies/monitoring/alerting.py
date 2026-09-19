"""Alert routing protocol — threshold and anomaly-based notifications.

Defines the central alert manager that receives typed alerts from all
layers and routes them based on severity.  Critical and Emergency
alerts activate safety controls autonomously (invariant 11).

Ownership boundary: individual layers define WHAT triggers an alert
and emit ``Alert`` events.  This protocol defines HOW alerts are
routed, acknowledged, and acted upon.
"""

from __future__ import annotations

from feelies.core.alert_manager import AlertManager as AlertManager
