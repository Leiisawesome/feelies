"""Combined v0.3 sensor replay determinism baseline (Phase 2.1).

Locks the bit-for-bit content and ordering of every ``SensorReading``
emitted when the canonical 5-minute synthetic fixture is replayed
through a fresh :class:`SensorRegistry` populated with the **four
v0.3 mechanism-fingerprint sensors**:

- ``hawkes_intensity``         (HAWKES_SELF_EXCITE family)
- ``scheduled_flow_window``    (SCHEDULED_FLOW family; calendar-driven)
- ``snr_drift_diffusion``      (cross-cutting SNR exploitability gate)
- ``structural_break_score``   (cross-cutting page-Hinkley diagnostic)

This baseline is *additive* to the Level-4 baseline in
``test_sensor_reading_replay.py``: the Phase-2-β baseline locks the
four simple sensors; this one locks the four v0.3 sensors.  Both must
remain green for Phase 2 + Phase 2.1 to ship together.

The v0.3 ``scheduled_flow_window`` sensor consumes the committed
``storage/reference/event_calendar/2026-03-24.yaml`` fixture, so this
test also implicitly exercises the calendar adapter's hash stability.

Re-baseline protocol matches ``test_sensor_reading_replay.py``:
print-on-fail, then update the constant in the same commit.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.impl.hawkes_intensity import HawkesIntensitySensor
from feelies.sensors.impl.scheduled_flow_window import ScheduledFlowWindowSensor
from feelies.sensors.impl.snr_drift_diffusion import SNRDriftDiffusionSensor
from feelies.sensors.impl.structural_break_score import (
    StructuralBreakScoreSensor,
)
from feelies.sensors.spec import SensorSpec
from feelies.storage.reference.event_calendar import (
    CalendarWindow,
    EventCalendar,
    WindowKind,
)
from tests.fixtures.event_logs._generate import SESSION_OPEN_NS
from tests.fixtures.replay import replay_through_registry


# ── Synthetic calendar pinned to the fixture's session_open_ns ─────


def _build_test_calendar() -> EventCalendar:
    """A scheduled-flow window covering minute 1-2 of the fixture.

    The fixture starts at SESSION_OPEN_NS and runs for ~5 minutes;
    placing one window inside that span guarantees the
    ``scheduled_flow_window`` sensor emits both inactive and active
    classifications in the locked stream.
    """
    return EventCalendar(
        session_date=date(2026, 3, 24),
        windows=(
            CalendarWindow(
                window_id="synthetic_flow_window",
                kind=WindowKind.OPENING_AUCTION,
                symbol=None,
                start_ns=SESSION_OPEN_NS + 60 * 1_000_000_000,
                end_ns=SESSION_OPEN_NS + 120 * 1_000_000_000,
                flow_direction_prior=0.0,
            ),
        ),
    )


_TEST_CALENDAR = _build_test_calendar()


_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="hawkes_intensity",
        sensor_version="1.0.0",
        cls=HawkesIntensitySensor,
        params={
            "alpha": 0.4,
            "beta": 0.05,
            "warm_window_seconds": 60,
            "warm_trades_per_side": 5,
        },
        subscribes_to=(Trade,),
    ),
    SensorSpec(
        sensor_id="scheduled_flow_window",
        sensor_version="1.0.0",
        cls=ScheduledFlowWindowSensor,
        params={"calendar": _TEST_CALENDAR},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="snr_drift_diffusion",
        sensor_version="1.0.0",
        cls=SNRDriftDiffusionSensor,
        params={
            "horizons_seconds": (30, 120),
            "ewma_n_eff": 16,
            "warm_samples_per_horizon": 4,
        },
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="structural_break_score",
        sensor_version="1.0.0",
        cls=StructuralBreakScoreSensor,
        params={
            "window_seconds": 60,
            "alarm_threshold": 0.001,
            "warm_samples": 10,
        },
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


def _replay() -> tuple[str, int]:
    recorder = replay_through_registry(sensor_specs=_SENSOR_SPECS)
    readings = recorder.sensor_readings
    return _hash_reading_stream(readings), len(readings)


def test_v03_sensor_reading_stream_matches_locked_baseline() -> None:
    """Locks SHA-256 + count of the v0.3 SensorReading stream."""
    actual_hash, actual_count = _replay()

    EXPECTED_V03_READING_HASH = (
        "f16b189ce987a1300b393d8713f377a7d34133f609e4685914ebe69c3553c3b3"
    )
    EXPECTED_V03_READING_COUNT = 9428

    assert actual_count == EXPECTED_V03_READING_COUNT, (
        f"v0.3 reading count drift: expected {EXPECTED_V03_READING_COUNT}, "
        f"got {actual_count}"
    )
    assert actual_hash == EXPECTED_V03_READING_HASH, (
        "v0.3 SensorReading hash drift!\n"
        f"  Expected: {EXPECTED_V03_READING_HASH}\n"
        f"  Actual:   {actual_hash}\n"
        "If intentional, update the constant in the same commit and "
        "justify in the commit message."
    )


def test_two_replays_produce_identical_v03_hash() -> None:
    """Sanity: replay determinism at the v0.3 SensorReading layer."""
    hash_a, _ = _replay()
    hash_b, _ = _replay()
    assert hash_a == hash_b


def test_calendar_hash_is_stable_across_constructions() -> None:
    """Sanity: the test calendar's hash is itself deterministic.

    If this fails, the v0.3 SensorReading hash will fail too because
    the calendar's identity flows into ``scheduled_flow_window`` reads.
    Diagnosing here first saves a confusing debug session at the
    Level-4 baseline failure.
    """
    cal_a = _build_test_calendar()
    cal_b = _build_test_calendar()
    assert cal_a.hash() == cal_b.hash()


def test_reference_calendar_path_exists() -> None:
    """Belt-and-suspenders: the committed reference calendar is present."""
    path = (
        Path(__file__).resolve().parents[2]
        / "storage" / "reference" / "event_calendar" / "2026-03-24.yaml"
    )
    assert path.is_file(), f"reference calendar missing: {path}"
