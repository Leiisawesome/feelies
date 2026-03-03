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
    """Sequential tick-processing pipeline states."""

    WAITING_FOR_MARKET_EVENT = auto()
    MARKET_EVENT_RECEIVED = auto()
    STATE_UPDATE = auto()
    FEATURE_COMPUTE = auto()
    SIGNAL_EVALUATE = auto()
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
    MicroState.STATE_UPDATE: frozenset({
        MicroState.FEATURE_COMPUTE,
    }),
    MicroState.FEATURE_COMPUTE: frozenset({
        MicroState.SIGNAL_EVALUATE,
    }),
    MicroState.SIGNAL_EVALUATE: frozenset({
        MicroState.RISK_CHECK,
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
