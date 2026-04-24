"""Level-3 baseline — ``HorizonFeatureSnapshot`` replay parity.

In Phase 2 the :class:`HorizonAggregator` ships in *passive-emitter*
mode: no horizon features are registered, so each
:class:`HorizonFeatureSnapshot` carries empty ``values`` / ``warm`` /
``stale`` dicts.  The other fields (sequence, symbol,
horizon_seconds, boundary_index, correlation_id, timestamp_ns) are
fully populated and form a stable Level-3 fingerprint.

Locking this baseline now means Phase 3 cannot accidentally change
snapshot scope expansion, ordering, or sequence allocation when it
starts attaching real horizon features — any drift there will
immediately surface as a failure here.
"""

from __future__ import annotations

import hashlib

from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.spec import SensorSpec
from tests.fixtures.replay import replay_through_aggregator


# Two simple sensors are enough to drive the aggregator: the
# Level-3 hash measures snapshot scope/ordering, not value content.
_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.0.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)


def _hash_snapshot_stream(snapshots: list[HorizonFeatureSnapshot]) -> str:
    lines: list[str] = []
    for s in snapshots:
        lines.append(
            f"{s.sequence}|{s.symbol}|{s.horizon_seconds}|"
            f"{s.boundary_index}|{s.timestamp_ns}|{s.correlation_id}|"
            f"V={sorted(s.values.items())}|"
            f"W={sorted(s.warm.items())}|"
            f"S={sorted(s.stale.items())}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _replay() -> tuple[str, int]:
    recorder = replay_through_aggregator(sensor_specs=_SENSOR_SPECS)
    return _hash_snapshot_stream(recorder.snapshots), len(recorder.snapshots)


def test_snapshot_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()

    EXPECTED_LEVEL3_SNAPSHOT_HASH = (
        "a853ab09b0f4d45bbfcaf0d52c24dc9931c9e3a045a4d9d82dd6d6a77080eb2c"
    )
    EXPECTED_LEVEL3_SNAPSHOT_COUNT = 28

    assert actual_count == EXPECTED_LEVEL3_SNAPSHOT_COUNT, (
        f"snapshot count drift: expected "
        f"{EXPECTED_LEVEL3_SNAPSHOT_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_LEVEL3_SNAPSHOT_HASH, (
        "Level-3 HorizonFeatureSnapshot hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL3_SNAPSHOT_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the constant in the same commit and "
        "justify in the commit message."
    )


def test_two_replays_produce_identical_snapshot_hash() -> None:
    """Sanity: replay determinism at the snapshot layer."""
    hash_a, _ = _replay()
    hash_b, _ = _replay()
    assert hash_a == hash_b
