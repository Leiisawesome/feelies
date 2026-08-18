"""HARN-2 — deterministic fault injection for conformance replays.

Some conformance tests can only observe a response by first causing the
condition: a latency budget that never breaches proves nothing about the
breach path.  This injects the condition deliberately.

Determinism is the whole constraint.  A slow engine is simulated by
advancing an injected :class:`~feelies.core.clock.SimulatedClock` by a
declared constant, never by sleeping and never by reading wall time, so an
injected replay stays bit-identical under Inv-5 and the injected delay is a
property of the scenario rather than of the host that ran it.

Presently a support artifact with no in-tree consumer: S-07 is the step that
uses it, to drive a latency-budget breach.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ParamSpec, TypeVar

from feelies.core.clock import SimulatedClock

P = ParamSpec("P")
T = TypeVar("T")


@dataclass(frozen=True)
class Injection:
    """One applied fault, in the order it was applied."""

    engine: str
    call_index: int
    delay_ns: int


class FaultInjector:
    """Applies declared faults to engine calls and records what it applied.

    The record is the point: a test asserting that a breach fired has to be
    able to show the breach was provoked, otherwise a silently un-injected
    run and a genuinely fast engine look identical.
    """

    def __init__(self, *, clock: SimulatedClock) -> None:
        self._clock = clock
        self._delays_ns: dict[str, int] = {}
        self._calls: dict[str, int] = {}
        self._injections: list[Injection] = []

    def slow_engine(self, engine: str, delay_ns: int) -> None:
        """Declare that ``engine`` takes an extra ``delay_ns`` per call."""
        if delay_ns < 0:
            raise ValueError(f"delay_ns must be non-negative, got {delay_ns}")
        self._delays_ns[engine] = delay_ns

    def wrap(self, engine: str, fn: Callable[P, T]) -> Callable[P, T]:
        """Return ``fn`` with ``engine``'s declared fault applied around it."""

        def wrapped(*args: P.args, **kwargs: P.kwargs) -> T:
            result = fn(*args, **kwargs)
            delay_ns = self._delays_ns.get(engine)
            if delay_ns is not None:
                call_index = self._calls.get(engine, 0)
                self._calls[engine] = call_index + 1
                self._clock.set_time(self._clock.now_ns() + delay_ns)
                self._injections.append(
                    Injection(engine=engine, call_index=call_index, delay_ns=delay_ns)
                )
            return result

        return wrapped

    @property
    def injections(self) -> tuple[Injection, ...]:
        return tuple(self._injections)
