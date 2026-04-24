"""Level-2 baseline — HorizonTick replay parity over the synth fixture.

Replays the canonical 5-minute synthetic fixture
(``tests/fixtures/event_logs/synth_5min_aapl.jsonl``) through a
fresh ``HorizonScheduler`` and asserts the SHA-256 hash of the
emitted ``HorizonTick`` stream matches a recorded baseline.

Adding a Level-2 hash here locks the **scheduler** layer's output
even though Phase-2-α has no consumers — once Phase-2-β/γ start
deriving features from these ticks, any change here would silently
shift downstream baselines.  Catching the drift at this layer is
faster than diagnosing it at Level-3 / Level-4.

Updating the baseline
---------------------

If you intentionally change the scheduler's emission semantics
(boundary math, ordering, correlation_id format, sequence
allocation, etc.) the test will fail with the new hash printed.
Copy it into ``EXPECTED_LEVEL2_TICK_HASH`` below in the same commit
and justify in the commit message.

The fixture itself can be regenerated with::

    PYTHONHASHSEED=0 python -m tests.fixtures.event_logs._generate

After regenerating the fixture you will *also* need to re-baseline
this hash (the scheduler output changes when its input changes).
"""

from __future__ import annotations

from tests.fixtures.replay import (
    hash_horizon_tick_stream,
    replay_quotes_through_scheduler,
)


# Locked baseline produced by the canonical fixture + scheduler at the
# Phase-2-α tip.  Any unintentional drift in scheduler semantics or
# fixture content will flip this value.
EXPECTED_LEVEL2_TICK_HASH = (
    "316765d45725f91373da2dfa6a5e201f6349bdae566980b20b220c481b9793c2"
)
EXPECTED_LEVEL2_TICK_COUNT = 28


def test_horizon_tick_stream_matches_locked_baseline() -> None:
    ticks, _ = replay_quotes_through_scheduler()
    actual_hash = hash_horizon_tick_stream(ticks)
    assert len(ticks) == EXPECTED_LEVEL2_TICK_COUNT, (
        f"emitted-tick count drift: expected "
        f"{EXPECTED_LEVEL2_TICK_COUNT}, got {len(ticks)}"
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
