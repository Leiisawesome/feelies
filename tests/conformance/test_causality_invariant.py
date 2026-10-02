"""I1, I2, and I3 over a bus tap. Red until the stamp fixes land."""

from __future__ import annotations

import gc
from pathlib import Path

import pytest

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import build_platform
from feelies.core.events import Event, NBBOQuote, OrderAck, OrderAckStatus, Trade
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.position_engine.scenarios import (
    T0,
    _FIXTURE,
    _seams,
    _sensors,
    synthetic_alpha_spec,
)
from tests.position_engine.tapes import make_tape

_MARKET = frozenset(
    {
        "NBBOQuote",
        "Trade",
        "SymbolHalted",
        "Signal",
        "SafetyStateChange",
        "SensorReading",
        "HorizonTick",
        "HorizonFeatureSnapshot",
        "CrossSectionalContext",
        "SizedPositionIntent",
        "MarkRailUpdate",
    }
)
_PENDING = frozenset({"GateDecision", "DeRiskRequirement", "PositionSnapshot"})
_REFERENCE_ENGINE = "tests.position_engine.reference.engine.PositionEngine"
_REFERENCE_RAIL = "tests.position_engine.reference.rail.ReferenceRail"


def _label(event: Event) -> str:
    name = type(event).__name__
    if isinstance(event, OrderAck):
        return f"OrderAck/{event.status.name}"
    return name


def _tap(orchestrator: object) -> list[tuple[Event, int, int | None]]:
    rows: list[tuple[Event, int, int | None]] = []
    trigger: list[int | None] = [None]
    clock = orchestrator._clock  # type: ignore[attr-defined]
    bus = orchestrator._bus  # type: ignore[attr-defined]

    def publish(event: Event) -> None:
        rows.append((event, clock.now_ns(), trigger[0]))

    bus.subscribe_all(publish)

    inner_tick = orchestrator._process_tick_inner  # type: ignore[attr-defined]

    def tick(quote: NBBOQuote) -> None:
        trigger[0] = quote.exchange_timestamp_ns
        inner_tick(quote)

    orchestrator._process_tick_inner = tick  # type: ignore[method-assign]

    inner_trade = orchestrator._process_trade  # type: ignore[attr-defined]

    def on_trade(trade: Trade) -> None:
        trigger[0] = trade.exchange_timestamp_ns
        inner_trade(trade)

    orchestrator._process_trade = on_trade  # type: ignore[method-assign]
    return rows


def _violations(
    rows: list[tuple[Event, int, int | None]],
) -> tuple[list[str], list[str], list[str]]:
    i1: list[str] = []
    i2: list[str] = []
    i3: list[str] = []
    for event, clock_ns, trigger_ns in rows:
        name = type(event).__name__
        label = _label(event)
        if event.timestamp_ns > clock_ns:
            i1.append(label)
        if name in _MARKET:
            if trigger_ns is None or event.timestamp_ns != trigger_ns:
                i3.append(label)
        elif event.timestamp_ns != clock_ns:
            i2.append(label)
    return i1, i2, i3


def _run_synthetic(tape: list[NBBOQuote]) -> list[tuple[Event, int, int | None]]:
    log = InMemoryEventLog()
    log.append_batch(list(tape))
    config = PlatformConfig(
        symbols=frozenset({"SYN"}),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_FIXTURE],
        sensor_specs=_sensors(),  # type: ignore[arg-type]
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=T0,
        risk_max_gross_exposure_pct=80.0,
    )
    original_load = AlphaLoader.load
    spec = synthetic_alpha_spec(None)

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
        with _seams(None, None, True):
            orchestrator, resolved = build_platform(config, event_log=log)
            rows = _tap(orchestrator)
            orchestrator.boot(resolved)
            gc.disable()
            try:
                orchestrator.run_backtest()
            finally:
                gc.enable()
    finally:
        AlphaLoader.load = original_load  # type: ignore[method-assign]
    return rows


def test_synthetic_seed11_i1_i2_i3() -> None:
    """C_SYN seed 11, n=36000. I1, I2, and I3 hold. Stays under 20s."""
    tape = make_tape(seed=11, n=36000, symbol="SYN", start_ns=T0, size=1000)
    rows = _run_synthetic(tape)
    acknowledged = [
        event
        for event, _clock, _trigger in rows
        if isinstance(event, OrderAck) and event.status == OrderAckStatus.ACKNOWLEDGED
    ]
    assert acknowledged, "the tape must publish an ACKNOWLEDGED ack"
    late = [
        event.timestamp_ns - clock
        for event, clock, _trigger in rows
        if isinstance(event, OrderAck)
        and event.status == OrderAckStatus.ACKNOWLEDGED
        and event.timestamp_ns != clock
    ]
    assert not late, late
    i1, i2, i3 = _violations(rows)
    assert not i1, sorted(set(i1))
    assert not i2, sorted(set(i2))
    assert not i3, sorted(set(i3))


@pytest.mark.battery_real
def test_reference_app_i2_only_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """R-FIX. I1 and I3 hold. I2 holds except PENDING, and PENDING still fails I2."""
    from tests.position_engine.scenarios import run_real

    monkeypatch.setenv("FEELIES_ENGINE", _REFERENCE_ENGINE)
    monkeypatch.setenv("FEELIES_RAIL", _REFERENCE_RAIL)
    # The harness builds inside run_real. Tap by wrapping build_platform.
    import tests.position_engine.scenarios as scenarios

    box: dict[str, list[tuple[Event, int, int | None]]] = {}
    original = scenarios.build_platform

    def wrapped(*args: object, **kwargs: object) -> object:
        orchestrator, resolved = original(*args, **kwargs)  # type: ignore[misc]
        box["rows"] = _tap(orchestrator)
        return orchestrator, resolved

    monkeypatch.setattr(scenarios, "build_platform", wrapped)
    run_real()
    rows = box["rows"]
    i1, i2, i3 = _violations(rows)
    pending_seen = {
        type(event).__name__
        for event, _clock, _trigger in rows
        if type(event).__name__ in _PENDING
    }
    pending_equal = [
        type(event).__name__
        for event, clock, _trigger in rows
        if type(event).__name__ in _PENDING and event.timestamp_ns == clock
    ]
    assert set(i2) <= _PENDING and i2, sorted(set(i2))
    assert not i1, sorted(set(i1))
    assert not i3, sorted(set(i3))
    assert pending_seen, "PENDING types must be on the reference session"
    assert not pending_equal, sorted(set(pending_equal))


_PUBLICATION_NS = 50_000_000_000
_RAIL_NS = 3_000


def _stamped_at_publication(kind: str) -> None:
    """One producer: the published stamp is the clock, and the rail time is not."""
    from feelies.core.clock import SimulatedClock
    from feelies.core.events import DeRiskRequirement, GateDecision, PositionSnapshot
    from tests.position_engine.test_reference_engine import (
        _engine,
        _of,
        _orient,
        _policy,
        _rail,
        _slice,
    )

    types = {
        "GateDecision": GateDecision,
        "DeRiskRequirement": DeRiskRequirement,
        "PositionSnapshot": PositionSnapshot,
    }
    clock = SimulatedClock(_PUBLICATION_NS)
    bus, engine, log = _engine(_policy(t_ns=1))
    engine._clock = clock
    bus.publish(_rail(1, 1_000))
    bus.publish(_slice(2, 1_000, order_id="entry", price="100.01", fill_quantity=1, quantity=1))
    bus.publish(
        _rail(
            4,
            _RAIL_NS,
            _orient(valuation=9_000, worst=9_000, forced=9_000, dwelled=9_000),
        )
    )
    assert _RAIL_NS != clock.now_ns()
    published = _of(log, types[kind])
    assert published, kind
    assert all(event.timestamp_ns == clock.now_ns() for event in published), kind


def test_gate_decision_stamp_equals_publication_clock() -> None:
    """GateDecision is action-class: timestamp_ns is the clock at publication."""
    _stamped_at_publication("GateDecision")


def test_derisk_requirement_stamp_equals_publication_clock() -> None:
    """DeRiskRequirement is action-class: timestamp_ns is the clock at publication."""
    _stamped_at_publication("DeRiskRequirement")


def test_position_snapshot_stamp_equals_publication_clock() -> None:
    """PositionSnapshot is action-class: timestamp_ns is the clock at publication."""
    _stamped_at_publication("PositionSnapshot")


def test_pending_allowlist_stays_empty() -> None:
    """PENDING is empty. Adding an entry fails this test."""
    assert _PENDING == frozenset()
