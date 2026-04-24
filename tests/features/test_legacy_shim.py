"""Unit tests for :class:`feelies.features.legacy_shim.LegacyFeatureShim`.

The shim's job is to wrap a legacy :class:`FeatureDefinition` so it
can be plugged into the new :class:`HorizonAggregator` as a
:class:`HorizonFeature`.  Phase-2 leaves the shim inactive in the
default bootstrap, but it must still satisfy the protocol contract
and behave correctly when exercised directly so Phase-3 can adopt it
without surprises.
"""

from __future__ import annotations

from typing import Any

import pytest

from feelies.core.events import HorizonTick, NBBOQuote, SensorReading, Trade
from feelies.features.definition import FeatureComputation, FeatureDefinition
from feelies.features.legacy_shim import LegacyFeatureShim
from feelies.features.protocol import HorizonFeature


class _DummyComputation:
    """Trivial legacy computation — only its identity matters here.

    The shim does not invoke ``update`` / ``update_trade`` (Phase-3
    will), so a minimal placeholder is sufficient for these tests.
    """

    def update(self, quote: NBBOQuote, state: dict[str, Any]) -> float:
        return 0.0

    def initial_state(self) -> dict[str, Any]:
        return {}

    def update_trade(
        self, trade: Trade, state: dict[str, Any]
    ) -> float | None:
        return None


def _definition(*, feature_id: str = "fake_feat", version: str = "1.2.3") -> FeatureDefinition:
    comp: FeatureComputation = _DummyComputation()
    return FeatureDefinition(
        feature_id=feature_id,
        version=version,
        description="dummy",
        compute=comp,
    )


def _reading(
    *,
    ts_ns: int,
    value: float | tuple[float, ...] = 1.5,
    warm: bool = True,
    sensor_id: str = "micro_price",
) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id=f"r-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        sensor_id=sensor_id,
        sensor_version="1.0.0",
        value=value,
        warm=warm,
    )


def _tick(*, boundary: int, ts_ns: int, horizon: int = 30) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{horizon}-SYMBOL-{boundary}",
        sequence=boundary + 1,
        horizon_seconds=horizon,
        boundary_index=boundary,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="TEST",
    )


def test_shim_satisfies_horizon_feature_protocol() -> None:
    shim = LegacyFeatureShim(
        definition=_definition(),
        sensor_id="micro_price",
        horizon_seconds=30,
    )
    assert isinstance(shim, HorizonFeature)


def test_shim_mirrors_definition_identity() -> None:
    shim = LegacyFeatureShim(
        definition=_definition(feature_id="ofi", version="2.0.0"),
        sensor_id="ofi_ewma",
        horizon_seconds=120,
    )
    assert shim.feature_id == "ofi"
    assert shim.feature_version == "2.0.0"
    assert shim.input_sensor_ids == ("ofi_ewma",)
    assert shim.horizon_seconds == 120


def test_invalid_horizon_rejected() -> None:
    with pytest.raises(ValueError, match="horizon_seconds"):
        LegacyFeatureShim(
            definition=_definition(),
            sensor_id="x",
            horizon_seconds=0,
        )


def test_finalize_without_observations_returns_zero_warm_false_stale_true() -> None:
    shim = LegacyFeatureShim(
        definition=_definition(),
        sensor_id="micro_price",
        horizon_seconds=30,
    )
    state = shim.initial_state()
    value, warm, stale = shim.finalize(
        _tick(boundary=1, ts_ns=1_030_000_000_000),
        state,
        params={},
    )
    assert value == 0.0
    assert warm is False
    assert stale is True


def test_observe_then_finalize_returns_last_value_warm_not_stale() -> None:
    shim = LegacyFeatureShim(
        definition=_definition(),
        sensor_id="micro_price",
        horizon_seconds=30,
    )
    state = shim.initial_state()
    shim.observe(_reading(ts_ns=1_001_000_000, value=5.5), state, params={})
    value, warm, stale = shim.finalize(
        _tick(boundary=1, ts_ns=1_030_000_000_000),
        state,
        params={},
    )
    assert value == 5.5
    assert warm is True
    assert stale is False


def test_subsequent_horizon_without_new_reading_is_stale() -> None:
    shim = LegacyFeatureShim(
        definition=_definition(),
        sensor_id="micro_price",
        horizon_seconds=30,
    )
    state = shim.initial_state()
    shim.observe(_reading(ts_ns=1_001_000_000, value=2.0), state, params={})
    _, _, stale1 = shim.finalize(
        _tick(boundary=1, ts_ns=1_030_000_000_000), state, params={},
    )
    assert stale1 is False
    value2, warm2, stale2 = shim.finalize(
        _tick(boundary=2, ts_ns=1_060_000_000_000), state, params={},
    )
    assert warm2 is True  # last value still available
    assert stale2 is True  # no fresh reading in this window
    assert value2 == 2.0


def test_non_warm_reading_does_not_clear_staleness() -> None:
    """A non-warm reading must not be counted as a 'fresh' reading.

    The shim treats upstream warmth as a hard floor: if the reading is
    unreliable, finalize should still report stale=True for the window.
    """
    shim = LegacyFeatureShim(
        definition=_definition(),
        sensor_id="micro_price",
        horizon_seconds=30,
    )
    state = shim.initial_state()
    shim.observe(
        _reading(ts_ns=1_001_000_000, value=4.0, warm=False),
        state,
        params={},
    )
    _, _, stale = shim.finalize(
        _tick(boundary=1, ts_ns=1_030_000_000_000), state, params={},
    )
    assert stale is True


def test_tuple_value_uses_first_component() -> None:
    """Multi-output sensors collapse to their first component via the shim."""
    shim = LegacyFeatureShim(
        definition=_definition(),
        sensor_id="micro_price",
        horizon_seconds=30,
    )
    state = shim.initial_state()
    shim.observe(
        _reading(ts_ns=1_001_000_000, value=(7.0, 99.0)),
        state,
        params={},
    )
    value, _, _ = shim.finalize(
        _tick(boundary=1, ts_ns=1_030_000_000_000), state, params={},
    )
    assert value == 7.0


def test_computation_property_returns_wrapped_compute() -> None:
    definition = _definition()
    shim = LegacyFeatureShim(
        definition=definition,
        sensor_id="micro_price",
        horizon_seconds=30,
    )
    assert shim.computation is definition.compute
