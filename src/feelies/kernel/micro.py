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
    - ``HORIZON_AGGREGATE`` — aggregator drains the sensor buffer for
      each emitted tick and publishes a ``HorizonFeatureSnapshot``.

    These three states are **only entered when at least one sensor
    is registered** (``sensor_specs`` non-empty in
    :class:`feelies.core.platform_config.PlatformConfig`).  Without
    sensors the orchestrator transitions
    ``STATE_UPDATE → FEATURE_COMPUTE`` directly (Inv-A).

    - ``SIGNAL_GATE`` — :class:`HorizonSignalEngine` evaluates SIGNAL
      alphas against the boundary snapshot + latest ``RegimeState``.
      Entered only when ``AlphaRegistry.has_signal_alphas()`` is true.

    - ``CROSS_SECTIONAL`` — composition evaluates PORTFOLIO alphas
      against a barrier-synced ``CrossSectionalContext``.  Entered only
      when ``AlphaRegistry.has_portfolio_alphas()`` is true.

    ``FEATURE_COMPUTE`` (M3) is bookkeeping only (per-tick feature
    engine removed in D.2); the SM still visits M3 so
    ``FEATURE_COMPUTE → SIGNAL_EVALUATE → …`` remains a legal spine.
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
    #   sensor-enabled config: → SENSOR_UPDATE (P2-α)
    #   legacy / sensor-empty config: → FEATURE_COMPUTE (bit-identical Phase-1 path)
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
    #   SIGNAL alpha(s) loaded → SIGNAL_GATE (P3-α)
    #   else → FEATURE_COMPUTE (Phase-2 fast-path)  OR  via orchestrator bookend
    #   ``CROSS_SECTIONAL`` → FEATURE_COMPUTE when PORTFOLIO alphas are registered
    MicroState.HORIZON_AGGREGATE: frozenset(
        {
            MicroState.SIGNAL_GATE,
            MicroState.CROSS_SECTIONAL,
            MicroState.FEATURE_COMPUTE,
        }
    ),
    # SIGNAL_GATE branches:
    #   PORTFOLIO alpha(s) loaded → CROSS_SECTIONAL (P4)
    #   no PORTFOLIO alpha        → FEATURE_COMPUTE (Phase-3 bit-identical)
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
