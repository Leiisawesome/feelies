"""POSITION requirements take the engine-8 copy path (contracts.md §5).

F3 keeps the existing RISK behaviour green:
tests/kernel/test_orchestrator_hazard_exit_routing.py,
tests/kernel/test_orchestrator_exit_composer_routing.py,
tests/execution/test_stop_slippage.py,
tests/kernel/test_orchestrator.py::TestForcedExitPanicReason.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import build_platform
from feelies.core.events import (
    DeRiskRequirement,
    NBBOQuote,
    OrderAck,
    OrderAckStatus,
    OrderRequest,
    OrderType,
    RiskAction,
    RiskVerdict,
    Side,
)
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.orchestrator import Orchestrator
from feelies.kernel.order_states import _TERMINAL_ORDER_STATES
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.position_engine.scenarios import T0, _FIXTURE, _sensors, synthetic_alpha_spec
from tests.position_engine.tapes import make_tape

_STRAT = "sig_position_fixture_v1"
_OTHER = "other_slice_v1"
_SYMBOL = "SYN"
_OTHER_QTY = 40
_REASON = "ADVERSE_EXCURSION"


@dataclass
class _Run:
    orders: list[OrderRequest]
    verdicts: list[RiskVerdict]
    acks: list[OrderAck]
    submits: list[OrderRequest]
    slice_qty: int
    decision_quote: NBBOQuote | None
    in_flight_at_second: bool
    orchestrator: Orchestrator
    tape: list[NBBOQuote]


def _requirement(slice_qty: int, *, order_id: str, sequence: int, ts: int) -> DeRiskRequirement:
    return DeRiskRequirement(
        timestamp_ns=ts,
        correlation_id=f"p62a-{order_id}",
        sequence=sequence,
        source_layer="POSITION",
        order_id=order_id,
        symbol=_SYMBOL,
        side=Side.SELL if slice_qty > 0 else Side.BUY,
        quantity=abs(slice_qty),
        strategy_id=_STRAT,
        reason=_REASON,
    )


def _run(*, second: bool) -> _Run:
    tape = make_tape(seed=11, n=1800, symbol=_SYMBOL, start_ns=T0, size=1000)
    log = InMemoryEventLog()
    log.append_batch(tape)
    config = PlatformConfig(
        symbols=frozenset({_SYMBOL}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_FIXTURE],
        sensor_specs=_sensors(),  # type: ignore[arg-type]
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=T0,
        risk_max_gross_exposure_pct=80.0,
    )
    spec = synthetic_alpha_spec(None)
    original_load = AlphaLoader.load

    def _load(
        self: AlphaLoader,
        path: object,
        param_overrides: dict[str, object] | None = None,
    ) -> object:
        if Path(str(path)) == _FIXTURE:
            return self.load_from_dict(spec, source=str(_FIXTURE))
        return original_load(self, path, param_overrides)  # type: ignore[arg-type]

    AlphaLoader.load = _load  # type: ignore[method-assign]
    try:
        orchestrator, resolved = build_platform(config, event_log=log)
        orders: list[OrderRequest] = []
        verdicts: list[RiskVerdict] = []
        acks: list[OrderAck] = []
        submits: list[OrderRequest] = []
        held: dict[str, object] = {
            "done": False,
            "slice_qty": 0,
            "quote": None,
            "in_flight": False,
        }
        orchestrator._bus.subscribe(OrderRequest, orders.append)
        orchestrator._bus.subscribe(RiskVerdict, verdicts.append)
        orchestrator._bus.subscribe(OrderAck, acks.append)
        router = orchestrator._backend.order_router
        original_submit = router.submit

        def _submit(request: OrderRequest, triggering_quote: NBBOQuote | None = None) -> None:
            submits.append(request)
            original_submit(request, triggering_quote=triggering_quote)

        router.submit = _submit  # type: ignore[method-assign]
        original_tick = orchestrator._process_tick

        def _tick(quote: NBBOQuote) -> None:
            original_tick(quote)
            if held["done"]:
                return
            store = orchestrator._strategy_positions
            assert store is not None
            qty = store.get(_STRAT, _SYMBOL).quantity
            if qty == 0:
                return
            store.update(_OTHER, _SYMBOL, _OTHER_QTY, quote.bid, timestamp_ns=quote.timestamp_ns)
            orchestrator._positions.update(
                _SYMBOL, _OTHER_QTY, quote.bid, timestamp_ns=quote.timestamp_ns
            )
            held["slice_qty"] = qty
            held["quote"] = quote
            orchestrator._bus.publish(
                _requirement(qty, order_id="pos-exit-1", sequence=9001, ts=quote.timestamp_ns)
            )
            if second:
                entry = orchestrator._active_orders.get("pos-exit-1")
                held["in_flight"] = (
                    entry is not None and entry[0].state not in _TERMINAL_ORDER_STATES
                )
                orchestrator._bus.publish(
                    _requirement(qty, order_id="pos-exit-2", sequence=9002, ts=quote.timestamp_ns)
                )
            held["done"] = True

        orchestrator._process_tick = _tick  # type: ignore[method-assign]
        orchestrator.boot(resolved)
        orchestrator.run_backtest()
    finally:
        AlphaLoader.load = original_load  # type: ignore[method-assign]
    quote = held["quote"]
    return _Run(
        orders=orders,
        verdicts=verdicts,
        acks=acks,
        submits=submits,
        slice_qty=int(held["slice_qty"]),
        decision_quote=quote if isinstance(quote, NBBOQuote) else None,
        in_flight_at_second=bool(held["in_flight"]),
        orchestrator=orchestrator,
        tape=tape,
    )


def _position_orders(run: _Run) -> list[OrderRequest]:
    return [order for order in run.orders if order.reason == _REASON]


def _position_submits(run: _Run) -> list[OrderRequest]:
    return [order for order in run.submits if order.reason == _REASON]


def test_position_requirement_exits_the_full_slice_at_stop_slippage() -> None:
    """F1. One POSITION requirement becomes one MARKET exit of the open slice.

    Original intent: the exit sells the whole slice and pays stop slippage
    on that fill. R2-1 prices the fill on the quote prevailing at arrival,
    bid 99.78. The old pin was the flush quote, ``later[0].bid`` = 99.79.
    """
    run = _run(second=False)
    exits = _position_orders(run)
    assert len(exits) == 1
    order = exits[0]
    assert order.order_type is OrderType.MARKET
    assert order.source_layer == "POSITION"
    assert order.strategy_id == _STRAT
    assert order.symbol == _SYMBOL
    assert order.side is Side.SELL
    assert order.quantity == run.slice_qty
    assert len(_position_submits(run)) == 1
    verdicts = [v for v in run.verdicts if v.correlation_id == order.correlation_id]
    assert verdicts and verdicts[-1].action is RiskAction.ALLOW
    fills = [
        ack
        for ack in run.acks
        if ack.order_id == order.order_id and ack.status is OrderAckStatus.FILLED
    ]
    assert len(fills) == 1
    assert fills[0].filled_quantity == run.slice_qty
    assert run.decision_quote is not None
    router = run.orchestrator._backend.order_router
    half = (run.decision_quote.ask - run.decision_quote.bid) / Decimal("2")
    panic_half = half * (router._stop_slippage_half_spreads - Decimal("1"))
    panic = router._cost_model.compute(
        symbol=_SYMBOL,
        side=order.side,
        quantity=order.quantity,
        fill_price=fills[0].fill_price,
        half_spread=panic_half,
    )
    plain = router._cost_model.compute(
        symbol=_SYMBOL,
        side=order.side,
        quantity=order.quantity,
        fill_price=fills[0].fill_price,
        half_spread=Decimal("0"),
    )
    assert fills[0].fees == panic.total_fees
    assert fills[0].fees > plain.total_fees
    later = [
        quote
        for quote in run.tape
        if quote.exchange_timestamp_ns > run.decision_quote.exchange_timestamp_ns
    ]
    assert later
    assert fills[0].fill_price == Decimal("99.78")
    store = run.orchestrator._strategy_positions
    assert store is not None
    assert store.get(_STRAT, _SYMBOL).quantity == 0


def test_other_slice_is_untouched() -> None:
    """F3. The requirement flattens its own slice and leaves the other strategy."""
    run = _run(second=False)
    store = run.orchestrator._strategy_positions
    assert store is not None
    assert store.get(_STRAT, _SYMBOL).quantity == 0
    assert store.get(_OTHER, _SYMBOL).quantity == _OTHER_QTY
    assert run.orchestrator._positions.get(_SYMBOL).quantity == _OTHER_QTY


def test_second_requirement_submits_no_second_order_while_exit_works() -> None:
    """F4. FINDING: escalation record unspecified.

    contracts.md §2 says a higher-ranked path's escalation is a no-op that is
    recorded, and names no event or field. This asserts no second submission.
    """
    run = _run(second=True)
    submits = _position_submits(run)
    assert len(submits) == 1
    assert submits[0].order_id == "pos-exit-1"
    assert run.in_flight_at_second
    assert "pos-exit-2" not in {order.order_id for order in submits}
    store = run.orchestrator._strategy_positions
    assert store is not None
    assert store.get(_STRAT, _SYMBOL).quantity == 0
