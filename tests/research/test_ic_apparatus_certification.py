"""ENG-3: known-answer certification of the measurement apparatus.

The IC *statistics* are certified in ``test_forward_ic.py`` (rho=±1, ties, NaN
drops).  This test certifies the **apparatus** end-to-end: a deterministic tape
is replayed through the *real production* path
``SensorRegistry → HorizonScheduler → HorizonAggregator`` and the warm boundary
feature values are paired with forward returns exactly as the IC harness does
(``forward_ic.forward_return_at``).  We assert closed-form known answers so any
pairing error — off-by-one, wrong timestamp anchor, look-ahead, aggregation bug
— is caught.

This is the precondition for trusting any IC the harness produces, i.e. the gate
that lets the platform move from engine work to gas (sensor/feature) selection.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from feelies.bus.event_bus import EventBus
from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote, SensorReading, Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature
from feelies.research.forward_ic import forward_return_at, spearman_ic
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec

_NS = 1_000_000_000
_H = 30  # horizon seconds


class _RampSensor:
    """Deterministic reference sensor: emits the running quote count (1,2,3,…).

    Warm immediately, no windowing — so the boundary passthrough value is a
    closed-form function of how many quotes have arrived at/before the boundary.
    """

    sensor_id = "ramp"
    sensor_version = "1.0.0"

    def initial_state(self) -> dict[str, Any]:
        return {"n": 0}

    def update(
        self, event: NBBOQuote | Trade, state: dict[str, Any], params: Mapping[str, Any]
    ) -> SensorReading | None:
        if not isinstance(event, NBBOQuote):
            return None
        state["n"] += 1
        return SensorReading(
            timestamp_ns=event.timestamp_ns,
            correlation_id="placeholder",
            sequence=-1,
            symbol=event.symbol,
            sensor_id=self.sensor_id,
            sensor_version=self.sensor_version,
            value=float(state["n"]),
            warm=True,
        )


def _quote(ts: int, mid: float) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{ts}",
        sequence=ts,
        symbol="AAPL",
        bid=Decimal(str(round(mid - 0.005, 6))),
        ask=Decimal(str(round(mid + 0.005, 6))),
        bid_size=100,
        ask_size=100,
        exchange_timestamp_ns=ts,
    )


def _replay(mids: list[float]) -> tuple[list[HorizonFeatureSnapshot], list[int], list[float]]:
    """Drive the real pipeline; return (warm h=30 snapshots, times_ns, mids)."""
    bus = EventBus()
    snaps: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, snaps.append)  # type: ignore[arg-type]

    registry = SensorRegistry(
        bus=bus, sequence_generator=SequenceGenerator(), symbols=frozenset({"AAPL"})
    )
    registry.register(
        SensorSpec(
            sensor_id="ramp", sensor_version="1.0.0", cls=_RampSensor, subscribes_to=(NBBOQuote,)
        )
    )
    scheduler = HorizonScheduler(
        horizons=frozenset({_H}),
        session_id="CERT",
        symbols=frozenset({"AAPL"}),
        session_open_ns=0,
        sequence_generator=SequenceGenerator(),
    )
    agg = HorizonAggregator(
        bus=bus,
        symbols=frozenset({"AAPL"}),
        sensor_buffer_seconds=2 * _H,
        sequence_generator=SequenceGenerator(),
        horizon_features=[SensorPassthroughFeature("ramp", _H)],
    )
    agg.attach()

    times = [i * _NS for i in range(len(mids))]
    for ts, mid in zip(times, mids):
        q = _quote(ts, mid)
        bus.publish(q)
        for tick in scheduler.on_event(q):
            bus.publish(tick)
    # SYMBOL-scope snapshots only (UNIVERSE ticks are deduped at the same boundary).
    warm = [s for s in snaps if "ramp" in s.values]
    return warm, times, mids


def test_apparatus_value_is_causal_and_exact() -> None:
    """The boundary feature value reflects exactly the quotes at/before the
    snapshot time — never a later quote (no look-ahead) — and the aggregation
    is exact."""
    mids = [100.0 * (1.0 + 1e-4 * i + 1e-6 * i * i) for i in range(200)]
    warm, _times, _mids = _replay(mids)
    assert warm, "expected warm boundary snapshots"
    for s in warm:
        # ramp(n) == number of quotes with ts <= snapshot.timestamp_ns,
        # and quotes are 1 s apart starting at t=0 → count = (t // 1s) + 1.
        expected = (s.timestamp_ns // _NS) + 1
        assert s.values["ramp"] == float(expected), (
            f"boundary {s.boundary_index}: value {s.values['ramp']} != {expected} "
            "(aggregation/look-ahead error)"
        )


def test_apparatus_pairing_yields_closed_form_rank_ic_plus_one() -> None:
    """A reference feature that is co-monotone with the forward return must
    measure RankIC = +1.0 through the full pipeline + harness pairing."""
    mids = [100.0 * (1.0 + 1e-4 * i + 1e-6 * i * i) for i in range(200)]  # convex ⇒ fwd rises
    warm, times, mids_out = _replay(mids)

    feats: list[float] = []
    fwds: list[float] = []
    for s in warm:
        fwd = forward_return_at(times, mids_out, s.timestamp_ns, _H)
        if fwd != fwd:  # NaN: forward window runs off the end of the tape
            continue
        feats.append(s.values["ramp"])
        fwds.append(fwd)

    # The last boundary's forward window exceeds the tape → it was dropped.
    assert len(fwds) < len(warm), "expected the final boundary's forward pair to be dropped"
    # Construction sanity: both series strictly increasing ⇒ co-monotone.
    assert feats == sorted(feats) and len(set(feats)) == len(feats)
    assert fwds == sorted(fwds) and len(set(fwds)) == len(fwds)
    # The certification: exact pairing through the real apparatus ⇒ rho = +1.
    assert spearman_ic(feats, fwds).rho == 1.0


def test_apparatus_pairing_detects_inverted_sign() -> None:
    """A concave mid (forward returns decreasing) must measure RankIC = -1.0 —
    proving the pairing preserves sign / direction."""
    mids = [100.0 * (1.0 + 1e-3 * i - 2e-6 * i * i) for i in range(180)]  # concave ⇒ fwd falls
    warm, times, mids_out = _replay(mids)
    feats: list[float] = []
    fwds: list[float] = []
    for s in warm:
        fwd = forward_return_at(times, mids_out, s.timestamp_ns, _H)
        if fwd == fwd:
            feats.append(s.values["ramp"])
            fwds.append(fwd)
    assert feats == sorted(feats)  # ramp still increasing
    assert fwds == sorted(fwds, reverse=True)  # forward returns decreasing
    assert spearman_ic(feats, fwds).rho == -1.0
