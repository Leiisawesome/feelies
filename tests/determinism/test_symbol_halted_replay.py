"""Pin halt events and halt-gated fill suppression.

The replay enters a halt, suppresses an entry, resumes into a blackout,
suppresses another entry, then fills after the blackout. Hashes cover halt,
order, acknowledgement, and position streams.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    OrderAck,
    OrderRequest,
    PositionUpdate,
    RiskAction,
    SignalDirection,
    SymbolHalted,
    Trade,
)
from feelies.execution.backend import ExecutionBackend
from feelies.execution.backtest_router import BacktestOrderRouter
from feelies.kernel.orchestrator import Orchestrator
from feelies.portfolio.memory_position_store import MemoryPositionStore
from feelies.storage.memory_event_log import InMemoryEventLog

from tests.kernel.test_orchestrator import (
    _NoOpMetricCollector,
    _StubMarketData,
    _StubRiskEngine,
    _boot_to_backtest,
    _make_quote,
    _make_signal,
    _publish_signal_on_quote,
)

_SYMBOL = "AAPL"
_HALT_ON_CODE = 5
_HALT_OFF_CODE = 6
_BLACKOUT_NS = 1000


def _trade(ts: int, seq: int, conditions: tuple[int, ...]) -> Trade:
    return Trade(
        timestamp_ns=ts,
        correlation_id=f"{_SYMBOL}:{ts}:{seq}",
        sequence=seq,
        symbol=_SYMBOL,
        price=Decimal("150"),
        size=100,
        exchange_timestamp_ns=ts - 50,
        conditions=conditions,
    )


def _replay() -> dict[str, tuple[str, int]]:
    clock = SimulatedClock(start_ns=1000)
    bus = EventBus()
    position_store = MemoryPositionStore()
    bt_router = BacktestOrderRouter(clock=clock)
    orch = Orchestrator(
        clock=clock,
        bus=bus,
        backend=ExecutionBackend(
            market_data=_StubMarketData(), order_router=bt_router, mode="BACKTEST"
        ),
        risk_engine=_StubRiskEngine(action=RiskAction.ALLOW),
        position_store=position_store,
        event_log=InMemoryEventLog(),
        metric_collector=_NoOpMetricCollector(),
    )
    _boot_to_backtest(orch)
    orch._halt_on_codes = frozenset({_HALT_ON_CODE})
    orch._halt_off_codes = frozenset({_HALT_OFF_CODE})
    orch._halt_blackout_ns = _BLACKOUT_NS

    halts: list[SymbolHalted] = []
    orders: list[OrderRequest] = []
    acks: list[OrderAck] = []
    updates: list[PositionUpdate] = []
    bus.subscribe(SymbolHalted, halts.append)  # type: ignore[arg-type]
    bus.subscribe(OrderRequest, orders.append)  # type: ignore[arg-type]
    bus.subscribe(OrderAck, acks.append)  # type: ignore[arg-type]
    bus.subscribe(PositionUpdate, updates.append)  # type: ignore[arg-type]

    _publish_signal_on_quote(bus, _make_signal(_make_quote(), SignalDirection.LONG))

    # 1. Halt-on before any entry succeeds.
    orch._process_trade(_trade(ts=1000, seq=1, conditions=(_HALT_ON_CODE,)))

    # 2. Entry attempt while halted — suppressed (position stays flat).
    q1 = _make_quote(ts=1500, seq=2)
    bt_router.on_quote(q1)
    orch._process_tick(q1)

    # 3. Halt-off — opens the post-resume blackout window.
    orch._process_trade(_trade(ts=2000, seq=3, conditions=(_HALT_OFF_CODE,)))

    # 4. Entry attempt inside the blackout — suppressed by a different gate.
    q2 = _make_quote(ts=2500, seq=4)
    bt_router.on_quote(q2)
    orch._process_tick(q2)

    # 5. Entry attempt after the blackout clears — succeeds.
    q3 = _make_quote(ts=3500, seq=5)
    bt_router.on_quote(q3)
    orch._process_tick(q3)

    return {
        "symbol_halted": (_hash_halts(halts), len(halts)),
        "order": (_hash_orders(orders), len(orders)),
        "ack": (_hash_acks(acks), len(acks)),
        "position_update": (_hash_updates(updates), len(updates)),
    }


def _sha(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _hash_halts(halts: list[SymbolHalted]) -> str:
    return _sha(
        [
            f"{h.sequence}|{h.symbol}|{h.halted}|{h.reason}|{h.blackout_until_ns}|"
            f"{h.timestamp_ns}|{h.correlation_id}"
            for h in halts
        ]
    )


def _hash_orders(orders: list[OrderRequest]) -> str:
    return _sha(
        [
            f"{o.sequence}|{o.order_id}|{o.symbol}|{o.side.name}|{o.quantity}|"
            f"{o.timestamp_ns}|{o.correlation_id}"
            for o in orders
        ]
    )


def _hash_acks(acks: list[OrderAck]) -> str:
    return _sha(
        [
            f"{a.sequence}|{a.order_id}|{a.status.name}|{a.filled_quantity}|"
            f"{a.fill_price}|{a.timestamp_ns}"
            for a in acks
        ]
    )


def _hash_updates(updates: list[PositionUpdate]) -> str:
    return _sha([f"{u.sequence}|{u.symbol}|{u.quantity}|{u.timestamp_ns}" for u in updates])


def test_two_replays_produce_identical_halt_streams() -> None:
    assert _replay() == _replay()


# Locked baseline.  Re-baseline only with an intentional change to the halt
# gate / blackout semantics, justified in the commit.
EXPECTED_SYMBOL_HALTED_HASH = "a7b5c52139086e62019a282a6e3ec9352c677917dda2eaf2d13c7000af06c564"
EXPECTED_SYMBOL_HALTED_COUNT = 2
EXPECTED_HALT_ORDER_HASH = "f791d994712762590eda4281830a0b4ce1af8b20cd295e2defcbbcd34e4a11e7"
EXPECTED_HALT_ORDER_COUNT = 1
EXPECTED_HALT_ACK_HASH = "ca5015fcf416e6698996ad77916c86e810b501e12e8e5605c8fdac6220496b09"
EXPECTED_HALT_ACK_COUNT = 2
EXPECTED_HALT_POSITION_UPDATE_HASH = (
    "ad9e112d08209b3866f1002e341c7bf755f7e778edd59957cf0ba4daa38dff7e"
)
EXPECTED_HALT_POSITION_UPDATE_COUNT = 1

EXPECTED_HALT_STREAMS: dict[str, tuple[str, int]] = {
    "symbol_halted": (EXPECTED_SYMBOL_HALTED_HASH, EXPECTED_SYMBOL_HALTED_COUNT),
    "order": (EXPECTED_HALT_ORDER_HASH, EXPECTED_HALT_ORDER_COUNT),
    "ack": (EXPECTED_HALT_ACK_HASH, EXPECTED_HALT_ACK_COUNT),
    "position_update": (
        EXPECTED_HALT_POSITION_UPDATE_HASH,
        EXPECTED_HALT_POSITION_UPDATE_COUNT,
    ),
}


def test_halt_streams_match_locked_baseline() -> None:
    actual = _replay()
    assert actual == EXPECTED_HALT_STREAMS, (
        "Halt-gate replay stream drift!\n"
        f"  Expected: {EXPECTED_HALT_STREAMS}\n"
        f"  Actual:   {actual}\n"
        "If intentional, update EXPECTED_HALT_STREAMS in the same commit and "
        "justify in the commit message (re-baseline workflow)."
    )


def test_scenario_discriminates_halt_and_blackout_suppression() -> None:
    """No-false-empty / no-false-pass guard.

    Confirms the scenario actually exercises both suppression gates
    separately (not just "nothing ever fills") and that exactly one entry —
    the post-blackout one — succeeds.
    """
    actual = _replay()
    assert actual["symbol_halted"][1] == 2, "expected exactly one halt-on and one resume marker"
    assert actual["order"][1] == 1, "expected exactly one order — the post-blackout entry"
    assert actual["position_update"][1] == 1, "expected exactly one position reconciliation"
