"""OFIRawSensor — per-event OFI and the integrated-flow property (audit 2P-2)."""

from __future__ import annotations

from decimal import Decimal

from feelies.core.events import HorizonTick, NBBOQuote
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature
from feelies.sensors.impl.ofi_raw import OFIRawSensor

_NS = 1_000_000_000


def _quote(
    ts: int, bid: float, ask: float, *, bid_sz: int = 100, ask_sz: int = 100, seq: int = 0
) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts,
        correlation_id=f"q-{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=bid_sz,
        ask_size=ask_sz,
        exchange_timestamp_ns=ts,
    )


def test_first_quote_has_no_measurable_ofi() -> None:
    s = OFIRawSensor(warm_after=1)
    st = s.initial_state()
    r = s.update(_quote(0, 100.00, 100.02), st, {})
    assert r is not None and r.value == 0.0 and r.warm is False


def test_raw_ofi_sign_matches_cks_on_bid_lift() -> None:
    s = OFIRawSensor(warm_after=1)
    st = s.initial_state()
    s.update(_quote(0, 100.00, 100.02, bid_sz=100, ask_sz=100), st, {})
    # Bid lifts to 100.01 with 300 lots ⇒ +300; ask unchanged with same size ⇒ 0.
    r = s.update(_quote(_NS, 100.01, 100.02, bid_sz=300, ask_sz=100, seq=1), st, {})
    assert r is not None and r.value == 300.0 and r.warm is True


def test_sum_reducer_gives_integrated_flow() -> None:
    """Σ raw OFI over the window (sum reducer) equals net signed flow, with
    each event counted exactly once (unlike a sum over the EWMA)."""
    s = OFIRawSensor(warm_after=1)
    st = s.initial_state()
    feat = HorizonWindowedFeature("ofi_raw", 120, reducer="sum", feature_id="ofi_integrated", min_samples=1)
    fstate = feat.initial_state()

    # Three OFI-bearing quotes: +300 (bid lift), -100 (bid drop to prior size),
    # +50 (ask drop reduces sell pressure differently) — we just sum whatever
    # the sensor emits and assert the feature reproduces that exact sum.
    quotes = [
        _quote(0, 100.00, 100.02, bid_sz=100, ask_sz=100, seq=0),
        _quote(_NS, 100.01, 100.02, bid_sz=300, ask_sz=100, seq=1),
        _quote(2 * _NS, 100.00, 100.02, bid_sz=100, ask_sz=100, seq=2),
        _quote(3 * _NS, 100.00, 100.03, bid_sz=100, ask_sz=80, seq=3),
    ]
    expected = 0.0
    for q in quotes:
        r = s.update(q, st, {})
        assert r is not None
        if r.warm:
            feat.observe(r, fstate, {})
            expected += float(r.value)

    tick = HorizonTick(
        timestamp_ns=3 * _NS,
        correlation_id="tick",
        sequence=0,
        horizon_seconds=120,
        boundary_index=1,
        scope="SYMBOL",
        symbol="AAPL",
        session_id="T",
    )
    value, warm, _stale = feat.finalize(tick, fstate, {})
    assert warm is True
    assert value == expected
