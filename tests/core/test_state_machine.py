"""Unit tests for StateMachine and TransitionRecord."""

from __future__ import annotations

from enum import Enum, auto

import pytest

from feelies.core.clock import SimulatedClock
from feelies.core.state_machine import IllegalTransition, StateMachine, TransitionRecord


class SimpleState(Enum):
    A = auto()
    B = auto()
    C = auto()


def _make_sm(
    transitions: dict[SimpleState, frozenset[SimpleState]] | None = None,
) -> StateMachine[SimpleState]:
    trans = transitions or {
        SimpleState.A: frozenset({SimpleState.B}),
        SimpleState.B: frozenset({SimpleState.A, SimpleState.C}),
        SimpleState.C: frozenset({SimpleState.A}),
    }
    return StateMachine(
        name="test_sm",
        initial_state=SimpleState.A,
        transitions=trans,
        clock=SimulatedClock(1000),
    )


class TestTransitionRecord:
    """Tests for TransitionRecord."""

    def test_is_frozen(self) -> None:
        rec = TransitionRecord(
            machine_name="m",
            from_state="A",
            to_state="B",
            trigger="t",
            timestamp_ns=1,
        )
        with pytest.raises(AttributeError):
            rec.machine_name = "x"  # type: ignore[misc]


class TestStateMachine:
    """Tests for StateMachine."""

    def test_initial_state(self) -> None:
        sm = _make_sm()
        assert sm.state == SimpleState.A

    def test_valid_transition(self) -> None:
        sm = _make_sm()
        rec = sm.transition(SimpleState.B, trigger="go")
        assert sm.state == SimpleState.B
        assert rec.from_state == "A"
        assert rec.to_state == "B"
        assert rec.trigger == "go"
        assert len(sm.history) == 1

    def test_illegal_transition_raises(self) -> None:
        sm = _make_sm()
        with pytest.raises(IllegalTransition, match="A -> C"):
            sm.transition(SimpleState.C, trigger="bad")
        assert sm.state == SimpleState.A
        assert len(sm.history) == 0

    def test_can_transition(self) -> None:
        sm = _make_sm()
        assert sm.can_transition(SimpleState.B) is True
        assert sm.can_transition(SimpleState.C) is False
        sm.transition(SimpleState.B, trigger="t")
        assert sm.can_transition(SimpleState.A) is True
        assert sm.can_transition(SimpleState.C) is True

    def test_callback_fires_before_state_update(self) -> None:
        sm = _make_sm()
        seen: list[TransitionRecord] = []

        def cb(rec: TransitionRecord) -> None:
            seen.append(rec)
            assert sm.state == SimpleState.A

        sm.on_transition(cb)
        sm.transition(SimpleState.B, trigger="t")
        assert len(seen) == 1
        assert seen[0].from_state == "A"
        assert seen[0].to_state == "B"
        assert sm.state == SimpleState.B

    def test_callback_raises_prevents_transition(self) -> None:
        sm = _make_sm()

        def cb(rec: TransitionRecord) -> None:
            raise RuntimeError("veto")

        sm.on_transition(cb)
        with pytest.raises(RuntimeError, match="veto"):
            sm.transition(SimpleState.B, trigger="t")
        assert sm.state == SimpleState.A
        assert len(sm.history) == 0

    def test_multi_callback_rollback_boundary(self) -> None:
        # When a later callback vetoes, the SM rolls back its OWN state, but
        # an earlier callback's external side effect is NOT undone — the SM
        # cannot reverse effects it does not own (documented contract).
        sm = _make_sm()
        external_effects: list[str] = []

        def first(rec: TransitionRecord) -> None:
            external_effects.append("first-ran")

        def second(rec: TransitionRecord) -> None:
            raise RuntimeError("veto")

        sm.on_transition(first)
        sm.on_transition(second)
        with pytest.raises(RuntimeError, match="veto"):
            sm.transition(SimpleState.B, trigger="t")

        # SM state/history rolled back ...
        assert sm.state == SimpleState.A
        assert len(sm.history) == 0
        # ... but the first callback's external effect persists.
        assert external_effects == ["first-ran"]

    def test_reset_unconditional(self) -> None:
        sm = _make_sm()
        sm.transition(SimpleState.B, trigger="t")
        sm.transition(SimpleState.C, trigger="t2")
        rec = sm.reset(trigger="reset")
        assert sm.state == SimpleState.A
        assert rec.to_state == "A"
        assert rec.metadata.get("type") == "reset"
        assert len(sm.history) == 3

    def test_assert_state(self) -> None:
        sm = _make_sm()
        sm.assert_state(SimpleState.A)
        sm.transition(SimpleState.B, trigger="t")
        sm.assert_state(SimpleState.B)
        with pytest.raises(AssertionError, match="Expected state A"):
            sm.assert_state(SimpleState.A)

    def test_history_limit_rings(self) -> None:
        sm = StateMachine(
            name="ring",
            initial_state=SimpleState.A,
            transitions={
                SimpleState.A: frozenset({SimpleState.B}),
                SimpleState.B: frozenset({SimpleState.A, SimpleState.C}),
                SimpleState.C: frozenset({SimpleState.A}),
            },
            clock=SimulatedClock(0),
            history_limit=2,
        )
        sm.transition(SimpleState.B, trigger="1")
        sm.transition(SimpleState.A, trigger="2")
        sm.transition(SimpleState.B, trigger="3")
        hist = sm.history
        assert len(hist) == 2
        assert hist[0].trigger == "2"
        assert hist[1].trigger == "3"

    def test_incomplete_transition_table_raises(self) -> None:
        clock = SimulatedClock(0)
        with pytest.raises(ValueError, match="incomplete"):
            StateMachine(
                name="bad",
                initial_state=SimpleState.A,
                transitions={
                    SimpleState.A: frozenset({SimpleState.B}),
                    # missing B and C
                },
                clock=clock,
            )
