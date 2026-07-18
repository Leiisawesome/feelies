"""Inv-6 no-lookahead tests for the ``sig_dislocation_lambda_drift_v1``
consumed-feature set (Task 9 commit 4; impl plan §2.2).

Two perturbations, targeting this card's exact h=300 features through
the REAL ``SensorRegistry → HorizonScheduler → HorizonAggregator``
stack (reference ``platform.yaml`` sensor params):

* **truncation property (Hypothesis):** for generated quote/trade
  tapes, the h=300 snapshot at boundary T is bit-identical between the
  tape truncated at T and the full tape — every reading and every one
  of the four consumed feature values at T is a function only of
  events with ``timestamp_ns <= T``;
* **out-of-order future reading:** a post-T reading fed to the
  aggregator *before* the boundary tick at T must not enter the
  snapshot at T (the ``TestHorizonAggregationAntiLookahead``
  perturbation, instantiated on ``kyle_lambda_60s_percentile`` /
  ``micro_price_drift`` instead of the synthetic feature).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feelies.bootstrap import _horizon_features_for
from feelies.bus.event_bus import EventBus
from feelies.core.events import (
    HorizonFeatureSnapshot,
    HorizonTick,
    NBBOQuote,
    SensorReading,
    Trade,
)
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor
from feelies.sensors.impl.micro_price import MicroPriceSensor
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec

pytestmark = pytest.mark.backtest_validation

_NS = 1_000_000_000
_H = 300
_SYM = "APP"
_T_NS = 600 * _NS  # truncation cutoff == the audited boundary

_CONSUMED_IDS = (
    "micro_price",
    "micro_price_drift",
    "kyle_lambda_60s_percentile",
    "realized_vol_30s_zscore",
)

_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 30, "alignment": "causal", "sensor_version": "2.0.0"},
        subscribes_to=(NBBOQuote, Trade),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={"warm_after": 1, "warm_window_seconds": 60},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 16},
        subscribes_to=(NBBOQuote,),
    ),
)


def _quote(ts_ns: int, mid: float) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol=_SYM,
        bid=Decimal(str(round(mid - 0.05, 6))),
        ask=Decimal(str(round(mid + 0.05, 6))),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts_ns,
    )


def _trade(ts_ns: int, price: float, size: int) -> Trade:
    return Trade(
        timestamp_ns=ts_ns,
        correlation_id=f"t-{ts_ns}",
        sequence=ts_ns,
        symbol=_SYM,
        price=Decimal(str(round(price, 6))),
        size=size,
        exchange_timestamp_ns=ts_ns,
    )


def _replay(events: list[NBBOQuote | Trade]) -> list[HorizonFeatureSnapshot]:
    bus = EventBus()
    snaps: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, snaps.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({_SYM}),
    )
    for spec in _SENSOR_SPECS:
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_H}),
        session_id="H8CAUSAL",
        symbols=frozenset({_SYM}),
        session_open_ns=0,
        sequence_generator=SequenceGenerator(),
    )
    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({_SYM}),
        sensor_buffer_seconds=2 * _H,
        sequence_generator=SequenceGenerator(),
        horizon_features=[
            f
            for sid in ("kyle_lambda_60s", "micro_price", "realized_vol_30s")
            for f in _horizon_features_for(sid, _H)
        ],
    )
    aggregator.attach()
    for ev in events:
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)
    return snaps


def _fingerprint(snap: HorizonFeatureSnapshot) -> tuple[object, ...]:
    """Bit-comparable content of one snapshot (values / warm / stale)."""
    return (
        snap.boundary_ts_ns,
        tuple(sorted(snap.values.items())),
        tuple(sorted(snap.warm.items())),
        tuple(sorted(snap.stale.items())),
    )


# ── Truncation property (Hypothesis) ──────────────────────────────────────

# One slot per 5 s over [0, 655]: a mid step and an optional trade.
_SLOT = st.tuples(
    st.sampled_from([-0.05, -0.02, 0.0, 0.01, 0.03]),
    st.one_of(st.none(), st.integers(min_value=10, max_value=200)),
)


def _build_tape(slots: list[tuple[float, int | None]]) -> list[NBBOQuote | Trade]:
    events: list[NBBOQuote | Trade] = []
    mid = 544.0
    for i, (step, size) in enumerate(slots):
        t = 5 * i
        mid += step
        events.append(_quote(t * _NS, mid))
        if size is not None:
            events.append(_trade((t + 2) * _NS, mid + step, size))
    return events


@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(slots=st.lists(_SLOT, min_size=132, max_size=132))
def test_truncation_property_snapshot_at_t_ignores_the_future(
    slots: list[tuple[float, int | None]],
) -> None:
    """Snapshots at boundaries <= T are bit-identical between the tape
    truncated at T and the full tape — Inv-6 for the whole consumed set.

    Slot 120 always lands a quote at exactly T = 600 s, so the T
    boundary tick fires in both runs; the full tape continues to 655 s.
    """
    full = _build_tape(slots)
    truncated = [ev for ev in full if ev.timestamp_ns <= _T_NS]

    snaps_full = {s.boundary_ts_ns: s for s in _replay(full) if s.boundary_ts_ns <= _T_NS}
    snaps_trunc = {s.boundary_ts_ns: s for s in _replay(truncated)}

    assert _T_NS in snaps_trunc, "boundary tick at T must fire on the truncated tape"
    assert set(snaps_trunc) == set(snaps_full)
    for boundary_ns, snap in snaps_trunc.items():
        assert _fingerprint(snap) == _fingerprint(snaps_full[boundary_ns])


# ── Out-of-order future reading (aggregator-level, real features) ─────────


def _kyle_micro_features() -> list[object]:
    return [
        f for sid in ("kyle_lambda_60s", "micro_price") for f in _horizon_features_for(sid, _H)
    ]


def _reading(*, ts_ns: int, sensor_id: str, value: float) -> SensorReading:
    return SensorReading(
        timestamp_ns=ts_ns,
        correlation_id=f"r-{ts_ns}",
        sequence=ts_ns,
        symbol=_SYM,
        sensor_id=sensor_id,
        sensor_version="test",
        value=value,
        warm=True,
    )


def _boundary_tick(*, boundary: int, ts_ns: int) -> HorizonTick:
    return HorizonTick(
        timestamp_ns=ts_ns,
        correlation_id=f"tick-{boundary}",
        sequence=boundary,
        horizon_seconds=_H,
        boundary_index=boundary,
        scope="SYMBOL",
        boundary_timestamp_ns=ts_ns,
        symbol=_SYM,
        session_id="H8CAUSAL",
    )


def _aggregator() -> HorizonAggregator:
    return HorizonAggregator(
        bus=EventBus(),
        horizon_features=_kyle_micro_features(),
        symbols=frozenset({_SYM}),
        sensor_buffer_seconds=2 * _H,
        sequence_generator=SequenceGenerator(),
    )


def _feed_baseline(agg: HorizonAggregator) -> None:
    # 40 warm readings each inside [0, T]: percentile and delta windows
    # comfortably clear min_samples=20.
    for k in range(40):
        ts = (5 + 7 * k) * _NS
        agg.on_sensor_reading(_reading(ts_ns=ts, sensor_id="kyle_lambda_60s", value=1e-4 * k))
        agg.on_sensor_reading(_reading(ts_ns=ts, sensor_id="micro_price", value=544.0 + 0.01 * k))


def test_out_of_order_future_reading_does_not_enter_snapshot_at_t() -> None:
    """A post-T reading observed before the boundary tick at T must not
    change ``kyle_lambda_60s_percentile`` / ``micro_price_drift`` at T.

    What this certifies is ``HorizonWindowedFeature.finalize``'s
    live-subset defense on the REAL reducers: when the window contains
    readings stamped after ``asof``, rank / latest / oldest are
    recomputed over the ``ts <= asof`` subset only, so the future VALUE
    cannot enter the boundary snapshot.

    Boundary of that defense, found while writing this test and
    disclosed here rather than hidden by construction: ``observe()``
    evicts at ``reading.ts − window``, so a future-stamped reading
    deeper than ``oldest_in_window_ts + window`` narrows the window
    (shifting the percentile denominator), and passthrough features
    (``micro_price``) overwrite ``state["value"]`` with no finalize
    defense at all.  That class is undefendable at the aggregator (the
    ``test_anti_lookahead.py`` model test says exactly this) — the
    platform's Inv-6 guarantee for out-of-order input is UPSTREAM:
    ``InMemoryEventLog`` / ``ReplayFeed`` raise ``CausalityViolation``
    on non-monotonic event order (``TestIngestionCausality``), so a
    future-stamped reading can never be fed before the boundary tick
    in production.  The perturbation below sits inside the defended
    envelope (ts = 305 s evicts nothing: the oldest baseline reading
    is at 5 s = 305 − 300).
    """
    tick = _boundary_tick(boundary=1, ts_ns=_H * _NS)

    agg_baseline = _aggregator()
    _feed_baseline(agg_baseline)
    snap_baseline = agg_baseline.on_horizon_tick(tick)[0]

    agg_perturbed = _aggregator()
    _feed_baseline(agg_perturbed)
    # Out-of-order arrival: readings stamped AFTER the boundary, fed in
    # before the tick.  An extreme value makes any leak loud in both the
    # percentile rank and the window delta.
    agg_perturbed.on_sensor_reading(
        _reading(ts_ns=305 * _NS, sensor_id="kyle_lambda_60s", value=999.0)
    )
    agg_perturbed.on_sensor_reading(
        _reading(ts_ns=305 * _NS, sensor_id="micro_price", value=999_999.0)
    )
    snap_perturbed = agg_perturbed.on_horizon_tick(tick)[0]

    assert snap_baseline.warm.get("kyle_lambda_60s_percentile") is True
    assert snap_baseline.warm.get("micro_price_drift") is True
    assert (
        snap_perturbed.values["kyle_lambda_60s_percentile"]
        == (snap_baseline.values["kyle_lambda_60s_percentile"])
    )
    assert (
        snap_perturbed.values["micro_price_drift"] == (snap_baseline.values["micro_price_drift"])
    )
