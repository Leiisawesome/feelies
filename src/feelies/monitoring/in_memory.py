"""In-memory monitoring implementations for backtest and testing.

Provides concrete implementations of MetricCollector, AlertManager,
and KillSwitch that store state in memory.  Suitable for backtest
mode where metrics are analyzed post-run rather than streamed to
external systems, and for integration tests.

These are the simplest correct implementations.  Production
implementations would route to external time-series databases,
notification systems, and persistent audit logs.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from feelies.core.events import Alert, AlertSeverity, MetricEvent

logger = logging.getLogger(__name__)


# ── InMemoryMetricCollector ─────────────────────────────────────────


@dataclass
class MetricSummary:
    """Aggregated summary for a single named metric."""

    count: int = 0
    total: float = 0.0
    min_value: float = float("inf")
    max_value: float = float("-inf")
    last_value: float = 0.0

    def record(self, value: float) -> None:
        self.count += 1
        self.total += value
        self.last_value = value
        if value < self.min_value:
            self.min_value = value
        if value > self.max_value:
            self.max_value = value

    @property
    def mean(self) -> float:
        return self.total / self.count if self.count > 0 else 0.0


class InMemoryMetricCollector:
    """Collects MetricEvents in memory for post-run analysis.

    Satisfies the MetricCollector protocol.

    Raw events are retained for replay analysis.  Summaries are
    computed incrementally for quick access during and after a run.
    """

    __slots__ = ("_events", "_summaries", "_flushed", "_store_raw_events")

    def __init__(self) -> None:
        self._events: list[MetricEvent] = []
        self._summaries: dict[str, MetricSummary] = defaultdict(MetricSummary)
        self._flushed: bool = False
        # Set to False to skip raw-event storage and avoid large list
        # reallocations in long backtest runs (~11M entries → 91 MB buffer).
        # Summaries are always updated regardless of this flag.
        self._store_raw_events: bool = True

    def record(self, metric: MetricEvent) -> None:
        if self._store_raw_events:
            self._events.append(metric)
        key = f"{metric.layer}.{metric.name}"
        self._summaries[key].record(metric.value)

    def flush(self) -> None:
        self._flushed = True
        if self._events:
            logger.debug(
                "MetricCollector flushed: %d events across %d metrics",
                len(self._events),
                len(self._summaries),
            )

    @property
    def events(self) -> list[MetricEvent]:
        return list(self._events)

    @property
    def summaries(self) -> dict[str, MetricSummary]:
        return dict(self._summaries)

    def get_summary(self, layer: str, name: str) -> MetricSummary | None:
        key = f"{layer}.{name}"
        return self._summaries.get(key)

    def events_by_layer(self, layer: str) -> list[MetricEvent]:
        return [e for e in self._events if e.layer == layer]

    def clear(self) -> None:
        self._events.clear()
        self._summaries.clear()
        self._flushed = False


# ── InMemoryAlertManager ────────────────────────────────────────────


class InMemoryAlertManager:
    """Stores alerts in memory and routes by severity.

    Satisfies the AlertManager protocol.

    For CRITICAL and EMERGENCY alerts, if a kill_switch is provided,
    it is activated synchronously before returning from emit()
    (invariant 11: fail-safe default).
    """

    __slots__ = ("_alerts", "_acknowledged", "_kill_switch")

    def __init__(self, kill_switch: InMemoryKillSwitch | None = None) -> None:
        self._alerts: list[Alert] = []
        self._acknowledged: set[str] = set()
        self._kill_switch = kill_switch

    def emit(self, alert: Alert) -> None:
        self._alerts.append(alert)
        if alert.severity in (AlertSeverity.CRITICAL, AlertSeverity.EMERGENCY):
            logger.warning(
                "Safety alert [%s]: %s — %s",
                alert.severity.name,
                alert.alert_name,
                alert.message,
            )
            if self._kill_switch is not None and alert.severity == AlertSeverity.EMERGENCY:
                self._kill_switch.activate(
                    reason=f"alert:{alert.alert_name}",
                    activated_by="alert_manager",
                )

    def active_alerts(self) -> list[Alert]:
        return [a for a in self._alerts if a.alert_name not in self._acknowledged]

    def acknowledge(self, alert_name: str, *, operator: str) -> None:
        self._acknowledged.add(alert_name)
        logger.info("Alert '%s' acknowledged by %s", alert_name, operator)

    @property
    def all_alerts(self) -> list[Alert]:
        return list(self._alerts)

    def clear(self) -> None:
        self._alerts.clear()
        self._acknowledged.clear()


# ── InMemoryKillSwitch ──────────────────────────────────────────────


@dataclass
class KillSwitchRecord:
    """Audit record for a kill switch activation or reset."""

    action: str
    reason: str
    actor: str
    audit_token: str = ""


class InMemoryKillSwitch:
    """In-memory kill switch with audit trail.

    Satisfies the KillSwitch protocol.

    Once activated, the kill switch blocks all new order submissions
    until manually reset with an audit token (invariant 11: safety
    controls only tighten autonomously; loosening requires human
    re-authorization).
    """

    __slots__ = ("_active", "_history")

    def __init__(self) -> None:
        self._active: bool = False
        self._history: list[KillSwitchRecord] = []

    @property
    def is_active(self) -> bool:
        return self._active

    def activate(self, reason: str, *, activated_by: str = "automated") -> None:
        self._active = True
        self._history.append(KillSwitchRecord(
            action="activate",
            reason=reason,
            actor=activated_by,
        ))
        logger.warning("Kill switch ACTIVATED by %s: %s", activated_by, reason)

    def reset(self, *, operator: str, audit_token: str) -> None:
        was_active = self._active
        self._active = False
        self._history.append(KillSwitchRecord(
            action="reset",
            reason="manual_reset",
            actor=operator,
            audit_token=audit_token,
        ))
        if was_active:
            logger.info(
                "Kill switch RESET by %s (token: %s)", operator, audit_token,
            )

    @property
    def history(self) -> list[KillSwitchRecord]:
        return list(self._history)
