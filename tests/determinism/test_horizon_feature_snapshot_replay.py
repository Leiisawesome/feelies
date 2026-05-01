"""Level-3 baseline — ``HorizonFeatureSnapshot`` replay parity.

Phase 3.5 (commit df632ef) activated the :class:`HorizonAggregator`:
horizon features are now registered in production and each
:class:`HorizonFeatureSnapshot` carries non-empty ``values`` / ``warm`` /
``stale`` dicts.  The locked hash covers the full snapshot content
(scope, ordering, sequence allocation, *and* feature values) so any
drift in any of those dimensions surfaces immediately.

Features wired for the two sensors in this test:
  ofi_ewma → SensorPassthroughFeature (feature_id=``ofi_ewma``) +
             RollingZscoreFeature (feature_id=``ofi_ewma_zscore``)
  micro_price → (none)
across horizons {30, 120, 300}.

The synthetic fixture has fewer quotes than ``min_samples=30``, so
both ofi_ewma and ofi_ewma_zscore are always cold (warm=False) and
ofi_ewma_zscore always returns 0.0.  That is expected: the baseline
locks the cold-path field shape, not warm-path values.
"""

from __future__ import annotations

import hashlib

from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote
from feelies.features.impl.rolling_stats import RollingZscoreFeature
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature
from feelies.features.protocol import HorizonFeature
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.spec import SensorSpec
from tests.fixtures.replay import replay_through_aggregator


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
        RollingZscoreFeature("ofi_ewma", h),
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


def _replay() -> tuple[str, int]:
    recorder = replay_through_aggregator(
        sensor_specs=_SENSOR_SPECS,
        horizon_features=_HORIZON_FEATURES,
    )
    return _hash_snapshot_stream(recorder.snapshots), len(recorder.snapshots)


def test_snapshot_stream_matches_locked_baseline() -> None:
    actual_hash, actual_count = _replay()

    # Phase 3.5 re-lock: aggregator now carries active features so V/W/S
    # dicts are non-empty.  ofi_ewma is warm (warm_after=5); ofi_ewma_zscore
    # is cold (fixture < min_samples=30) and always returns 0.0.
    # H1 fix (audit): dedup logic now emits exactly one snapshot per
    # (symbol, horizon, boundary_index); SYMBOL+UNIVERSE ticks no longer
    # produce duplicate snapshots, halving the count from 28 → 14.
    EXPECTED_LEVEL3_SNAPSHOT_HASH = (
        "d03258eb3f077ad4d3ebaea697843e9226f251c9ece9800c1e672182e3aab8c7"
    )
    EXPECTED_LEVEL3_SNAPSHOT_COUNT = 14

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
