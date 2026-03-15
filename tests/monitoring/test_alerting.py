"""Tests for the AlertManager protocol contract."""

from __future__ import annotations

from feelies.core.events import Alert, AlertSeverity


class SimpleAlertManager:
    """Minimal concrete AlertManager implementation for testing the protocol."""

    def __init__(self) -> None:
        self._alerts: list[Alert] = []
        self._acknowledged: set[str] = set()

    def emit(self, alert: Alert) -> None:
        self._alerts.append(alert)

    def active_alerts(self) -> list[Alert]:
        return [a for a in self._alerts if a.alert_name not in self._acknowledged]

    def acknowledge(self, alert_name: str, *, operator: str) -> None:
        self._acknowledged.add(alert_name)


def _make_alert(
    name: str,
    severity: AlertSeverity = AlertSeverity.WARNING,
) -> Alert:
    return Alert(
        timestamp_ns=1_000_000_000,
        correlation_id="corr-1",
        sequence=1,
        severity=severity,
        layer="test",
        alert_name=name,
        message=f"Alert: {name}",
    )


class TestAlertManager:
    def test_emit_stores_alert(self) -> None:
        mgr = SimpleAlertManager()
        alert = _make_alert("high_spread")
        mgr.emit(alert)
        assert len(mgr.active_alerts()) == 1
        assert mgr.active_alerts()[0].alert_name == "high_spread"

    def test_active_alerts_returns_unacknowledged(self) -> None:
        mgr = SimpleAlertManager()
        mgr.emit(_make_alert("alert_a"))
        mgr.emit(_make_alert("alert_b"))
        assert len(mgr.active_alerts()) == 2

    def test_acknowledge_removes_from_active(self) -> None:
        mgr = SimpleAlertManager()
        mgr.emit(_make_alert("alert_a"))
        mgr.emit(_make_alert("alert_b"))
        mgr.acknowledge("alert_a", operator="trader_1")
        active = mgr.active_alerts()
        assert len(active) == 1
        assert active[0].alert_name == "alert_b"

    def test_acknowledge_all_leaves_no_active(self) -> None:
        mgr = SimpleAlertManager()
        mgr.emit(_make_alert("only_one"))
        mgr.acknowledge("only_one", operator="ops")
        assert mgr.active_alerts() == []

    def test_emit_multiple_severities(self) -> None:
        mgr = SimpleAlertManager()
        mgr.emit(_make_alert("info_alert", AlertSeverity.INFO))
        mgr.emit(_make_alert("crit_alert", AlertSeverity.CRITICAL))
        active = mgr.active_alerts()
        assert len(active) == 2
        severities = {a.severity for a in active}
        assert severities == {AlertSeverity.INFO, AlertSeverity.CRITICAL}
