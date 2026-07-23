"""Tests for composition solver-degradation alerts.

``HorizonMetricsCollector`` raises a ``composition.solver_degraded``
WARNING when a ``SizedPositionIntent`` carries a degraded optimizer
``solver_status``, with a per-alpha state-change throttle.
"""

from __future__ import annotations

from feelies.bus.event_bus import EventBus
from feelies.core.events import Alert, SizedPositionIntent, TargetPosition
from feelies.core.identifiers import SequenceGenerator
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector


def _intent(
    solver_status: str, *, strategy_id: str = "port_a", ts_ns: int = 1_000
) -> SizedPositionIntent:
    return SizedPositionIntent(
        timestamp_ns=ts_ns,
        sequence=0,
        correlation_id="ctx:1",
        source_layer="PORTFOLIO",
        strategy_id=strategy_id,
        layer="PORTFOLIO",
        horizon_seconds=300,
        target_positions={"AAPL": TargetPosition(symbol="AAPL", target_usd=1000.0)},
        solver_status=solver_status,
    )


def _collector() -> tuple[EventBus, list[Alert]]:
    bus = EventBus()
    alerts: list[Alert] = []
    bus.subscribe(Alert, lambda a: alerts.append(a))
    collector = HorizonMetricsCollector(
        bus=bus,
        metric_sequence_generator=SequenceGenerator(),
    )
    collector.attach()
    return bus, alerts


def _solver_alerts(alerts: list[Alert]) -> list[Alert]:
    return [a for a in alerts if a.alert_name == "composition.solver_degraded"]


def test_degraded_status_raises_alert() -> None:
    bus, alerts = _collector()
    bus.publish(_intent("ECOS_FAILED_FALLBACK"))
    solver_alerts = _solver_alerts(alerts)
    assert len(solver_alerts) == 1
    assert solver_alerts[0].context["solver_status"] == "ECOS_FAILED_FALLBACK"


def test_healthy_statuses_do_not_alert() -> None:
    bus, alerts = _collector()
    for status in (
        "CLOSED_FORM",
        "optimal",
        "optimal_inaccurate",
        "ZERO_GROSS",
        "EMPTY_UNIVERSE",
        "",
    ):
        bus.publish(_intent(status))
    assert _solver_alerts(alerts) == []


def test_repeated_same_status_is_throttled() -> None:
    bus, alerts = _collector()
    for _ in range(3):
        bus.publish(_intent("ECOS_FAILED_FALLBACK"))
    assert len(_solver_alerts(alerts)) == 1


def test_rearms_after_healthy_boundary() -> None:
    bus, alerts = _collector()
    bus.publish(_intent("ECOS_FAILED_FALLBACK"))
    bus.publish(_intent("CLOSED_FORM"))  # healthy → re-arm
    bus.publish(_intent("ECOS_FAILED_FALLBACK"))
    assert len(_solver_alerts(alerts)) == 2


def test_throttle_is_per_alpha() -> None:
    bus, alerts = _collector()
    bus.publish(_intent("infeasible", strategy_id="port_a"))
    bus.publish(_intent("infeasible", strategy_id="port_b"))
    assert len(_solver_alerts(alerts)) == 2
