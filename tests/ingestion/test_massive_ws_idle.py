"""Tests for :meth:`MassiveLiveFeed.events` IdleTick yielding.

When the WS queue is empty and the stop event is unset, the feed
must yield :class:`IdleTick` sentinels so the orchestrator can drain
broker-pushed fills between market events.  When the stop event is
set, the iterator must terminate within one timeout cycle.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Iterator

import pytest

from feelies.core.clock import Clock
from feelies.ingestion.idle_tick import IdleTick
from feelies.ingestion.massive_normalizer import MassiveNormalizer
from feelies.ingestion.massive_ws import MassiveLiveFeed


class _AdvancingClock:
    """Deterministic ns clock that advances by 1_000_000_000 per read."""

    __slots__ = ("_now",)

    def __init__(self, start: int = 0) -> None:
        self._now = start

    def now_ns(self) -> int:
        self._now += 1_000_000_000
        return self._now


def _make_feed(clock: Clock) -> MassiveLiveFeed:
    """Construct a feed without ever calling start() — used for unit tests."""
    normalizer = MassiveNormalizer(clock=clock)
    feed = MassiveLiveFeed(
        api_key="dummy",
        symbols=("AAPL",),
        normalizer=normalizer,
        clock=clock,
    )
    # Shrink internal queue timeout for snappy test iteration.
    return feed


def _take_n(it: Iterator, n: int) -> list:
    """Pull up to n items from an iterator without blocking on exhaustion."""
    out = []
    for _ in range(n):
        try:
            out.append(next(it))
        except StopIteration:
            break
    return out


def test_events_yields_idle_tick_when_queue_empty() -> None:
    clock = _AdvancingClock()
    feed = _make_feed(clock)
    # Spin up the iterator on a background thread (each .get() blocks
    # for 1s, so three ticks take ~3s — keep this snappy by sampling
    # only one tick on the main thread).
    it = feed.events()
    first = next(it)
    assert isinstance(first, IdleTick)
    assert first.timestamp_ns > 0


def test_events_yields_distinct_idle_tick_timestamps() -> None:
    clock = _AdvancingClock()
    feed = _make_feed(clock)
    it = feed.events()
    ticks = [next(it), next(it)]
    assert all(isinstance(t, IdleTick) for t in ticks)
    assert ticks[0].timestamp_ns != ticks[1].timestamp_ns
    assert ticks[1].timestamp_ns > ticks[0].timestamp_ns


def test_events_returns_when_stop_event_set() -> None:
    clock = _AdvancingClock()
    feed = _make_feed(clock)
    feed._stop_event.set()
    # On an empty queue with stop_event set, the iterator must return
    # within one timeout cycle (~1s) — assert by treating the
    # generator as a list (StopIteration → empty list).
    done = threading.Event()

    def consume() -> None:
        for _ in feed.events():
            break  # should not happen
        done.set()

    t = threading.Thread(target=consume, daemon=True)
    t.start()
    assert done.wait(timeout=2.0), "events() did not terminate on stop_event"


def test_events_passes_through_real_items_unchanged() -> None:
    """Item placed on the queue (not the sentinel) must yield as-is."""
    clock = _AdvancingClock()
    feed = _make_feed(clock)
    # Put a sentinel object that mimics a typed event; the iterator
    # yields whatever is on the queue (it does not validate the type).
    marker = object()
    feed._queue.put_nowait(marker)
    it = feed.events()
    assert next(it) is marker


def test_events_sentinel_terminates_iterator() -> None:
    clock = _AdvancingClock()
    feed = _make_feed(clock)
    # Enqueue the module-level sentinel that stop() uses internally.
    from feelies.ingestion.massive_ws import _SENTINEL

    feed._queue.put_nowait(_SENTINEL)
    assert list(feed.events()) == []


def test_start_drains_stale_sentinel_from_prior_stop() -> None:
    """stop() sentinel must not kill the next session on the same feed."""
    clock = _AdvancingClock()
    feed = _make_feed(clock)
    feed._stop_event.set()
    feed.stop()  # enqueues _SENTINEL while consumer is not running
    assert feed._queue.qsize() >= 1
    feed._stop_event.clear()
    feed._drain_stale_sentinels()  # same drain start() performs before reconnect
    first = next(feed.events())
    assert isinstance(first, IdleTick)


def test_start_preserves_buffered_events_while_draining_sentinel() -> None:
    clock = _AdvancingClock()
    feed = _make_feed(clock)
    marker = object()
    feed._queue.put_nowait(marker)
    from feelies.ingestion.massive_ws import _SENTINEL

    feed._queue.put_nowait(_SENTINEL)
    feed._drain_stale_sentinels()
    assert feed._queue.qsize() == 1
    assert feed._queue.get_nowait() is marker
