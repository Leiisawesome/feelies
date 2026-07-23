"""Tests for the ``RiskLevel`` transition table.

Every legal edge succeeds. Skipped or backward transitions raise
``IllegalTransition`` without changing state.
"""

from __future__ import annotations

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition, StateMachine
from feelies.risk.escalation import RiskLevel, create_risk_escalation_machine

# The single legal forward chain (plus the one loosening edge LOCKED -> NORMAL).
_CHAIN: list[RiskLevel] = [
    RiskLevel.NORMAL,
    RiskLevel.WARNING,
    RiskLevel.BREACH_DETECTED,
    RiskLevel.FORCED_FLATTEN,
    RiskLevel.LOCKED,
]


def _machine() -> StateMachine[RiskLevel]:
    return create_risk_escalation_machine(SimulatedClock(start_ns=0))


def _walk_to(sm: StateMachine[RiskLevel], level: RiskLevel) -> None:
    """Drive ``sm`` from NORMAL to ``level`` via the legal forward chain."""
    for step in _CHAIN[1 : _CHAIN.index(level) + 1]:
        sm.transition(step, trigger="setup")


def test_starts_at_normal() -> None:
    assert _machine().state == RiskLevel.NORMAL


@pytest.mark.parametrize(
    "start,target",
    [(_CHAIN[i], _CHAIN[(i + 1) % len(_CHAIN)]) for i in range(len(_CHAIN))],
)
def test_legal_edges_succeed(start: RiskLevel, target: RiskLevel) -> None:
    sm = _machine()
    _walk_to(sm, start)
    sm.transition(target, trigger="probe")
    assert sm.state == target


@pytest.mark.parametrize(
    "start,target",
    [
        (start, target)
        for start in _CHAIN
        for target in _CHAIN
        # Exclude self (untested no-op case) and the one legal edge from `start`.
        if target != start and target != _CHAIN[(_CHAIN.index(start) + 1) % len(_CHAIN)]
    ],
)
def test_illegal_edges_raise_without_mutating_state(start: RiskLevel, target: RiskLevel) -> None:
    sm = _machine()
    _walk_to(sm, start)
    with pytest.raises(IllegalTransition):
        sm.transition(target, trigger="probe")
    assert sm.state == start


def test_warning_cannot_skip_directly_to_locked() -> None:
    """A callback failure may strand escalation at WARNING."""
    sm = _machine()
    _walk_to(sm, RiskLevel.WARNING)
    with pytest.raises(IllegalTransition):
        sm.transition(RiskLevel.LOCKED, trigger="probe")
    assert sm.state == RiskLevel.WARNING


def test_breach_detected_cannot_transition_directly_to_normal() -> None:
    """``.transition()`` may strand escalation at BREACH_DETECTED when
    (unlike ``.reset()``) must reject a direct de-escalation edge."""
    sm = _machine()
    _walk_to(sm, RiskLevel.BREACH_DETECTED)
    with pytest.raises(IllegalTransition):
        sm.transition(RiskLevel.NORMAL, trigger="probe")
    assert sm.state == RiskLevel.BREACH_DETECTED


def test_locked_only_loosens_to_normal() -> None:
    sm = _machine()
    _walk_to(sm, RiskLevel.LOCKED)
    assert sm.can_transition(RiskLevel.NORMAL)
    assert not sm.can_transition(RiskLevel.WARNING)
    assert not sm.can_transition(RiskLevel.BREACH_DETECTED)
    assert not sm.can_transition(RiskLevel.FORCED_FLATTEN)
