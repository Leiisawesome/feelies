"""Boundary content is the state at the boundary, not at the crossing event.

A boundary is emitted once, in order, from the horizon-check step. Its
window is complete as of the boundary time even when a later event is what
crosses it. Held-signal expiry reads that boundary time. Window statistics
use one reduction, so a window that still holds a later sample matches the
filtered window bit for bit.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from feelies.alpha.loader import AlphaLoader
from feelies.bootstrap import build_platform
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    HorizonTick,
    NBBOQuote,
    RiskAction,
    RiskVerdict,
    SensorReading,
    Signal,
    SignalDirection,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.storage.memory_event_log import InMemoryEventLog
from tests.conformance.test_own_quote_release import _BASE_NS, _orchestrator, _quote, _tick
from tests.position_engine.scenarios import T0, _FIXTURE, _sensors
from tests.position_engine.tapes import make_tape

_NS = 1_000_000_000
_OPEN = 1_000 * _NS


def _market(symbol: str, ts: int, seq: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{symbol}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("20.00"),
        ask=Decimal("20.01"),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def _reading(symbol: str, ts: int, seq: int, value: float) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts,
        correlation_id=f"r:{symbol}:{seq}",
        sequence=seq,
        source_layer="SENSORS",
        symbol=symbol,
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        value=value,
        warm=True,
    )


def _scheduler(symbols: frozenset[str]) -> HorizonScheduler:
    return HorizonScheduler(
        horizons=frozenset({30}),
        session_id="P23G",
        symbols=symbols,
        session_open_ns=_OPEN,
        sequence_generator=SequenceGenerator(),
    )


def _arm_and_feed(
    bus: EventBus,
    store: Any,
    sched: HorizonScheduler,
    symbol: str,
    ts: int,
    seq: int,
    value: float,
) -> None:
    keys = sched.claim_capture_keys(symbol, ts)
    if keys:
        store.begin_event(symbol, keys, {})
    try:
        bus.publish(_reading(symbol, ts, seq, value))
        for tick in sched.on_event(_market(symbol, ts, seq)):
            bus.publish(tick)
    finally:
        store.end_event()


def _aggregator(symbols: frozenset[str], features: list[Any], store: Any) -> tuple[EventBus, list]:
    bus = EventBus()
    snaps: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, snaps.append)
    agg = HorizonAggregator(
        bus=bus,
        symbols=symbols,
        sensor_buffer_seconds=120,
        sequence_generator=SequenceGenerator(),
        horizon_features=features,
        boundary_state=store,
    )
    agg.attach()
    return bus, snaps


def test_window_for_boundary_t_complete_regardless_of_later_events() -> None:
    """A boundary's window keeps every sample at or before T.

    The event that finally crosses T is later than T. Evicting against that
    later timestamp would drop samples that still belong to T.
    """
    from feelies.core.events import BoundaryStateStore

    symbols = frozenset({"AAPL"})
    feature = HorizonWindowedFeature(
        "ofi_ewma",
        30,
        reducer="mean",
        feature_id="m",
        min_samples=1,
    )
    store = BoundaryStateStore()
    bus, snaps = _aggregator(symbols, [feature], store)
    sched = _scheduler(symbols)
    _arm_and_feed(bus, store, sched, "AAPL", _OPEN + 5 * _NS, 1, 1.0)
    _arm_and_feed(bus, store, sched, "AAPL", _OPEN + 10 * _NS, 2, 2.0)
    _arm_and_feed(bus, store, sched, "AAPL", _OPEN + 15 * _NS, 3, 3.0)
    _arm_and_feed(bus, store, sched, "AAPL", _OPEN + 50 * _NS, 4, 99.0)
    boundary = [snap for snap in snaps if snap.boundary_index == 1]
    assert len(boundary) == 1
    assert boundary[0].values["m"] == 2.0


def test_catchup_emits_every_skipped_boundary_in_order() -> None:
    sched = _scheduler(frozenset({"AAPL"}))
    trigger = _OPEN + 95 * _NS
    ticks = [
        tick for tick in sched.on_event(_market("AAPL", trigger, 1)) if tick.scope == "SYMBOL"
    ]
    assert [tick.boundary_index for tick in ticks] == [0, 1, 2, 3]
    for tick in ticks:
        assert tick.boundary_ts_ns == _OPEN + tick.boundary_index * 30 * _NS
        assert tick.timestamp_ns == trigger
        assert tick.boundary_ts_ns < tick.timestamp_ns


def test_held_signal_expiry_anchored_on_boundary_time() -> None:
    """Age is measured from the boundary, not from the late trigger stamp.

    The trigger is 20 s after the boundary and the releasing quote is 45 s
    after the boundary. A 30 s horizon still contains the trigger and does
    not contain the boundary.
    """
    orch, orders, _sink = _orchestrator()
    boundary = _BASE_NS
    _tick(orch, _quote("AAA", boundary, 1, "20.00"))
    held = Signal(
        timestamp_ns=boundary + 20 * _NS,
        boundary_ts_ns=boundary,
        correlation_id="sig:AAA:boundary",
        sequence=90_001,
        symbol="AAA",
        strategy_id="own_quote_alpha",
        direction=SignalDirection.LONG,
        strength=0.8,
        edge_estimate_bps=5.0,
        layer="SIGNAL",
        horizon_seconds=30,
    )
    orch._bus.publish(held)
    assert held.sequence in orch._carryover_signal_sequences
    _tick(orch, _quote("AAA", boundary + 45 * _NS, 2, "21.00"))
    assert orders == []
    assert all(item.sequence != held.sequence for item in orch._signal_buffer)


def test_tie_membership_event_exactly_at_boundary() -> None:
    """An event stamped on the boundary belongs to that boundary."""
    sched = _scheduler(frozenset({"AAPL"}))
    ts = _OPEN + 30 * _NS
    ticks = [tick for tick in sched.on_event(_market("AAPL", ts, 1)) if tick.scope == "SYMBOL"]
    exact = [tick for tick in ticks if tick.boundary_index == 1]
    assert len(exact) == 1
    assert exact[0].boundary_ts_ns == ts
    assert exact[0].timestamp_ns == ts

    feature = HorizonWindowedFeature(
        "ofi_ewma",
        30,
        reducer="last",
        feature_id="last",
        min_samples=1,
    )
    state = feature.initial_state()
    feature.observe(_reading("AAPL", ts, 1, 7.0), state, {})
    tick = HorizonTick(
        timestamp_ns=ts,
        correlation_id="tie",
        sequence=1,
        source_layer="SCHEDULER",
        horizon_seconds=30,
        boundary_index=1,
        boundary_ts_ns=ts,
        boundary_timestamp_ns=ts,
        session_id="P23G",
        scope="SYMBOL",
        symbol="AAPL",
    )
    value, warm, _stale = feature.finalize(tick, state, {})
    assert warm is True
    assert value == 7.0


def test_boundary_0_uses_pre_event_state() -> None:
    """The first event after boundary 0 does not enter that boundary."""
    from feelies.core.events import BoundaryStateStore

    symbols = frozenset({"AAPL"})
    feature = SensorPassthroughFeature("ofi_ewma", 30)
    store = BoundaryStateStore()
    bus, snaps = _aggregator(symbols, [feature], store)
    sched = _scheduler(symbols)
    _arm_and_feed(bus, store, sched, "AAPL", _OPEN + 5 * _NS, 1, 42.0)
    boundary = [snap for snap in snaps if snap.boundary_index == 0]
    assert len(boundary) == 1
    assert boundary[0].warm.get("ofi_ewma") is not True
    assert "ofi_ewma" not in boundary[0].values


def test_finalize_bit_identical_across_paths() -> None:
    """One reduction: a later sample does not change the bits at this as-of."""
    feature = HorizonWindowedFeature(
        "ofi_ewma",
        30,
        reducer="mean",
        feature_id="m",
        min_samples=1,
    )
    samples = [(0, 1e16), (_NS, 1.0), (2 * _NS, -1e16), (3 * _NS, 3.0)]
    plain = feature.initial_state()
    for ts, value in samples:
        feature.observe(_reading("AAPL", ts, ts, value), plain, {})
    asof = samples[-1][0]
    tick = HorizonTick(
        timestamp_ns=asof,
        correlation_id="bits",
        sequence=1,
        source_layer="SCHEDULER",
        horizon_seconds=30,
        boundary_index=1,
        boundary_ts_ns=asof,
        boundary_timestamp_ns=asof,
        session_id="P23G",
        scope="SYMBOL",
        symbol="AAPL",
    )
    held = copy.deepcopy(plain)
    held["win"].append((asof + 1, 0.0))
    without_later, warm_a, _ = feature.finalize(tick, plain, {})
    with_later, warm_b, _ = feature.finalize(tick, held, {})
    assert warm_a and warm_b
    assert without_later == with_later


def test_boundary_content_identical_solo_and_two_symbol() -> None:
    """BBB's boundary value does not depend on AAA crossing that boundary first."""
    from feelies.core.events import BoundaryStateStore

    feature = HorizonWindowedFeature(
        "ofi_ewma",
        30,
        reducer="mean",
        feature_id="m",
        min_samples=1,
    )

    def _run(symbols: frozenset[str], events: list[tuple[str, int, float]]) -> float:
        store = BoundaryStateStore()
        bus, snaps = _aggregator(symbols, [feature], store)
        sched = _scheduler(symbols)
        for seq, (symbol, ts, value) in enumerate(events, start=1):
            _arm_and_feed(bus, store, sched, symbol, ts, seq, value)
        chosen = [snap for snap in snaps if snap.symbol == "BBB" and snap.boundary_index == 1]
        assert len(chosen) == 1
        return chosen[0].values["m"]

    bbb = [
        ("BBB", _OPEN + 5 * _NS, 1.0),
        ("BBB", _OPEN + 50 * _NS, 99.0),
    ]
    joint = [
        ("BBB", _OPEN + 5 * _NS, 1.0),
        ("AAA", _OPEN + 31 * _NS, 7.0),
        ("BBB", _OPEN + 50 * _NS, 99.0),
    ]
    solo = _run(frozenset({"BBB"}), bbb)
    wider = _run(frozenset({"AAA", "BBB"}), joint)
    assert solo == 1.0
    assert wider == solo


def _imbalance_spec() -> dict[str, object]:
    raw = copy.deepcopy(yaml.safe_load(_FIXTURE.read_text(encoding="utf-8")))
    assert isinstance(raw, dict)
    risk = raw.setdefault("risk_budget", {})
    assert isinstance(risk, dict)
    risk["capital_allocation_pct"] = 10.0
    risk["max_gross_exposure_pct"] = 100.0
    risk["max_position_per_symbol"] = 500
    risk["max_drawdown_pct"] = 100.0
    raw["horizon_seconds"] = 30
    raw["reads_no_sensor"] = False
    raw["depends_on_sensors"] = ["book_imbalance"]
    raw["signal"] = (
        "def evaluate(snapshot, regime, params):\n"
        "    raw = snapshot.values.get('book_imbalance')\n"
        "    if raw is None or raw < 0.5:\n"
        "        return None\n"
        "    return Signal(\n"
        "        timestamp_ns=snapshot.timestamp_ns,\n"
        "        correlation_id=snapshot.correlation_id,\n"
        "        sequence=snapshot.sequence,\n"
        "        symbol=snapshot.symbol,\n"
        "        strategy_id=alpha_id,\n"
        "        direction=LONG,\n"
        "        strength=1.0,\n"
        "        edge_estimate_bps=40.0,\n"
        "    )\n"
    )
    return raw


def _fills(tape: list[NBBOQuote], symbols: tuple[str, ...]) -> tuple[list[tuple[Any, ...]], int]:
    loaded = _imbalance_spec()
    original = AlphaLoader.load

    def _load(
        self: AlphaLoader,
        path: object,
        param_overrides: dict[str, object] | None = None,
    ) -> object:
        if Path(str(path)) == _FIXTURE:
            return self.load_from_dict(loaded, source=str(_FIXTURE))
        return original(self, path, param_overrides)

    log = InMemoryEventLog()
    log.append_batch(list(tape))
    config = PlatformConfig(
        symbols=frozenset(symbols),
        mode=OperatingMode.BACKTEST,
        alpha_specs=[_FIXTURE],
        sensor_specs=_sensors(),  # type: ignore[arg-type]
        regime_engine=None,
        enforce_trend_mechanism=False,
        session_open_ns=T0,
        risk_max_gross_exposure_pct=100.0,
        account_equity=50_000.0,
    )
    AlphaLoader.load = _load  # type: ignore[method-assign]
    rejects = 0
    try:
        orchestrator, resolved = build_platform(config, event_log=log)

        def _on_verdict(event: RiskVerdict) -> None:
            nonlocal rejects
            if event.action == RiskAction.REJECT:
                rejects += 1

        orchestrator._bus.subscribe(RiskVerdict, _on_verdict)
        orchestrator.boot(resolved)
        orchestrator.run_backtest()
        journal = orchestrator.trade_journal
        assert journal is not None
        rows = [
            (
                record.symbol,
                record.fill_timestamp_ns,
                str(record.fill_price),
                record.filled_quantity,
                record.side.name,
            )
            for record in journal.query()
        ]
    finally:
        AlphaLoader.load = original  # type: ignore[method-assign]
    return rows, rejects


def _bbb_rows(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    return [row[1:] for row in rows if row[0] == "BBB"]


def _sized(symbol: str, ts: int, seq: int, bid_size: int, ask_size: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"{symbol}:{seq}",
        sequence=seq,
        symbol=symbol,
        bid=Decimal("20.00"),
        ask=Decimal("20.01"),
        bid_size=bid_size,
        ask_size=ask_size,
        exchange_timestamp_ns=ts,
        source_layer="INGESTION",
    )


def test_joint_fills_equal_solo_when_no_risk_limit_binds() -> None:
    """Solo and joint fills match when the shared exposure cap does not bind.

    The crossing quote is bid-heavy. The book before that quote is not.
    Risk rejects stay at zero; a difference would be the boundary, not the cap.
    """
    step = 100_000_000
    aaa = make_tape(seed=11, n=400, symbol="AAA", start_ns=T0, size=100, interval_ns=step)
    bbb = make_tape(
        seed=12,
        n=200,
        symbol="BBB",
        start_ns=T0,
        size=100,
        interval_ns=step,
        start_sequence=10_000,
    )
    bbb.append(_sized("BBB", T0 + 35 * _NS, 20_000, 1000, 10))
    bbb.append(_sized("BBB", T0 + 36 * _NS, 20_001, 1000, 10))
    joint = sorted([*aaa, *bbb], key=lambda quote: (quote.timestamp_ns, quote.sequence))
    solo_rows, solo_rejects = _fills(bbb, ("BBB",))
    joint_rows, joint_rejects = _fills(joint, ("AAA", "BBB"))
    assert solo_rejects == 0
    assert joint_rejects == 0
    assert _bbb_rows(solo_rows) == _bbb_rows(joint_rows)

    control = make_tape(
        seed=12,
        n=200,
        symbol="BBB",
        start_ns=T0,
        size=100,
        interval_ns=step,
        start_sequence=10_000,
    )
    control[-1] = replace(control[-1], bid_size=1000, ask_size=10)
    control.append(_sized("BBB", T0 + 35 * _NS, 20_000, 1000, 10))
    control.append(_sized("BBB", T0 + 36 * _NS, 20_001, 1000, 10))
    control_rows, control_rejects = _fills(control, ("BBB",))
    assert control_rejects == 0
    assert control_rows, "pre-boundary imbalance produced no fill"
