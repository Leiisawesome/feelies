"""Paper-RTH safety-path E2E tests (Tier 3).

Exercises degrade-on-data-gap, RISK_LOCKDOWN, and G12 cost alerts
using the in-process ``paper_session`` harness where possible.
"""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from feelies.core.events import (
    Alert,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
    Signal,
)
from feelies.kernel.macro import MacroState
from feelies.execution.order_state import OrderState

from tests.kernel.test_orchestrator import (
    _make_signal,
    _publish_signal_on_quote,
)
from tests.paper.conftest import require_ib_gateway, require_massive_api_key, require_rth_window

pytestmark = [
    pytest.mark.functional,
    pytest.mark.paper_rth,
]


@pytest.fixture(scope="module", autouse=True)
def _paper_rth_module_guards() -> None:
    require_rth_window()
    require_ib_gateway()
    require_massive_api_key()


def test_data_gap_degrades_macro(paper_session) -> None:
    orchestrator, _bus, _run_dir, thread = paper_session
    assert orchestrator.macro_state == MacroState.PAPER_TRADING_MODE
    normalizer = orchestrator._normalizer
    assert normalizer is not None

    normalizer.notify_feed_interrupted(["SPY"])

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if orchestrator.macro_state == MacroState.DEGRADED:
            break
        time.sleep(0.5)

    orchestrator.halt()
    thread.join(timeout=30.0)
    assert orchestrator.macro_state in {
        MacroState.DEGRADED,
        MacroState.READY,
        MacroState.SHUTDOWN,
    }


def test_risk_lockdown_on_force_flatten(paper_session) -> None:
    orchestrator, bus, _run_dir, thread = paper_session
    assert orchestrator.macro_state == MacroState.PAPER_TRADING_MODE

    risk_engine = orchestrator._risk_engine

    def _force_flatten(signal: object, positions: object) -> RiskVerdict:
        from feelies.core.events import Signal

        assert isinstance(signal, Signal)
        return RiskVerdict(
            timestamp_ns=signal.timestamp_ns,
            correlation_id=signal.correlation_id,
            sequence=signal.sequence,
            symbol=signal.symbol,
            action=RiskAction.FORCE_FLATTEN,
            reason="paper_e2e_force_flatten",
        )

    risk_engine.check_signal = _force_flatten  # type: ignore[method-assign]

    from decimal import Decimal

    from feelies.core.events import NBBOQuote

    quote = NBBOQuote(
        timestamp_ns=1_000,
        correlation_id="SPY:1000:1",
        sequence=1,
        symbol="SPY",
        bid=Decimal("500.00"),
        ask=Decimal("500.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=900,
    )
    signal = _make_signal(quote)
    signal = Signal(
        timestamp_ns=signal.timestamp_ns,
        correlation_id=signal.correlation_id,
        sequence=signal.sequence,
        symbol=signal.symbol,
        strategy_id="paper_smoke_v1",
        direction=signal.direction,
        strength=signal.strength,
        edge_estimate_bps=signal.edge_estimate_bps,
    )
    _publish_signal_on_quote(bus, signal)
    orchestrator._process_tick(quote)

    orchestrator.halt()
    thread.join(timeout=30.0)
    assert orchestrator.macro_state in {
        MacroState.RISK_LOCKDOWN,
        MacroState.READY,
        MacroState.SHUTDOWN,
    }


def test_g12_cost_exceeds_disclosure_alert(paper_session) -> None:
    orchestrator, bus, _run_dir, thread = paper_session
    alerts: list[Alert] = []
    bus.subscribe(Alert, alerts.append)

    from feelies.core.clock import WallClock

    clock = WallClock()
    order_id = f"g12-{clock.now_ns()}"
    req = OrderRequest(
        timestamp_ns=clock.now_ns(),
        correlation_id=f"paper-e2e:{order_id}",
        sequence=1,
        order_id=order_id,
        symbol="SPY",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=Decimal("500.0"),
        strategy_id="paper_smoke_v1",
        g12_disclosed_cost_total_bps=2.5,
    )
    orchestrator._track_order(order_id, Side.BUY, req)
    orchestrator._transition_order(
        order_id,
        OrderState.SUBMITTED,
        "paper_e2e_g12",
        correlation_id=req.correlation_id,
    )

    ack = OrderAck(
        timestamp_ns=clock.now_ns(),
        correlation_id=req.correlation_id,
        sequence=2,
        order_id=order_id,
        symbol="SPY",
        status=OrderAckStatus.FILLED,
        filled_quantity=1,
        fill_price=Decimal("500.0"),
        fees=Decimal("10.0"),
        cost_bps=Decimal("50.0"),
        request_sequence=req.sequence,
    )
    orchestrator._reconcile_fills([ack], req.correlation_id)

    orchestrator.halt()
    thread.join(timeout=30.0)
    assert any(a.alert_name == "g12_realized_cost_exceeds_disclosure_stress" for a in alerts)
