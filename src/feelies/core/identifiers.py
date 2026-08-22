"""Correlation IDs and sequence management for event provenance (invariant 13)."""

from __future__ import annotations

import hashlib
import threading


def make_correlation_id(symbol: str, exchange_timestamp_ns: int, sequence: int) -> str:
    """Build a correlation ID per the system-architect spec.

    Format: {symbol}:{exchange_timestamp_ns}:{sequence}
    Links a quote update through the entire pipeline to the trade it caused.
    """
    return f"{symbol}:{exchange_timestamp_ns}:{sequence}"


def derive_order_id(seed: str) -> str:
    """Deterministic 16-hex-char order_id from a provenance ``seed`` string.

    The seed is the order's full provenance key (correlation_id, sequence,
    symbol, reason, etc.); identical seeds always produce identical IDs so
    replay is bit-identical (Inv-5).  Callers own the seed format.
    """
    return hashlib.sha256(seed.encode()).hexdigest()[:16]


class SequenceGenerator:
    """Monotonically increasing sequence counter.

    When ``thread_safe=True`` (default), a lock guarantees every ``next()``
    returns a **unique** value. The lock does NOT make the *assignment order*
    deterministic across concurrent callers: if two threads race on
    ``next()``, which one gets the lower value depends on OS scheduling.
    Deterministic replay (Inv-5) therefore requires single-threaded sequence
    allocation — which is exactly the backtest/replay path.  Live/paper runs
    may allocate from multiple threads, where uniqueness holds but
    cross-thread ordering is not reproducible (acceptable: live is not
    replay-hashed).

    Pass ``thread_safe=False`` on the single-threaded BACKTEST path to skip
    the lock (measured hot-path overhead; emission order is unchanged).

    ``stream`` is a keyword-only name for the sequence this generator owns.
    Production call sites in ``src/feelies`` must pass it; S12 enforces that.
    Tests and scripts may omit it — they are not sequence authorities.
    """

    __slots__ = ("_counter", "_lock", "_stream", "_start")

    def __init__(
        self,
        start: int = 0,
        *,
        thread_safe: bool = True,
        stream: str | None = None,
    ) -> None:
        self._start = start
        self._counter = start
        self._lock: threading.Lock | None = threading.Lock() if thread_safe else None
        self._stream = stream

    def reset(self) -> None:
        """Restore the counter to the constructor ``start`` value."""
        lock = self._lock
        if lock is None:
            self._counter = self._start
            return
        with lock:
            self._counter = self._start

    def next(self) -> int:
        lock = self._lock
        if lock is None:
            seq = self._counter
            self._counter += 1
            return seq
        with lock:
            seq = self._counter
            self._counter += 1
            return seq
