"""Injectable clock abstraction (platform invariant 10).

All timestamps in the system flow through this interface.
No raw datetime.now() in core logic.
"""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """Monotonic nanosecond clock used across all layers."""

    def now_ns(self) -> int:
        """Current time in nanoseconds since epoch."""
        ...


class WallClock:
    """Production clock backed by system time."""

    __slots__ = ()

    def now_ns(self) -> int:
        return time.time_ns()


class SimulatedClock:
    """Deterministic clock for backtest and testing.

    Time only advances via explicit set_time() calls,
    ensuring bit-identical replay (invariant 5).
    """

    __slots__ = ("_time_ns",)

    def __init__(self, start_ns: int = 0) -> None:
        self._time_ns = start_ns

    def now_ns(self) -> int:
        return self._time_ns

    def set_time(self, ns: int) -> None:
        if ns < self._time_ns:
            raise ValueError(f"Clock cannot move backward: {ns} < {self._time_ns}")
        self._time_ns = ns
