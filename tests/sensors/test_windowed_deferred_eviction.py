"""Deferred window eviction: capture cost and boundary reductions.

T1 is structural and fail-first on the copy path. T2-T4 are characterisations
of the reduction over ``[T-W, T]``. A salt returns None when the scenario the
assertion needs did not occur, True when the property held, and False when it
was violated. At least 8 of 32 salts must be non-vacuous.
"""

from __future__ import annotations

import copy
import tracemalloc
from collections import deque
from collections.abc import Callable

from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    BoundaryStateStore,
    HorizonFeatureSnapshot,
    HorizonTick,
    SensorReading,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature

_NS = 1_000_000_000
_HORIZON = 30
_SALT_COUNT = 32
_SALT_FLOOR = 8
_SYMBOL = "AAPL"
_FEATURE = "win_sum"

_Salt = Callable[[int], bool | None]


def _reading(ts_ns: int, value: float) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id=f"r-{ts_ns}",
        sequence=ts_ns,
        symbol=_SYMBOL,
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        value=value,
        warm=True,
    )


def _tick(boundary: int, boundary_ts: int, trigger_ts: int) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=trigger_ts,
        correlation_id=f"t-{boundary}-{boundary_ts}",
        sequence=boundary,
        horizon_seconds=_HORIZON,
        boundary_index=boundary,
        scope="SYMBOL",
        boundary_timestamp_ns=boundary_ts,
        symbol=_SYMBOL,
        session_id="TEST",
    )


def _aggregator(*, max_samples: int) -> tuple[HorizonAggregator, BoundaryStateStore]:
    store = BoundaryStateStore()
    feature = HorizonWindowedFeature(
        "ofi_ewma",
        _HORIZON,
        reducer="sum",
        feature_id=_FEATURE,
        min_samples=1,
        max_samples=max_samples,
    )
    agg = HorizonAggregator(
        bus=EventBus(),
        horizon_features=(feature,),
        symbols=frozenset({_SYMBOL}),
        sensor_buffer_seconds=600,
        sequence_generator=SequenceGenerator(),
        boundary_state=store,
    )
    return agg, store


def _traced_peak(action: Callable[[], None]) -> int:
    tracemalloc.start()
    try:
        tracemalloc.clear_traces()
        tracemalloc.reset_peak()
        action()
        _current, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


def _capture_peak(n: int) -> int:
    """Bytes traced while one pending-boundary reading is applied."""
    agg, store = _aggregator(max_samples=n + 8)
    for i in range(n):
        agg.on_sensor_reading(_reading(i + 1, float(i)))
    store.begin_event(_SYMBOL, ((_HORIZON, 1, 10**18),), {})

    def apply() -> None:
        agg.on_sensor_reading(_reading(n + 2, 0.0))

    return _traced_peak(apply)


def _deque_copy_peak(n: int) -> int:
    """Same tracer on a helper that copies a deque of ``n`` samples."""
    window: deque[tuple[int, float]] = deque((i, float(i)) for i in range(n))
    held: list[deque[tuple[int, float]]] = []

    def apply() -> None:
        held.append(copy.deepcopy(window))

    return _traced_peak(apply)


def _batch_sum(samples: list[tuple[int, float]], boundary: int) -> float:
    window_ns = _HORIZON * _NS
    values = [value for ts, value in samples if boundary - window_ns <= ts <= boundary]
    n = len(values)
    if n == 0:
        return 0.0
    return (sum(values) / n) * n


def _finalize(
    samples: list[tuple[int, float]],
    keys: tuple[tuple[int, int, int], ...],
    later: list[tuple[int, float]],
    ticks: list[HorizonTick],
) -> list[HorizonFeatureSnapshot]:
    agg, store = _aggregator(max_samples=50_000)
    for ts, value in samples:
        agg.on_sensor_reading(_reading(ts, value))
    store.begin_event(_SYMBOL, keys, {})
    for ts, value in later:
        agg.on_sensor_reading(_reading(ts, value))
    snaps: list[HorizonFeatureSnapshot] = []
    for tick in ticks:
        snaps.extend(agg.on_horizon_tick(tick))
    return snaps


def _value(snap: HorizonFeatureSnapshot) -> float:
    assert _FEATURE in snap.values, f"feature missing from {snap.values!r}"
    return snap.values[_FEATURE]


def _over_salts(scenario: _Salt) -> tuple[int, int]:
    """Return ``(precondition misses, non-vacuous holds)``.

    A property violation fails immediately. Fewer than 8 non-vacuous salts
    fails as a precondition miss.
    """
    missed = 0
    held = 0
    for salt in range(_SALT_COUNT):
        outcome = scenario(salt)
        if outcome is False:
            raise AssertionError(f"PROPERTY: violated at salt {salt}")
        if outcome is None:
            missed += 1
        else:
            held += 1
    if held < _SALT_FLOOR:
        raise AssertionError(f"PRECONDITION: held on {held} of {_SALT_COUNT} salts")
    return missed, held


def _t2_scenario(salt: int) -> bool | None:
    window_ns = _HORIZON * _NS
    boundary = 200 * _NS
    samples = [
        (boundary - window_ns - 1, 7.0),
        (boundary - window_ns, 3.0),
        (boundary - window_ns + 1, 4.0 + float(salt)),
        (boundary - window_ns // 2, 5.0),
        (boundary, 11.0),
    ]
    # Every salt is far enough that eager eviction at the later timestamp
    # would drop a sample the closed window still includes.
    later_ts = boundary + (salt + 1) * _NS
    eager_cutoff = later_ts - window_ns
    protected = [
        value
        for ts, value in samples
        if boundary - window_ns <= ts <= boundary and ts < eager_cutoff
    ]
    if not protected:
        return None
    later = [(later_ts, 99.0), (later_ts + window_ns, 98.0)]
    snaps = _finalize(
        samples,
        ((_HORIZON, 1, boundary),),
        later,
        [_tick(1, boundary, later[-1][0])],
    )
    if len(snaps) != 1:
        return False
    return _value(snaps[0]) == _batch_sum(samples, boundary)


def _t3_scenario(salt: int) -> bool | None:
    window_ns = _HORIZON * _NS
    first = 200 * _NS
    # The first eight salts are not two ordered boundaries.
    if salt < 8:
        return None
    second = first + (salt - 7) * _NS
    only_first = first - window_ns + 1
    shared = second - window_ns
    if shared > first or not (first - window_ns <= only_first < shared):
        return None
    # History ends at T1. Observing a reading at T2 would already have
    # evicted only_first before either boundary was claimed.
    samples = [
        (only_first, 2.0 + float(salt)),
        (shared, 6.0),
        (first, 8.0),
    ]
    own_ts = second + window_ns
    snaps = _finalize(
        samples,
        ((_HORIZON, 1, first), (_HORIZON, 2, second)),
        [(own_ts, 50.0)],
        [_tick(1, first, own_ts), _tick(2, second, own_ts)],
    )
    if len(snaps) != 2:
        return False
    return _value(snaps[0]) == _batch_sum(samples, first) and _value(snaps[1]) == _batch_sum(
        samples, second
    )


def _t4_scenario(salt: int) -> bool | None:
    window_ns = _HORIZON * _NS
    boundary = 80 * _NS
    left = boundary - window_ns
    right = boundary
    # Every salt places both edges. The salt only moves an interior sample.
    samples = [
        (left - 1, 1.0),
        (left, 3.0 + float(salt)),
        (left + 1 + salt, 4.0),
        (right, 5.0),
    ]
    edges = {ts for ts, _value in samples if ts in (left, right)}
    if edges != {left, right}:
        return None
    feature = HorizonWindowedFeature(
        "ofi_ewma",
        _HORIZON,
        reducer="sum",
        feature_id=_FEATURE,
        min_samples=1,
        max_samples=50_000,
    )
    state = feature.initial_state()
    for ts, value in samples:
        feature.observe(_reading(ts, value), state, {})
    # Present in the deque, past the boundary. Finalize must leave it out.
    state["win"].append((right + 1, 99.0))
    value, warm, _stale = feature.finalize(_tick(1, boundary, right), state, {})
    if not warm:
        return False
    return value == _batch_sum(samples, boundary)


def test_t1_boundary_capture_allocation_does_not_scale_with_window() -> None:
    """One boundary capture at 4N versus N stays under 1.5; a deque copy does not."""
    small = 20_000
    large = 4 * small
    copy_ratio = _deque_copy_peak(large) / _deque_copy_peak(small)
    assert copy_ratio > 3.0, f"negative control ratio {copy_ratio}"
    capture_ratio = _capture_peak(large) / _capture_peak(small)
    assert capture_ratio < 1.5, f"boundary capture ratio {capture_ratio}"


def test_t2_finalize_matches_batch_after_later_events() -> None:
    missed, held = _over_salts(_t2_scenario)
    assert missed == 0
    assert held == 32


def test_t3_two_pending_boundaries_keep_the_earlier_window() -> None:
    missed, held = _over_salts(_t3_scenario)
    assert missed == 8
    assert held == 24


def test_t4_closed_window_includes_both_edges() -> None:
    missed, held = _over_salts(_t4_scenario)
    assert missed == 0
    assert held == 32
