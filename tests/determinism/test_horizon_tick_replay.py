"""Replay parity for scheduler ``HorizonTick`` output.

The baseline pins boundary math, ordering, correlation IDs, and sequence
allocation over the canonical five-minute fixture.
"""

from __future__ import annotations

from tests.fixtures.replay import (
    hash_horizon_tick_stream,
    replay_quotes_through_scheduler,
)


# Canonical fixture and scheduler output.
EXPECTED_LEVEL2_TICK_HASH = "316765d45725f91373da2dfa6a5e201f6349bdae566980b20b220c481b9793c2"
EXPECTED_LEVEL2_TICK_COUNT = 28


def test_horizon_tick_stream_matches_locked_baseline() -> None:
    ticks, _ = replay_quotes_through_scheduler()
    actual_hash = hash_horizon_tick_stream(ticks)
    assert len(ticks) == EXPECTED_LEVEL2_TICK_COUNT, (
        f"emitted-tick count drift: expected {EXPECTED_LEVEL2_TICK_COUNT}, got {len(ticks)}"
    )
    assert actual_hash == EXPECTED_LEVEL2_TICK_HASH, (
        "Level-2 HorizonTick hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL2_TICK_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update EXPECTED_LEVEL2_TICK_HASH with "
        "justification in the commit message."
    )


def test_two_replays_produce_identical_hash() -> None:
    """Sanity: replay determinism at this layer (no shared state).

    Catches accidental introduction of process-level mutable state
    (singletons, module-level caches) in the scheduler implementation
    that would only surface when running it twice.
    """
    ticks_a, _ = replay_quotes_through_scheduler()
    ticks_b, _ = replay_quotes_through_scheduler()
    assert hash_horizon_tick_stream(ticks_a) == hash_horizon_tick_stream(ticks_b)
