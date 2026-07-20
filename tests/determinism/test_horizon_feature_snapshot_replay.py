"""Replay parity for full ``HorizonFeatureSnapshot`` content and ordering.

The short fixture keeps the windowed z-score cold, so this baseline also locks
the cold-path ``values``, ``warm``, and ``stale`` fields.
"""

from __future__ import annotations

import hashlib

from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature
from feelies.features.protocol import HorizonFeature
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.spec import SensorSpec
from tests.fixtures.replay import replay_through_aggregator


_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        params={"alpha": 0.1, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={},
        subscribes_to=(NBBOQuote,),
    ),
)

# Active features for the two sensors above across the three test horizons.
# Mirrors _horizon_features_for() in bootstrap.py:
#   ofi_ewma  → SensorPassthroughFeature + RollingZscoreFeature
#   micro_price → (none)
_HORIZONS = frozenset({30, 120, 300})
_HORIZON_FEATURES: tuple[HorizonFeature, ...] = tuple(
    feature
    for h in sorted(_HORIZONS)
    for feature in (
        SensorPassthroughFeature("ofi_ewma", h),
        HorizonWindowedFeature(
            "ofi_ewma",
            h,
            reducer="zscore",
            feature_id="ofi_ewma_zscore",
        ),
    )
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


# Locked snapshot stream from the active horizon-window aggregator.
EXPECTED_LEVEL3_SNAPSHOT_HASH = "251cc109c25a4c1124c3dab32b7168c09b6a9126f4092d977df08a740c59d04b"
EXPECTED_LEVEL3_SNAPSHOT_COUNT = 14


def _replay() -> tuple[str, int]:
    recorder = replay_through_aggregator(
        sensor_specs=_SENSOR_SPECS,
        horizon_features=_HORIZON_FEATURES,
    )
    return _hash_snapshot_stream(recorder.snapshots), len(recorder.snapshots)


def test_snapshot_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()

    # One snapshot per symbol, horizon, and boundary; cold readings remain stale.
    assert actual_count == EXPECTED_LEVEL3_SNAPSHOT_COUNT, (
        f"snapshot count drift: expected {EXPECTED_LEVEL3_SNAPSHOT_COUNT}, got {actual_count}"
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
