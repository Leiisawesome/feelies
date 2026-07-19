"""Paper-RTH end-to-end integration tests (Tier 3).

Requires US RTH, IB Gateway paper @ 4002, and MASSIVE_API_KEY.
"""

from __future__ import annotations

import os
import time

import pytest

from feelies.kernel.macro import MacroState

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


def test_cold_start_smoke(paper_session) -> None:
    orchestrator, _bus, _run_dir, thread = paper_session
    assert orchestrator.macro_state == MacroState.PAPER_TRADING_MODE
    orchestrator.halt()
    thread.join(timeout=30.0)
    assert not thread.is_alive()


@pytest.mark.slow
def test_quote_sensor_warmup(paper_session) -> None:
    orchestrator, bus, _run_dir, thread = paper_session
    from feelies.core.events import HorizonFeatureSnapshot, SensorReading

    readings: list[SensorReading] = []
    snapshots: list[HorizonFeatureSnapshot] = []
    bus.subscribe(SensorReading, readings.append)
    bus.subscribe(HorizonFeatureSnapshot, snapshots.append)

    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        if readings:
            break
        if snapshots and any(
            s.warm and s.symbol == "SPY"
            for s in snapshots
            if "realized_vol_30s" in s.values or "micro_price" in s.values
        ):
            break
        time.sleep(1.0)

    orchestrator.halt()
    thread.join(timeout=130.0)
    if not readings and not snapshots:
        pytest.skip(
            "No live Massive quote stream during session "
            "(market may be closed despite PAPER_RTH_FORCE)",
        )
    assert readings, "expected SensorReading events during warm-up window"


@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("PAPER_E2E_SIGNAL_PATH", "").strip() != "1",
    reason="Set PAPER_E2E_SIGNAL_PATH=1 for 10-min signal-path test",
)
def test_signal_path(paper_session) -> None:
    orchestrator, bus, _run_dir, thread = paper_session
    from feelies.core.events import OrderAck, OrderRequest as OR, Signal

    signals: list[Signal] = []
    orders: list[OR] = []
    acks: list[OrderAck] = []
    bus.subscribe(Signal, signals.append)
    bus.subscribe(OR, orders.append)
    bus.subscribe(OrderAck, acks.append)

    deadline = time.monotonic() + 600.0
    while time.monotonic() < deadline:
        if signals and orders:
            break
        time.sleep(5.0)

    orchestrator.halt()
    thread.join(timeout=620.0)
    assert signals, "expected at least one Signal during signal-path window"


def test_shutdown_in_flight(paper_session) -> None:
    from decimal import Decimal

    from feelies.core.events import OrderAck, OrderRequest, OrderType, Side
    from feelies.core.clock import WallClock

    orchestrator, bus, _run_dir, thread = paper_session
    assert orchestrator.macro_state == MacroState.PAPER_TRADING_MODE

    clock = WallClock()
    order_id = f"shutdown-in-flight-{clock.now_ns()}"
    req = OrderRequest(
        timestamp_ns=clock.now_ns(),
        correlation_id=f"paper-e2e:{order_id}",
        sequence=1,
        order_id=order_id,
        symbol="SPY",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=1,
        limit_price=Decimal("1.00"),
        strategy_id="paper_e2e_shutdown",
    )
    acks: list[OrderAck] = []
    bus.subscribe(OrderAck, acks.append)
    bus.publish(req)

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if any(a.order_id == order_id for a in acks):
            break
        time.sleep(0.2)

    orchestrator.halt()
    thread.join(timeout=30.0)
    assert not thread.is_alive()
    assert orchestrator.macro_state in {MacroState.READY, MacroState.SHUTDOWN}
