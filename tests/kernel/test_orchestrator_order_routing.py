"""Characterization tests for orchestrator order routing and submission."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import Alert, OrderRequest, OrderType, Side
from feelies.execution.position_manager import ExecStyle

from tests.kernel.test_orchestrator import _build_orchestrator, _make_quote


class _FixedRoutePolicy:
    def __init__(self, decision: str) -> None:
        self.decision = decision
        self.calls: list[dict[str, Any]] = []

    def decide(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.decision


@pytest.mark.parametrize(
    (
        "use_passive",
        "policy_decision",
        "exec_style",
        "forced_market",
        "moc",
        "expected_type",
    ),
    [
        (False, None, None, False, False, OrderType.MARKET),
        (True, None, None, False, False, OrderType.LIMIT),
        (True, "aggressive", None, False, False, OrderType.MARKET),
        (False, None, ExecStyle.PASSIVE, False, False, OrderType.LIMIT),
        (True, "passive", ExecStyle.PASSIVE, True, False, OrderType.MARKET),
        (True, "passive", ExecStyle.PASSIVE, False, True, OrderType.MARKET),
    ],
)
def test_order_route_precedence(
    use_passive: bool,
    policy_decision: str | None,
    exec_style: ExecStyle | None,
    forced_market: bool,
    moc: bool,
    expected_type: OrderType,
) -> None:
    orch = _build_orchestrator(SimulatedClock(start_ns=1000))
    orch._use_passive_entries = use_passive
    policy = _FixedRoutePolicy(policy_decision) if policy_decision else None
    orch._min_cost_policy = policy  # type: ignore[assignment]
    if moc:
        orch._moc_strategy_ids = frozenset({"test_strat"})
        orch._moc_bounds_configured = True

    order_type, limit_price, is_moc = orch._resolve_order_route(
        strategy_id="test_strat",
        symbol="AAPL",
        side=Side.BUY,
        quantity=100,
        quote=_make_quote(),
        is_short=False,
        is_exit_or_stop=False,
        edge_bps=5.0,
        exec_style=exec_style,
        forced_market=forced_market,
    )

    assert order_type is expected_type
    assert limit_price == (Decimal("149.50") if expected_type is OrderType.LIMIT else None)
    assert is_moc is moc
    if forced_market:
        assert policy is not None and policy.calls == []


def test_submit_exception_rejects_and_prunes_order(monkeypatch) -> None:
    clock = SimulatedClock(start_ns=1000)
    bus = EventBus()
    alerts: list[Alert] = []
    bus.subscribe(Alert, alerts.append)
    orch = _build_orchestrator(clock, bus=bus)
    order = OrderRequest(
        timestamp_ns=1000,
        correlation_id="c",
        sequence=1,
        order_id="order-1",
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=10,
    )
    orch._track_order(order.order_id, order.side, order)

    def raise_on_submit(_order: OrderRequest) -> None:
        raise RuntimeError("submit failed")

    monkeypatch.setattr(orch._backend.order_router, "submit", raise_on_submit)

    error = orch._submit_tracked_order(order)

    assert isinstance(error, RuntimeError)
    assert order.order_id not in orch._active_orders
    assert any(alert.alert_name == "order_submit_failed" for alert in alerts)
