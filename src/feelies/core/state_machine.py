"""Generic deterministic state machine framework.

Used by all state machines in the system: macro, micro, order,
risk escalation, data integrity.

Every transition is validated against a frozen transition table,
logged, and emitted as a typed record. No silent transitions allowed.

Tradeoff: type safety + auditability over flexibility.
The transition table is frozen at construction — dynamic rule
changes at runtime are forbidden to preserve determinism.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

from feelies.core.clock import Clock

S = TypeVar("S", bound=Enum)


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    """Immutable record of a state transition for audit trail (invariant 13)."""

    machine_name: str
    from_state: str
    to_state: str
    trigger: str
    timestamp_ns: int
    correlation_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class IllegalTransition(Exception):
    """Raised when a forbidden state transition is attempted."""

    def __init__(self, machine: str, from_state: Enum, to_state: Enum, trigger: str) -> None:
        self.machine = machine
        self.from_state = from_state
        self.to_state = to_state
        self.trigger = trigger
        super().__init__(
            f"[{machine}] Illegal transition: {from_state.name} -> {to_state.name} "
            f"(trigger: {trigger})"
        )


class StateMachine(Generic[S]):
    """Deterministic state machine with enforced transition table.

    The transition table maps each state to the set of states it may
    transition to.  Attempting any transition not in the table raises
    ``IllegalTransition``.

    Callbacks registered via ``on_transition`` fire synchronously
    *before* the state pointer is updated — listeners see the old
    state as ``record.from_state`` and the new state as
    ``record.to_state``.

    Not thread-safe: ``transition()``'s check-then-act sequence
    (``can_transition`` → build record → run callbacks → commit) holds no
    lock, unlike ``SequenceGenerator``. This is safe today because every
    consumer drives it from a single thread — e.g. ``OrderState``
    transitions only ever run on the orchestrator's tick thread; broker
    callback threads (``broker/ib/connection.py``) communicate exclusively
    through thread-safe ``queue.Queue``s and never touch a ``StateMachine``
    instance directly. A future consumer that transitions the same
    instance from more than one thread would need to add external
    synchronization.
    """

    __slots__ = (
        "_name",
        "_initial_state",
        "_state",
        "_transitions",
        "_clock",
        "_history",
        "_on_transition_callbacks",
        "_timing_sink",
        "_timing_key",
    )

    def __init__(
        self,
        name: str,
        initial_state: S,
        transitions: dict[S, frozenset[S]],
        clock: Clock,
        *,
        history_limit: int | None = None,
        timing_key: str | None = None,
    ) -> None:
        self._name = name
        self._initial_state = initial_state
        self._state = initial_state
        self._transitions: dict[S, frozenset[S]] = dict(transitions)
        self._clock = clock
        # Unbounded by default (alpha-lifecycle SM reads full history).
        # Micro/macro tick SMs pass a ring-buffer limit to bound memory
        # on long backtest replays (~8 transitions × 80k quotes).
        if history_limit is None:
            self._history: list[TransitionRecord] | deque[TransitionRecord] = []
        else:
            if history_limit < 1:
                raise ValueError(f"[{name}] history_limit must be >= 1, got {history_limit}")
            self._history = deque(maxlen=history_limit)
        self._on_transition_callbacks: list[Callable[[TransitionRecord], None]] = []
        # Optional wall-time sink for hot-path attribution (micro SM).
        self._timing_sink: dict[str, int] | None = None
        self._timing_key = timing_key

        # Validate completeness: every member of the enum must have
        # an entry in the transition table.  A missing entry would
        # silently make that state terminal — undefined behavior.
        enum_cls = type(initial_state)
        missing = {m for m in enum_cls} - set(self._transitions.keys())
        if missing:
            names = ", ".join(sorted(m.name for m in missing))
            raise ValueError(
                f"[{name}] Transition table incomplete — missing entries "
                f"for: {names}. Every state must be explicitly listed, "
                f"even if its allowed targets are empty (terminal)."
            )

    def bind_timing_sink(self, sink: dict[str, int] | None) -> None:
        """Bind a per-tick timing dict; ``None`` disables accumulation."""
        self._timing_sink = sink

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> S:
        return self._state

    @property
    def history(self) -> list[TransitionRecord]:
        return list(self._history)

    def on_transition(self, callback: Callable[[TransitionRecord], None]) -> None:
        """Register a callback invoked during each successful transition.

        Callbacks run after validation and record construction, but **before**
        the state pointer and history are updated — subscribers must treat
        ``record.from_state`` / ``record.to_state`` as the authoritative edge.
        """
        self._on_transition_callbacks.append(callback)

    def can_transition(self, target: S) -> bool:
        """Check whether a transition to *target* is valid from current state."""
        return target in self._transitions.get(self._state, frozenset())

    def transition(
        self,
        target: S,
        *,
        trigger: str,
        correlation_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> TransitionRecord:
        """Validate, notify callbacks, then atomically commit a transition.

        A callback exception leaves this machine unchanged. Earlier callbacks'
        external side effects cannot be rolled back, so they must be idempotent
        or reversible.
        """
        if not self.can_transition(target):
            raise IllegalTransition(self._name, self._state, target, trigger)

        sink = self._timing_sink
        key = self._timing_key
        t0 = time.perf_counter_ns() if sink is not None and key is not None else 0

        record = TransitionRecord(
            machine_name=self._name,
            from_state=self._state.name,
            to_state=target.name,
            trigger=trigger,
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            metadata=metadata if metadata is not None else {},
        )

        for callback in self._on_transition_callbacks:
            callback(record)

        self._history.append(record)
        self._state = target
        if sink is not None and key is not None:
            sink[key] = sink.get(key, 0) + (time.perf_counter_ns() - t0)
        return record

    def reset(
        self,
        *,
        trigger: str = "reset",
        correlation_id: str = "",
    ) -> TransitionRecord:
        """Unconditional return to initial state with full audit trail.

        Unlike ``transition()``, this does NOT validate against the
        transition table — it is an unconditional reinitialization.
        History is preserved for audit; the reset itself is logged
        with ``metadata={"type": "reset"}`` so subscribers can
        distinguish it from a normal transition.

        Commit semantics match ``transition()``: callbacks fire
        before history/state are updated.
        """
        record = TransitionRecord(
            machine_name=self._name,
            from_state=self._state.name,
            to_state=self._initial_state.name,
            trigger=trigger,
            timestamp_ns=self._clock.now_ns(),
            correlation_id=correlation_id,
            metadata={"type": "reset"},
        )
        for callback in self._on_transition_callbacks:
            callback(record)
        self._history.append(record)
        self._state = self._initial_state
        return record

    def assert_state(self, expected: S) -> None:
        """Assert current state matches *expected*.  Fails loudly."""
        if self._state is not expected:
            raise AssertionError(
                f"[{self._name}] Expected state {expected.name}, got {self._state.name}"
            )
