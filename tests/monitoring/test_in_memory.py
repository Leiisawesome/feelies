"""Tests for in-memory monitoring implementations."""

from __future__ import annotations

import pytest

from feelies.core.events import Alert, AlertSeverity, MetricEvent, MetricType
from feelies.monitoring.in_memory import (
    InMemoryAlertManager,
    InMemoryKillSwitch,
    InMemoryMetricCollector,
    MetricSummary,
)


def _metric(layer: str, name: str, value: float) -> MetricEvent:
    return MetricEvent(
        timestamp_ns=1_000_000_000,
        correlation_id="c1",
        sequence=1,
        layer=layer,
        name=name,
        value=value,
        metric_type=MetricType.GAUGE,
    )


def _alert(
    name: str,
    severity: AlertSeverity = AlertSeverity.WARNING,
) -> Alert:
    return Alert(
        timestamp_ns=1_000_000_000,
        correlation_id="c1",
        sequence=1,
        severity=severity,
        layer="test",
        alert_name=name,
        message=f"Alert: {name}",
    )


# ── MetricCollector ─────────────────────────────────────────────────


class TestInMemoryMetricCollector:
    def test_record_stores_event(self) -> None:
        mc = InMemoryMetricCollector()
        mc.record(_metric("kernel", "tick_latency_ns", 500.0))
        assert len(mc.events) == 1

    def test_summary_tracks_min_max_mean(self) -> None:
        mc = InMemoryMetricCollector()
        mc.record(_metric("kernel", "latency", 100.0))
        mc.record(_metric("kernel", "latency", 300.0))
        mc.record(_metric("kernel", "latency", 200.0))
        s = mc.get_summary("kernel", "latency")
        assert s is not None
        assert s.count == 3
        assert s.min_value == 100.0
        assert s.max_value == 300.0
        assert s.mean == 200.0

    def test_summary_last_value(self) -> None:
        mc = InMemoryMetricCollector()
        mc.record(_metric("risk", "exposure", 10.0))
        mc.record(_metric("risk", "exposure", 25.0))
        s = mc.get_summary("risk", "exposure")
        assert s is not None
        assert s.last_value == 25.0

    def test_events_by_layer_filters(self) -> None:
        mc = InMemoryMetricCollector()
        mc.record(_metric("kernel", "ticks", 1.0))
        mc.record(_metric("risk", "checks", 1.0))
        mc.record(_metric("kernel", "ticks", 2.0))
        assert len(mc.events_by_layer("kernel")) == 2
        assert len(mc.events_by_layer("risk")) == 1

    def test_flush_marks_flushed(self) -> None:
        mc = InMemoryMetricCollector()
        mc.record(_metric("x", "y", 1.0))
        mc.flush()
        assert mc._flushed is True

    def test_clear_resets(self) -> None:
        mc = InMemoryMetricCollector()
        mc.record(_metric("x", "y", 1.0))
        mc.clear()
        assert len(mc.events) == 0
        assert len(mc.summaries) == 0

    def test_unknown_summary_returns_none(self) -> None:
        mc = InMemoryMetricCollector()
        assert mc.get_summary("x", "y") is None

    def test_satisfies_protocol(self) -> None:
        from feelies.monitoring.telemetry import MetricCollector

        mc = InMemoryMetricCollector()
        assert hasattr(mc, "record")
        assert hasattr(mc, "flush")


# ── AlertManager ────────────────────────────────────────────────────


class TestInMemoryAlertManager:
    def test_emit_stores_alert(self) -> None:
        am = InMemoryAlertManager()
        am.emit(_alert("high_spread"))
        assert len(am.active_alerts()) == 1

    def test_acknowledge_removes_from_active(self) -> None:
        am = InMemoryAlertManager()
        am.emit(_alert("a"))
        am.emit(_alert("b"))
        am.acknowledge("a", operator="ops")
        active = am.active_alerts()
        assert len(active) == 1
        assert active[0].alert_name == "b"

    def test_emergency_activates_kill_switch(self) -> None:
        ks = InMemoryKillSwitch()
        am = InMemoryAlertManager(kill_switch=ks)
        am.emit(_alert("meltdown", AlertSeverity.EMERGENCY))
        assert ks.is_active is True

    def test_critical_does_not_activate_kill_switch(self) -> None:
        ks = InMemoryKillSwitch()
        am = InMemoryAlertManager(kill_switch=ks)
        am.emit(_alert("high_latency", AlertSeverity.CRITICAL))
        assert ks.is_active is False

    def test_all_alerts_includes_acknowledged(self) -> None:
        am = InMemoryAlertManager()
        am.emit(_alert("x"))
        am.acknowledge("x", operator="ops")
        assert len(am.all_alerts) == 1
        assert len(am.active_alerts()) == 0

    def test_clear_resets(self) -> None:
        am = InMemoryAlertManager()
        am.emit(_alert("x"))
        am.acknowledge("x", operator="ops")
        am.clear()
        assert len(am.all_alerts) == 0
        assert len(am.active_alerts()) == 0

    def test_satisfies_protocol(self) -> None:
        from feelies.monitoring.alerting import AlertManager

        am = InMemoryAlertManager()
        assert hasattr(am, "emit")
        assert hasattr(am, "active_alerts")
        assert hasattr(am, "acknowledge")


# ── KillSwitch ──────────────────────────────────────────────────────


class TestInMemoryKillSwitch:
    def test_starts_inactive(self) -> None:
        ks = InMemoryKillSwitch()
        assert ks.is_active is False

    def test_activate_engages(self) -> None:
        ks = InMemoryKillSwitch()
        ks.activate("drawdown_breach", activated_by="risk_engine")
        assert ks.is_active is True

    def test_reset_disengages(self) -> None:
        ks = InMemoryKillSwitch()
        ks.activate("test")
        ks.reset(operator="human", audit_token="AUD-001")
        assert ks.is_active is False

    def test_double_activate_stays_active(self) -> None:
        ks = InMemoryKillSwitch()
        ks.activate("first")
        ks.activate("second")
        assert ks.is_active is True

    def test_history_tracks_all_actions(self) -> None:
        ks = InMemoryKillSwitch()
        ks.activate("breach", activated_by="orchestrator")
        ks.reset(operator="ops", audit_token="TOK-1")
        assert len(ks.history) == 2
        assert ks.history[0].action == "activate"
        assert ks.history[0].reason == "breach"
        assert ks.history[1].action == "reset"
        assert ks.history[1].audit_token == "TOK-1"

    def test_satisfies_protocol(self) -> None:
        from feelies.monitoring.kill_switch import KillSwitch

        ks = InMemoryKillSwitch()
        assert hasattr(ks, "is_active")
        assert hasattr(ks, "activate")
        assert hasattr(ks, "reset")
