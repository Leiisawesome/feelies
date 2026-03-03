"""Core primitives shared across all layers."""

from feelies.core.clock import Clock, SimulatedClock, WallClock
from feelies.core.identifiers import SequenceGenerator, make_correlation_id
from feelies.core.state_machine import IllegalTransition, StateMachine, TransitionRecord

__all__ = [
    "Clock",
    "IllegalTransition",
    "SequenceGenerator",
    "SimulatedClock",
    "StateMachine",
    "TransitionRecord",
    "WallClock",
    "make_correlation_id",
]
