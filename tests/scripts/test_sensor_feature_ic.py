"""Unit coverage for the sensor/feature IC harness (scripts/sensor_feature_ic.py).

Validates the pure statistics and the end-to-end replay→pairing wiring on
synthetic events, so the offline validation tool can't silently rot.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from feelies.core.events import NBBOQuote
import scripts.sensor_feature_ic as ic


def _quote(ts_ns: int, bid: str, ask: str, bid_sz: int, ask_sz: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"q-{ts_ns}",
        sequence=ts_ns,
        symbol="AAPL",
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=bid_sz,
        ask_size=ask_sz,
        exchange_timestamp_ns=ts_ns,
    )


# ── statistics ───────────────────────────────────────────────────────────


def test_rankdata_handles_ties() -> None:
    # values 10, 20, 20, 30 → ranks 1, 2.5, 2.5, 4
    assert ic._rankdata([10.0, 20.0, 20.0, 30.0]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_monotonic_is_one() -> None:
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 6.0, 8.0, 10.0]  # strictly increasing transform
    assert ic._spearman(xs, ys) == pytest.approx(1.0)
    # Reversed → -1.
    assert ic._spearman(xs, list(reversed(ys))) == pytest.approx(-1.0)


def test_pearson_perfect_linear() -> None:
    xs = [1.0, 2.0, 3.0, 4.0]
    ys = [3.0, 5.0, 7.0, 9.0]  # y = 2x + 1
    assert ic._pearson(xs, ys) == pytest.approx(1.0)


def test_correlations_degenerate_inputs() -> None:
    assert ic._pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None  # zero var
    assert ic._spearman([1.0], [2.0]) is None  # too few


def test_tstat_grows_with_n() -> None:
    assert ic._tstat(0.1, 1000) > ic._tstat(0.1, 50)


# ── mid series + forward returns ─────────────────────────────────────────


def test_mid_series_is_causal() -> None:
    NS = ic._NS_PER_SECOND
    evs = [
        _quote(0, "100.00", "100.02", 100, 100),
        _quote(1 * NS, "101.00", "101.02", 100, 100),
        _quote(2 * NS, "102.00", "102.02", 100, 100),
    ]
    mids = ic._MidSeries.from_events(evs)
    assert mids.at(-1) is None  # before start
    assert mids.at(0) == pytest.approx(100.01)
    assert mids.at(1 * NS + 500) == pytest.approx(101.01)  # last <= t
    assert mids.last_ts == 2 * NS


def test_forward_return_drops_when_window_unrealised() -> None:
    NS = ic._NS_PER_SECOND
    evs = [_quote(i * NS, f"{100 + i}.00", f"{100 + i}.02", 100, 100) for i in range(5)]
    mids = ic._MidSeries.from_events(evs)
    # 2 s horizon from t=0 has data (t=2s exists); 100 s horizon does not.
    assert ic._forward_return(mids, 0, 2) is not None
    assert ic._forward_return(mids, 0, 100) is None


# ── end-to-end replay → pairing ──────────────────────────────────────────


def test_replay_produces_snapshots_and_pairs() -> None:
    NS = ic._NS_PER_SECOND
    # 400 s of quotes, 1/sec.  The mid drifts upward (1 cent every 10 s) so
    # forward returns are non-zero, with bid-size imbalance driving OFI.
    evs = []
    for i in range(400):
        cents = i // 10
        px = 100.00 + cents * 0.01
        bid_sz = 100 + (i % 50)
        evs.append(_quote(i * NS, f"{px:.2f}", f"{px + 0.02:.2f}", bid_sz, 100))
    horizons = frozenset({30, 120})
    feats = [f for h in sorted(horizons) for f in ic._window_builder("ofi_ewma")("ofi_ewma", h)]
    snaps = ic._replay_snapshots(
        evs,
        symbol="AAPL",
        horizon_features=feats,
        horizons=horizons,
        session_open_ns=0,
    )
    assert snaps, "expected snapshots from the synthetic replay"
    mids = ic._MidSeries.from_events(evs)
    pairs = ic._collect_pairs(snaps, mids, "ofi_ewma_zscore", 30)
    # Some boundaries should be warm and have a realised forward window.
    assert len(pairs.values) == len(pairs.fwd)
    assert len(pairs.values) >= 1


def test_collect_pairs_anchors_on_boundary_ts_ns_not_timestamp_ns() -> None:
    """sensor_audit_2026-07-02 P1: on a sparse tape the event that *triggers*
    a HorizonTick can arrive well after the nominal grid boundary.
    ``HorizonFeatureSnapshot.boundary_ts_ns`` is documented as "the regular-
    grid anchor for IC labels / forensics" (core/events.py) specifically so
    forward-return pairing is not skewed by that trigger-time lag; this locks
    ``_collect_pairs`` to that field.

    Constructed so the two anchors give an unambiguous, opposite-verdict
    contrast: from the nominal boundary (30s) the 30s-forward window is
    *realised* (data exists through 60s); from the late trigger time (90s,
    simulating a long gap before the triggering event) the same 30s horizon
    would require data through 120s, which does not exist yet — the wrong
    anchor would silently drop this pair as unrealised instead of just
    computing a different value, making the bug unambiguous rather than a
    matter of degree.
    """
    from feelies.core.events import HorizonFeatureSnapshot

    NS = ic._NS_PER_SECOND
    snap = HorizonFeatureSnapshot(
        timestamp_ns=90 * NS,  # late trigger — the bug's anchor
        correlation_id="snap-1",
        sequence=1,
        symbol="AAPL",
        horizon_seconds=30,
        boundary_index=1,
        boundary_ts_ns=30 * NS,  # nominal grid boundary — the correct anchor
        values={"demo": 1.0},
        warm={"demo": True},
        stale={"demo": False},
    )
    evs = [
        _quote(0, "99.99", "100.01", 100, 100),
        _quote(60 * NS, "199.99", "200.01", 100, 100),
        _quote(65 * NS, "199.99", "200.01", 100, 100),  # last quote at t=65s
    ]
    mids = ic._MidSeries.from_events(evs)

    from_boundary = ic._forward_return(mids, 30 * NS, 30)  # window end 60s <= last_ts 65s
    assert from_boundary is not None

    from_trigger = ic._forward_return(mids, 90 * NS, 30)  # window end 120s > last_ts 65s
    assert from_trigger is None

    pairs = ic._collect_pairs([snap], mids, "demo", 30)
    # Using timestamp_ns would drop this pair entirely (unrealised); using
    # boundary_ts_ns realises it with the expected value.
    assert pairs.values == [1.0]
    assert pairs.fwd == [from_boundary]


def test_kyle_alignment_ab_registers_both_versions_and_runs() -> None:
    """P1-5 A/B must register legacy 1.2.0 and causal 2.0.0 kyle (version-match
    via params) and produce both variant rows."""
    NS = ic._NS_PER_SECOND
    from decimal import Decimal

    from feelies.core.events import Trade

    evs: list = []
    for i in range(120):
        cents = i // 5
        px = 100.00 + cents * 0.01
        evs.append(_quote(i * NS, f"{px:.2f}", f"{px + 0.02:.2f}", 100, 100))
        evs.append(
            Trade(
                timestamp_ns=i * NS + 1,
                correlation_id=f"t-{i}",
                sequence=i * NS + 1,
                symbol="AAPL",
                price=Decimal(f"{px:.2f}"),
                size=100,
                exchange_timestamp_ns=i * NS + 1,
            )
        )
    evs.sort(key=lambda e: (e.timestamp_ns, e.sequence))
    mids = ic._MidSeries.from_events(evs)
    rows = ic._kyle_alignment_ab(
        evs,
        mids,
        "AAPL",
        "2026-01-01",
        frozenset({30, 120}),
        session_open_ns=0,
    )
    assert {r.variant for r in rows} == {"kyle_legacy_win", "kyle_causal_win"}
    assert all(r.feature == "kyle_alignment" for r in rows)
