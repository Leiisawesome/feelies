"""Micro-state machine for deterministic tick processing (Section III–IV).

Runs inside BACKTEST_MODE, PAPER_TRADING_MODE, and LIVE_TRADING_MODE.
The same machine runs identically in all three modes (invariant 9).

Hard rules:
  - Each step must complete before the next begins.
  - No skipping.
  - No parallel mutation of shared state.
"""

from __future__ import annotations

from enum import Enum, auto

from feelies.core.clock import Clock
from feelies.core.state_machine import StateMachine


class MicroState(Enum):
    """Sequential tick-processing pipeline states.

    Phase 2 additions (sensor layer): three new states slot in
    between ``STATE_UPDATE`` and ``FEATURE_COMPUTE``:

    - ``SENSOR_UPDATE`` — registry fans the event out to every
      registered sensor; each emits at most one ``SensorReading``.
    - ``HORIZON_CHECK`` — scheduler inspects the event time and
      emits any ``HorizonTick`` events for crossed boundaries.
    - ``HORIZON_AGGREGATE`` — Phase-2-β aggregator drains the
      sensor buffer for each emitted tick and publishes a
      ``HorizonFeatureSnapshot`` (passive in P2-α).

    These three states are **only entered when at least one sensor
    is registered** (``sensor_specs`` non-empty in
    :class:`feelies.core.platform_config.PlatformConfig`).  Without
    sensors the orchestrator transitions
    ``STATE_UPDATE → FEATURE_COMPUTE`` directly, preserving the
    legacy bit-identical execution path (Inv-A in the plan).

    Phase 3 addition (signal layer): one new state slots in between
    ``HORIZON_AGGREGATE`` and ``FEATURE_COMPUTE``:

    - ``SIGNAL_GATE`` — :class:`HorizonSignalEngine` evaluates each
      registered SIGNAL alpha against the boundary's
      ``HorizonFeatureSnapshot`` and the latest ``RegimeState``,
      publishing zero or more ``Signal(layer='SIGNAL')`` events on the
      bus.

    ``SIGNAL_GATE`` is entered **only when at least one SIGNAL alpha
    is registered** (``AlphaRegistry.has_signal_alphas()`` is true);
    otherwise the orchestrator transitions
    ``HORIZON_AGGREGATE → FEATURE_COMPUTE`` directly so LEGACY_SIGNAL
    runs (and runs without SIGNAL alphas) remain bit-identical to the
    Phase-2 execution path (Inv-A).

    Phase 4 addition (composition layer): one new state slots in after
    ``SIGNAL_GATE`` (or ``HORIZON_AGGREGATE`` when no SIGNAL alphas
    are present) and before ``FEATURE_COMPUTE``:

    - ``CROSS_SECTIONAL`` — :class:`UniverseSynchronizer` and
      :class:`CompositionEngine` evaluate every registered PORTFOLIO
      alpha against the barrier-synced
      :class:`feelies.core.events.CrossSectionalContext`, publishing
      one :class:`feelies.core.events.SizedPositionIntent` per alpha
      per barrier.

    ``CROSS_SECTIONAL`` is entered **only when at least one PORTFOLIO
    alpha is registered** (``AlphaRegistry.has_portfolio_alphas()`` is
    true); otherwise the orchestrator preserves the prior transition
    edges so LEGACY_SIGNAL / SIGNAL-only runs remain bit-identical to
    the Phase-3 execution path (Inv-A).
    """

    WAITING_FOR_MARKET_EVENT = auto()
    MARKET_EVENT_RECEIVED = auto()
    STATE_UPDATE = auto()
    SENSOR_UPDATE = auto()         # NEW (P2-α): Layer-1 sensor fan-out
    HORIZON_CHECK = auto()         # NEW (P2-α): scheduler boundary check
    HORIZON_AGGREGATE = auto()     # NEW (P2-α): aggregator snapshot emit
    SIGNAL_GATE = auto()           # NEW (P3-α): HorizonSignalEngine emit
    CROSS_SECTIONAL = auto()       # NEW (P4):   CompositionEngine emit
    FEATURE_COMPUTE = auto()
    SIGNAL_EVALUATE = auto()
    ORDER_AGGREGATION = auto()
    RISK_CHECK = auto()
    ORDER_DECISION = auto()
    ORDER_SUBMIT = auto()
    ORDER_ACK = auto()
    POSITION_UPDATE = auto()
    LOG_AND_METRICS = auto()


_MICRO_TRANSITIONS: dict[MicroState, frozenset[MicroState]] = {
    MicroState.WAITING_FOR_MARKET_EVENT: frozenset({
        MicroState.MARKET_EVENT_RECEIVED,
    }),
    MicroState.MARKET_EVENT_RECEIVED: frozenset({
        MicroState.STATE_UPDATE,
    }),
    # STATE_UPDATE branches:
    #   sensor-enabled config: → SENSOR_UPDATE (P2-α)
    #   legacy / sensor-empty config: → FEATURE_COMPUTE (bit-identical Phase-1 path)
    MicroState.STATE_UPDATE: frozenset({
        MicroState.SENSOR_UPDATE,    # sensor layer registered
        MicroState.FEATURE_COMPUTE,  # legacy fast-path
    }),
    MicroState.SENSOR_UPDATE: frozenset({
        MicroState.HORIZON_CHECK,
    }),
    # HORIZON_CHECK branches:
    #   any tick crossed → HORIZON_AGGREGATE
    #   no tick crossed  → FEATURE_COMPUTE (skip aggregate)
    MicroState.HORIZON_CHECK: frozenset({
        MicroState.HORIZON_AGGREGATE,
        MicroState.FEATURE_COMPUTE,
    }),
    # HORIZON_AGGREGATE branches:
    #   SIGNAL alpha(s) loaded → SIGNAL_GATE (P3-α)
    #   PORTFOLIO alpha(s) only → CROSS_SECTIONAL (P4 — skip SIGNAL_GATE)
    #   no SIGNAL alpha        → FEATURE_COMPUTE (Phase-2 bit-identical fast-path)
    MicroState.HORIZON_AGGREGATE: frozenset({
        MicroState.SIGNAL_GATE,
        MicroState.CROSS_SECTIONAL,
        MicroState.FEATURE_COMPUTE,
    }),
    # SIGNAL_GATE branches:
    #   PORTFOLIO alpha(s) loaded → CROSS_SECTIONAL (P4)
    #   no PORTFOLIO alpha        → FEATURE_COMPUTE (Phase-3 bit-identical)
    MicroState.SIGNAL_GATE: frozenset({
        MicroState.CROSS_SECTIONAL,
        MicroState.FEATURE_COMPUTE,
    }),
    MicroState.CROSS_SECTIONAL: frozenset({
        MicroState.FEATURE_COMPUTE,
    }),
    MicroState.FEATURE_COMPUTE: frozenset({
        MicroState.SIGNAL_EVALUATE,
    }),
    # M4 branches:
    #   single-alpha: signal → RISK_CHECK
    #   multi-alpha:  intents → ORDER_AGGREGATION
    #   no signal / force_flatten: → LOG_AND_METRICS
    MicroState.SIGNAL_EVALUATE: frozenset({
        MicroState.RISK_CHECK,          # single-alpha path
        MicroState.ORDER_AGGREGATION,   # multi-alpha path
        MicroState.LOG_AND_METRICS,     # no signal / force_flatten
    }),
    # Multi-alpha: aggregated orders ready → ORDER_DECISION, or empty → M10.
    MicroState.ORDER_AGGREGATION: frozenset({
        MicroState.ORDER_DECISION,
        MicroState.LOG_AND_METRICS,
    }),
    # M5 branches: risk pass + order needed → M6, risk pass + no order → M10.
    # Risk fail → cross-machine to G8 (handled by orchestrator, not in this table).
    MicroState.RISK_CHECK: frozenset({
        MicroState.ORDER_DECISION,   # risk pass, order warranted
        MicroState.LOG_AND_METRICS,  # risk pass, no order (flat / reject)
    }),
    # M6 branches: check_order pass → M7, check_order reject → M10.
    MicroState.ORDER_DECISION: frozenset({
        MicroState.ORDER_SUBMIT,    # check_order pass
        MicroState.LOG_AND_METRICS,  # check_order reject (pre-submission veto)
    }),
    MicroState.ORDER_SUBMIT: frozenset({
        MicroState.ORDER_ACK,
    }),
    MicroState.ORDER_ACK: frozenset({
        MicroState.POSITION_UPDATE,
    }),
    MicroState.POSITION_UPDATE: frozenset({
        MicroState.LOG_AND_METRICS,
    }),
    # Loop back to wait for next tick
    MicroState.LOG_AND_METRICS: frozenset({
        MicroState.WAITING_FOR_MARKET_EVENT,
    }),
}


def create_micro_state_machine(clock: Clock) -> StateMachine[MicroState]:
    """Create the tick-processing pipeline, starting in WAITING."""
    return StateMachine(
        name="tick_pipeline",
        initial_state=MicroState.WAITING_FOR_MARKET_EVENT,
        transitions=_MICRO_TRANSITIONS,
        clock=clock,
    )
