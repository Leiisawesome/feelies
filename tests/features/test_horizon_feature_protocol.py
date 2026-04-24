"""Contract tests for the :class:`HorizonFeature` Protocol.

Phase-2-β ships the Protocol *only* — no concrete implementations
land in ``feelies/features/``.  These tests therefore validate two
things:

1.  A minimal in-test class that satisfies the Protocol shape passes
    ``isinstance(obj, HorizonFeature)`` (runtime-checkable).
2.  An object missing any required attribute / method is rejected.

Both checks pin the public surface of the contract so a Phase-3
horizon-feature implementation cannot accidentally rename a method
or omit ``feature_id`` / ``feature_version`` without breaking these
tests first.
"""

from __future__ import annotations

from typing import Any, Mapping

from feelies.core.events import HorizonTick, SensorReading
from feelies.features.protocol import HorizonFeature


class _GoodFeature:
    """Reference implementation that satisfies the Protocol."""

    feature_id: str = "good_feature"
    feature_version: str = "1.0.0"
    input_sensor_ids: tuple[str, ...] = ("ofi_ewma",)
    horizon_seconds: int = 30

    def initial_state(self) -> dict[str, Any]:
        return {"sum": 0.0, "count": 0, "received": False}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        if isinstance(reading.value, tuple):
            return
        state["sum"] += float(reading.value)
        state["count"] += 1
        state["received"] = True

    def finalize(
        self,
        tick: HorizonTick,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> tuple[float, bool, bool]:
        n = state["count"]
        value = state["sum"] / n if n > 0 else 0.0
        warm = n > 0
        stale = not state["received"]
        state["received"] = False
        return value, warm, stale


class _MissingMethod:
    """No ``finalize`` method — should fail the runtime check."""

    feature_id = "broken"
    feature_version = "0.0.1"
    input_sensor_ids: tuple[str, ...] = ()
    horizon_seconds = 30

    def initial_state(self) -> dict[str, Any]:
        return {}

    def observe(
        self,
        reading: SensorReading,
        state: dict[str, Any],
        params: Mapping[str, Any],
    ) -> None:
        return None


def test_good_feature_satisfies_protocol() -> None:
    feature: HorizonFeature = _GoodFeature()
    assert isinstance(feature, HorizonFeature)
    assert feature.feature_id == "good_feature"
    assert feature.feature_version == "1.0.0"
    assert feature.input_sensor_ids == ("ofi_ewma",)
    assert feature.horizon_seconds == 30


def test_initial_state_returns_independent_dicts() -> None:
    """Two calls to ``initial_state`` must return distinct dicts.

    The aggregator stores per-(feature, symbol) state mutably; if
    ``initial_state`` returned a shared dict the symbols would alias.
    """
    feature = _GoodFeature()
    a = feature.initial_state()
    b = feature.initial_state()
    a["sum"] = 999.0
    assert b["sum"] == 0.0


def test_finalize_returns_value_warm_stale_triple() -> None:
    feature = _GoodFeature()
    state = feature.initial_state()
    reading = SensorReading(
        timestamp_ns=1_000_000_000,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        value=2.5,
        warm=True,
    )
    feature.observe(reading, state, params={})
    tick = HorizonTick(
        timestamp_ns=1_030_000_000_000,
        correlation_id="t",
        sequence=1,
        horizon_seconds=30,
        boundary_index=1,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="TEST",
    )
    value, warm, stale = feature.finalize(tick, state, params={})
    assert value == 2.5
    assert warm is True
    assert stale is False


def test_finalize_resets_window_freshness_flag() -> None:
    """Calling ``finalize`` must let the next horizon detect staleness.

    The reference impl resets ``received`` inside ``finalize``; if a
    Phase-3 implementation forgets to do so, the second horizon would
    report ``stale=False`` even with no new readings — silently
    masking the staleness signal.
    """
    feature = _GoodFeature()
    state = feature.initial_state()
    reading = SensorReading(
        timestamp_ns=1_000_000_000,
        correlation_id="c",
        sequence=1,
        symbol="AAPL",
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        value=1.0,
        warm=True,
    )
    feature.observe(reading, state, params={})
    tick1 = HorizonTick(
        timestamp_ns=1_030_000_000_000,
        correlation_id="t1",
        sequence=1,
        horizon_seconds=30,
        boundary_index=1,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="TEST",
    )
    _, _, stale1 = feature.finalize(tick1, state, params={})
    assert stale1 is False

    tick2 = HorizonTick(
        timestamp_ns=1_060_000_000_000,
        correlation_id="t2",
        sequence=2,
        horizon_seconds=30,
        boundary_index=2,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="TEST",
    )
    _, _, stale2 = feature.finalize(tick2, state, params={})
    assert stale2 is True


def test_protocol_rejects_object_missing_finalize() -> None:
    obj = _MissingMethod()
    assert not isinstance(obj, HorizonFeature)


def test_protocol_rejects_plain_object() -> None:
    assert not isinstance(object(), HorizonFeature)
