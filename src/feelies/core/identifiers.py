"""Correlation IDs and sequence management for event provenance (invariant 13)."""

from __future__ import annotations

import threading


def make_correlation_id(symbol: str, exchange_timestamp_ns: int, sequence: int) -> str:
    """Build a correlation ID per the system-architect spec.

    Format: {symbol}:{exchange_timestamp_ns}:{sequence}
    Links a quote update through the entire pipeline to the trade it caused.
    """
    return f"{symbol}:{exchange_timestamp_ns}:{sequence}"


class SequenceGenerator:
    """Thread-safe monotonically increasing sequence counter."""

    __slots__ = ("_counter", "_lock")

    def __init__(self, start: int = 0) -> None:
        self._counter = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            seq = self._counter
            self._counter += 1
            return seq
