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
    """Sequential tick-processing states.

    Sensor, horizon, signal, and portfolio states are visited only when their
    layers are configured. ``FEATURE_COMPUTE`` remains a bookkeeping state in
    the legal transition spine.
    """

    WAITING_FOR_MARKET_EVENT = auto()
    MARKET_EVENT_RECEIVED = auto()
    STATE_UPDATE = auto()
    SENSOR_UPDATE = auto()  # Layer-1 sensor fan-out
    HORIZON_CHECK = auto()  # scheduler boundary check
    HORIZON_AGGREGATE = auto()  # aggregator snapshot emit
    SIGNAL_GATE = auto()  # HorizonSignalEngine emit
    CROSS_SECTIONAL = auto()  # CompositionEngine emit
    FEATURE_COMPUTE = auto()
    SIGNAL_EVALUATE = auto()
    RISK_CHECK = auto()
    ORDER_DECISION = auto()
    ORDER_SUBMIT = auto()
    ORDER_ACK = auto()
    POSITION_UPDATE = auto()
    LOG_AND_METRICS = auto()


_MICRO_TRANSITIONS: dict[MicroState, frozenset[MicroState]] = {
    MicroState.WAITING_FOR_MARKET_EVENT: frozenset(
        {
            MicroState.MARKET_EVENT_RECEIVED,
        }
    ),
    MicroState.MARKET_EVENT_RECEIVED: frozenset(
        {
            MicroState.STATE_UPDATE,
        }
    ),
    # STATE_UPDATE branches:
    # Sensor-enabled configs visit SENSOR_UPDATE; sensor-empty configs skip it.
    MicroState.STATE_UPDATE: frozenset(
        {
            MicroState.SENSOR_UPDATE,  # sensor layer registered
            MicroState.FEATURE_COMPUTE,  # sensor/scheduler-empty fast-path
        }
    ),
    MicroState.SENSOR_UPDATE: frozenset(
        {
            MicroState.HORIZON_CHECK,
        }
    ),
    # HORIZON_CHECK branches:
    #   any tick crossed → HORIZON_AGGREGATE
    #   no tick crossed  → FEATURE_COMPUTE (skip aggregate)
    MicroState.HORIZON_CHECK: frozenset(
        {
            MicroState.HORIZON_AGGREGATE,
            MicroState.FEATURE_COMPUTE,
        }
    ),
    # HORIZON_AGGREGATE branches (orchestrator picks exactly one per tick):
    # SIGNAL alphas visit SIGNAL_GATE; otherwise proceed to FEATURE_COMPUTE.
    MicroState.HORIZON_AGGREGATE: frozenset(
        {
            MicroState.SIGNAL_GATE,
            MicroState.CROSS_SECTIONAL,
            MicroState.FEATURE_COMPUTE,
        }
    ),
    # SIGNAL_GATE branches:
    # PORTFOLIO alphas visit CROSS_SECTIONAL before FEATURE_COMPUTE.
    MicroState.SIGNAL_GATE: frozenset(
        {
            MicroState.CROSS_SECTIONAL,
            MicroState.FEATURE_COMPUTE,
        }
    ),
    # PORTFOLIO can walk M5–M10 here when :meth:`Orchestrator._flush_pending_sized_intents`
    # drains horizon-buffered ``SizedPositionIntent`` events before M3.
    MicroState.CROSS_SECTIONAL: frozenset(
        {
            MicroState.FEATURE_COMPUTE,
            MicroState.RISK_CHECK,
        }
    ),
    MicroState.FEATURE_COMPUTE: frozenset(
        {
            MicroState.SIGNAL_EVALUATE,
        }
    ),
    # M4 branches:
    #   signal selected → RISK_CHECK (multi-alpha arbitration is bus-side
    #   before M4; see ``Orchestrator._select_bus_signal``)
    #   no signal this tick → LOG_AND_METRICS
    #   (FORCE_FLATTEN is evaluated only after RISK_CHECK on the SIGNAL path.)
    MicroState.SIGNAL_EVALUATE: frozenset(
        {
            MicroState.RISK_CHECK,
            MicroState.LOG_AND_METRICS,
        }
    ),
    # M5 branches: risk pass + order needed → M6, risk pass + no order → M10.
    # Risk fail → cross-machine to G8 (handled by orchestrator, not in this table).
    MicroState.RISK_CHECK: frozenset(
        {
            MicroState.ORDER_DECISION,  # risk pass, order warranted
            MicroState.LOG_AND_METRICS,  # risk pass, no order (flat / reject)
        }
    ),
    # M6 branches: check_order pass → M7, check_order reject → M10.
    MicroState.ORDER_DECISION: frozenset(
        {
            MicroState.ORDER_SUBMIT,  # check_order pass
            MicroState.LOG_AND_METRICS,  # check_order reject (pre-submission veto)
        }
    ),
    MicroState.ORDER_SUBMIT: frozenset(
        {
            MicroState.ORDER_ACK,
        }
    ),
    MicroState.ORDER_ACK: frozenset(
        {
            MicroState.POSITION_UPDATE,
        }
    ),
    MicroState.POSITION_UPDATE: frozenset(
        {
            MicroState.LOG_AND_METRICS,
        }
    ),
    # Loop back to wait for next tick, continue a PORTFOLIO multi-intent flush on
    # the same quote, or resume M3 after that flush (orchestrator-guarded only).
    MicroState.LOG_AND_METRICS: frozenset(
        {
            MicroState.WAITING_FOR_MARKET_EVENT,
            MicroState.RISK_CHECK,
            MicroState.FEATURE_COMPUTE,
        }
    ),
}


# Ring-buffer depth for micro-SM history.  ~8 transitions per quote × a
# few recent ticks is enough for forensics; the bus still emits every
# StateTransition (Inv-13).  Alpha-lifecycle SM keeps unbounded history.
_MICRO_HISTORY_LIMIT = 256


def create_micro_state_machine(clock: Clock) -> StateMachine[MicroState]:
    """Create the tick-processing pipeline, starting in WAITING."""
    return StateMachine(
        name="tick_pipeline",
        initial_state=MicroState.WAITING_FOR_MARKET_EVENT,
        transitions=_MICRO_TRANSITIONS,
        clock=clock,
        history_limit=_MICRO_HISTORY_LIMIT,
        timing_key="sm_transition_ns",
    )
