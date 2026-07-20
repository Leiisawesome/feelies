"""Replay parity for the four core sensor streams.

The baseline pins values and ordering for OFI EWMA, micro-price, spread z-score,
and realized volatility over the canonical five-minute fixture.
"""

from __future__ import annotations

import hashlib
from typing import Any

from feelies.core.events import NBBOQuote
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec
from tests.fixtures.replay import replay_through_registry


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
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        params={"window": 30, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 5},
        subscribes_to=(NBBOQuote,),
    ),
)


def _hash_reading_stream(recorder_readings: list[Any]) -> str:
    """SHA-256 over the canonical line-per-reading representation."""
    lines: list[str] = []
    for r in recorder_readings:
        if isinstance(r.value, tuple):
            value_repr = ",".join(repr(float(v)) for v in r.value)
        else:
            value_repr = repr(float(r.value))
        lines.append(
            f"{r.sequence}|{r.sensor_id}|{r.sensor_version}|{r.symbol}|"
            f"{value_repr}|{int(r.warm)}|{r.timestamp_ns}|{r.correlation_id}"
        )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# Locked Level-1 SensorReading baseline (canonical synth fixture).
EXPECTED_LEVEL4_READING_HASH = "1cb37e110cacd693b0c0e14a4ce99cb87169848a1e9ceb5c273ba4f974f27152"
EXPECTED_LEVEL4_READING_COUNT = 12_000


def _replay() -> tuple[str, int]:
    recorder = replay_through_registry(sensor_specs=_SENSOR_SPECS)
    readings = recorder.sensor_readings
    return _hash_reading_stream(readings), len(readings)


# ── Locked baseline (auto-bake on first run, then locked) ──────────


def test_sensor_reading_stream_matches_locked_baseline() -> None:
    """Locks the SHA-256 hash + count of the SensorReading stream.

    The first run on a fresh repo will print the baseline values; copy
    them into the constants below and re-run.  Subsequent unintended
    drift will then fail with the diff.
    """
    actual_hash, actual_count = _replay()

    assert actual_count == EXPECTED_LEVEL4_READING_COUNT, (
        f"reading count drift: expected {EXPECTED_LEVEL4_READING_COUNT}, got {actual_count}"
    )
    assert actual_hash == EXPECTED_LEVEL4_READING_HASH, (
        "Level-4 SensorReading hash drift!\n"
        f"  Expected: {EXPECTED_LEVEL4_READING_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the constant in the same commit and "
        "justify in the commit message."
    )


def test_two_replays_produce_identical_reading_hash() -> None:
    """Sanity: replay determinism at the SensorReading layer."""
    hash_a, _ = _replay()
    hash_b, _ = _replay()
    assert hash_a == hash_b
