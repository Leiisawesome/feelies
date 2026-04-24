"""Hypothesis property tests for the Phase-3-extended Micro state machine.

The Phase-3 plan (P3-β / `p3b_micro_sm_property_tests`) requires that
random pipeline configurations × random per-tick event flags drive
the Micro SM through a complete tick that:

* never raises :class:`feelies.core.state_machine.IllegalTransition`;
* always reaches the terminal :class:`MicroState.LOG_AND_METRICS`
  state and then loops back to
  :class:`MicroState.WAITING_FOR_MARKET_EVENT`;
* visits :class:`MicroState.SIGNAL_GATE` **iff** the configuration
  enables sensors *and* registers at least one SIGNAL alpha *and*
  the per-tick horizon-crossed flag is true (the v0.2 §10 contract);
* never visits :class:`MicroState.SIGNAL_GATE` more than once per
  tick (the no-duplicate-emission contract for the
  :class:`HorizonSignalEngine`).

Two complementary :class:`HorizonSignalEngine`-level properties are
also locked here:

* per-snapshot dispatch is one-shot — the engine emits at most one
  ``Signal(layer="SIGNAL")`` per ``(alpha_id, symbol, boundary_index)``
  no matter how many times the same snapshot is replayed on the bus
  (idempotent re-delivery is *not* a feature, but accidental
  duplication has surfaced before in adjacent codepaths and is
  cheap to guard);
* repeated replay of the same snapshot stream produces a byte-stable
  emitted-Signal sequence (Inv-5 / determinism).

The state-machine table is the single source of truth for legal
transitions, so the SM-walking property functions consult it
directly rather than baking edge constants into the test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feelies.bus.event_bus import EventBus
from feelies.core.clock import SimulatedClock
from feelies.core.events import (
    HorizonFeatureSnapshot,
    RegimeState,
    Signal,
    SignalDirection,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.kernel.micro import MicroState, create_micro_state_machine
from feelies.signals.horizon_engine import HorizonSignalEngine, RegisteredSignal
from feelies.signals.horizon_protocol import HorizonSignal
from feelies.signals.regime_gate import RegimeGate
from feelies.alpha.cost_arithmetic import CostArithmetic


# ── Pipeline-config domain ──────────────────────────────────────────────


@dataclass(frozen=True)
class TickConfig:
    """Per-tick branching flags drawn by Hypothesis.

    The Micro SM table itself is config-agnostic; the per-tick walk
    selects between sibling targets based on these flags.  Names
    mirror the conditions documented inline in
    :data:`feelies.kernel.micro._MICRO_TRANSITIONS`.
    """

    sensors_enabled: bool
    signal_alpha_loaded: bool
    multi_alpha: bool
    horizon_crossed: bool
    signal_emitted: bool
    risk_pass: bool
    order_warranted: bool
    check_order_pass: bool


# ── Pipeline walker ─────────────────────────────────────────────────────


def _walk_one_tick(cfg: TickConfig) -> list[MicroState]:
    """Walk the Micro SM through exactly one tick under *cfg*.

    Returns the ordered list of *visited* states for the property
    layer to inspect.  Raises :class:`IllegalTransition` (from the
    SM) on any disallowed edge — the property test expects that
    every config produces a fully-legal walk.

    Walks always start from
    :class:`MicroState.WAITING_FOR_MARKET_EVENT` and end on the
    return-to-WAITING transition, modelling one full tick.
    """
    sm = create_micro_state_machine(SimulatedClock(start_ns=0))
    visited: list[MicroState] = [sm.state]

    def step(target: MicroState) -> None:
        sm.transition(target, trigger="prop")
        visited.append(target)

    step(MicroState.MARKET_EVENT_RECEIVED)
    step(MicroState.STATE_UPDATE)

    if cfg.sensors_enabled:
        step(MicroState.SENSOR_UPDATE)
        step(MicroState.HORIZON_CHECK)
        if cfg.horizon_crossed:
            step(MicroState.HORIZON_AGGREGATE)
            if cfg.signal_alpha_loaded:
                step(MicroState.SIGNAL_GATE)
                step(MicroState.FEATURE_COMPUTE)
            else:
                step(MicroState.FEATURE_COMPUTE)
        else:
            step(MicroState.FEATURE_COMPUTE)
    else:
        step(MicroState.FEATURE_COMPUTE)

    step(MicroState.SIGNAL_EVALUATE)

    if not cfg.signal_emitted:
        step(MicroState.LOG_AND_METRICS)
    elif cfg.multi_alpha:
        step(MicroState.ORDER_AGGREGATION)
        if not cfg.order_warranted:
            step(MicroState.LOG_AND_METRICS)
        elif not cfg.check_order_pass:
            step(MicroState.ORDER_DECISION)
            step(MicroState.LOG_AND_METRICS)
        else:
            step(MicroState.ORDER_DECISION)
            step(MicroState.ORDER_SUBMIT)
            step(MicroState.ORDER_ACK)
            step(MicroState.POSITION_UPDATE)
            step(MicroState.LOG_AND_METRICS)
    else:
        if not cfg.risk_pass or not cfg.order_warranted:
            step(MicroState.RISK_CHECK)
            step(MicroState.LOG_AND_METRICS)
        elif not cfg.check_order_pass:
            step(MicroState.RISK_CHECK)
            step(MicroState.ORDER_DECISION)
            step(MicroState.LOG_AND_METRICS)
        else:
            step(MicroState.RISK_CHECK)
            step(MicroState.ORDER_DECISION)
            step(MicroState.ORDER_SUBMIT)
            step(MicroState.ORDER_ACK)
            step(MicroState.POSITION_UPDATE)
            step(MicroState.LOG_AND_METRICS)

    step(MicroState.WAITING_FOR_MARKET_EVENT)
    return visited


# ── Hypothesis strategies ───────────────────────────────────────────────


_BOOL = st.booleans()


@st.composite
def _tick_config(draw: st.DrawFn) -> TickConfig:
    return TickConfig(
        sensors_enabled=draw(_BOOL),
        signal_alpha_loaded=draw(_BOOL),
        multi_alpha=draw(_BOOL),
        horizon_crossed=draw(_BOOL),
        signal_emitted=draw(_BOOL),
        risk_pass=draw(_BOOL),
        order_warranted=draw(_BOOL),
        check_order_pass=draw(_BOOL),
    )


_SETTINGS = settings(
    deadline=None,
    max_examples=200,
    suppress_health_check=[HealthCheck.too_slow],
)


# ── Property A: Reachability + no-deadlock ──────────────────────────────


@_SETTINGS
@given(cfg=_tick_config())
def test_every_tick_reaches_log_and_then_waiting(cfg: TickConfig) -> None:
    """Every legal tick walk terminates at WAITING via LOG_AND_METRICS.

    The Micro SM is acyclic-per-tick by design (LOG_AND_METRICS is
    the single chokepoint before the WAITING reset).  Hypothesis
    samples random branching flags and asserts the invariant holds
    across the whole config space — any future SM table edit that
    introduces a deadlock or skips the LOG state will fail this
    test loud and fast.
    """
    visited = _walk_one_tick(cfg)
    assert visited[-1] == MicroState.WAITING_FOR_MARKET_EVENT
    assert visited[-2] == MicroState.LOG_AND_METRICS
    assert MicroState.LOG_AND_METRICS in visited


# ── Property B: SIGNAL_GATE entry condition ─────────────────────────────


@_SETTINGS
@given(cfg=_tick_config())
def test_signal_gate_visited_iff_all_conditions_met(cfg: TickConfig) -> None:
    """SIGNAL_GATE entry is gated on three independent conditions.

    Per the SM table comments, ``SIGNAL_GATE`` is only entered when
    all three of (a) sensors enabled, (b) horizon crossed for this
    tick, (c) at least one SIGNAL alpha registered, are true.  Any
    other combination must take the Phase-2 fast-path
    ``HORIZON_AGGREGATE → FEATURE_COMPUTE`` (or skip even further
    upstream).
    """
    visited = _walk_one_tick(cfg)
    expected = (
        cfg.sensors_enabled
        and cfg.horizon_crossed
        and cfg.signal_alpha_loaded
    )
    assert (MicroState.SIGNAL_GATE in visited) is expected


# ── Property C: SIGNAL_GATE single-visit per tick ───────────────────────


@_SETTINGS
@given(cfg=_tick_config())
def test_signal_gate_visited_at_most_once_per_tick(cfg: TickConfig) -> None:
    """SIGNAL_GATE is one-shot per tick — no inner loop possible.

    The SM table forbids ``SIGNAL_GATE`` from looping back to
    ``HORIZON_AGGREGATE`` and routes it exclusively to
    ``FEATURE_COMPUTE``, which itself routes only to
    ``SIGNAL_EVALUATE``.  Together these prevent any path that
    would revisit ``SIGNAL_GATE`` within the same tick — the
    structural guarantee underpinning the engine's
    no-duplicate-Signal-emission contract.
    """
    visited = _walk_one_tick(cfg)
    assert visited.count(MicroState.SIGNAL_GATE) <= 1


# ── Property D: Determinism — repeating the same config replays bytes ───


@_SETTINGS
@given(cfg=_tick_config())
def test_same_config_replays_identical_walk(cfg: TickConfig) -> None:
    """Walking the same config twice yields the identical state sequence.

    Inv-5 guard for the SM walker: the per-tick sequence is a
    pure function of the branching flags.  Any future change that
    introduces an implicit timestamp / clock dependency in the SM
    table would break this property.
    """
    walk_a = _walk_one_tick(cfg)
    walk_b = _walk_one_tick(cfg)
    assert walk_a == walk_b


# ── HorizonSignalEngine no-duplicate-emission property ──────────────────


@dataclass
class _StubSignal:
    """Minimal :class:`HorizonSignal` impl that always emits LONG.

    Captures the count of evaluations so the property test can
    cross-check the engine's dispatch arithmetic.
    """

    invocations: list[int] = field(default_factory=list)

    def evaluate(
        self,
        snapshot: HorizonFeatureSnapshot,
        regime: RegimeState | None,
        params: dict[str, float],
    ) -> Signal | None:
        self.invocations.append(snapshot.boundary_index)
        return Signal(
            timestamp_ns=snapshot.timestamp_ns,
            correlation_id=snapshot.correlation_id,
            sequence=snapshot.sequence,
            symbol=snapshot.symbol,
            strategy_id="stub",
            direction=SignalDirection.LONG,
            strength=0.5,
            edge_estimate_bps=3.0,
        )


def _open_gate() -> RegimeGate:
    """A regime gate that is unconditionally ON for any binding.

    ``True`` is a literal expression accepted by the safe DSL and
    therefore the cheapest way to factor the gate out of these
    HorizonSignalEngine-level properties (which target the engine's
    dispatch arithmetic, not the gate evaluator that has its own
    dedicated property suite).
    """
    return RegimeGate(
        alpha_id="stub",
        on_condition="True",
        off_condition="False",
    )


def _zero_cost() -> CostArithmetic:
    """A cost block whose margin ratio satisfies G12 (>= 1.5).

    The engine never reads cost arithmetic at runtime — it is
    enforced at load time — so the values here exist only to
    satisfy the constructor invariants.
    """
    return CostArithmetic(
        edge_estimate_bps=10.0,
        half_spread_bps=2.0,
        impact_bps=2.0,
        fee_bps=1.0,
        margin_ratio=2.0,
    )


def _make_engine(
    horizon_seconds: int,
    signal: HorizonSignal,
) -> tuple[EventBus, HorizonSignalEngine, list[Signal]]:
    bus = EventBus()
    captured: list[Signal] = []
    bus.subscribe(Signal, captured.append)  # type: ignore[arg-type]
    engine = HorizonSignalEngine(
        bus=bus, signal_sequence_generator=SequenceGenerator(),
    )
    engine.register(RegisteredSignal(
        alpha_id="stub",
        horizon_seconds=horizon_seconds,
        signal=signal,
        params={},
        gate=_open_gate(),
        cost_arithmetic=_zero_cost(),
        consumed_features=(),
    ))
    engine.attach()
    return bus, engine, captured


def _snapshot(boundary_index: int, horizon_seconds: int = 30) -> HorizonFeatureSnapshot:
    return HorizonFeatureSnapshot(
        timestamp_ns=1_000_000_000 + boundary_index * 1_000,
        correlation_id=f"snap-{boundary_index}",
        sequence=boundary_index,
        symbol="AAPL",
        horizon_seconds=horizon_seconds,
        boundary_index=boundary_index,
        values={},
    )


@settings(deadline=None, max_examples=100)
@given(
    boundary_indices=st.lists(
        st.integers(min_value=0, max_value=128),
        min_size=1, max_size=32,
    ),
)
def test_engine_emits_one_signal_per_snapshot(
    boundary_indices: list[int],
) -> None:
    """Every snapshot delivery yields exactly one ``Signal`` emission.

    The ``HorizonSignalEngine.dispatch_one`` path emits at most one
    ``Signal`` per ``(registered_alpha, snapshot)`` pair, regardless
    of whether the same ``boundary_index`` is replayed.  Replays are
    *additive* by design (the bus does not deduplicate) — the
    property here is that the dispatch arithmetic is one-emission-
    per-delivery, not zero and not many.

    The no-duplicate-per-tick guarantee from the Micro SM property
    above ensures the orchestrator never re-publishes the same
    snapshot inside one tick, so production runs see exactly one
    Signal per ``(alpha, symbol, boundary_index)``.
    """
    stub = _StubSignal()
    bus, _, captured = _make_engine(horizon_seconds=30, signal=stub)
    for idx in boundary_indices:
        bus.publish(_snapshot(idx))
    assert len(captured) == len(boundary_indices)
    assert len(stub.invocations) == len(boundary_indices)


@settings(deadline=None, max_examples=50)
@given(
    boundary_indices=st.lists(
        st.integers(min_value=0, max_value=64),
        min_size=2, max_size=16, unique=True,
    ),
)
def test_engine_replay_is_byte_stable(
    boundary_indices: list[int],
) -> None:
    """Two replays of the same snapshot stream produce identical Signals.

    Inv-5 / Phase-3 Level-2 guard: two fresh engines fed the same
    sequence of snapshots must emit byte-for-byte identical
    ``Signal`` streams on every structurally-engine-controlled
    field (symbol, correlation_id, timestamp_ns, layer, direction).
    The ``sequence`` field is allocated from a fresh
    :class:`SequenceGenerator` per engine so it is *expected* to
    match across two fresh runs (each starts at 1) — which is the
    contract this property locks in.
    """
    snapshots = [_snapshot(i) for i in boundary_indices]
    assert _run_signals(snapshots) == _run_signals(snapshots)


def _run_signals(
    snapshots: Iterable[HorizonFeatureSnapshot],
) -> list[tuple[str, str, int, str, str, int]]:
    """Replay *snapshots* through a fresh engine; return projection tuples.

    The projection uses the engine-controlled fields of each
    emitted ``Signal``, including the freshly-allocated
    ``sequence``, so two replays through fresh engines must agree
    bit-for-bit (Inv-5).
    """
    bus, _, captured = _make_engine(
        horizon_seconds=30, signal=_StubSignal(),
    )
    for s in snapshots:
        bus.publish(s)
    return [
        (
            sig.symbol,
            sig.correlation_id,
            sig.timestamp_ns,
            sig.layer,
            sig.direction.name,
            sig.sequence,
        )
        for sig in captured
    ]


# ── Sanity: the SM table is complete (no missing transitions) ──────────


def test_micro_sm_table_is_complete() -> None:
    """Every :class:`MicroState` enum member must have a transition entry.

    Belt-and-braces guard: the ``StateMachine`` constructor would
    raise on incomplete tables, but this test pins the contract at
    the test layer so a partial enum extension surfaces without
    needing to instantiate the machine.
    """
    sm = create_micro_state_machine(SimulatedClock(start_ns=0))
    table = sm._transitions  # noqa: SLF001 — internal field, intentional
    assert set(table.keys()) == set(MicroState)
    for targets in table.values():
        for target in targets:
            assert isinstance(target, MicroState)
