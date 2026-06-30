"""Gas decision #2 — integrated OFI as a fast-horizon (~30 s) momentum input.

Gas #1 found one statistically robust result: at 30 s, ``ofi_integrated`` has
RankIC +0.10 (n≈810, t≈2.9), ~2.2× ``ofi_ewma_zscore``.  But 30 s is at the edge
of cost-arithmetic feasibility, so the *binding* gate here is tradability, not
RankIC: the captured edge must clear ~1.5× round-trip cost (Inv-12).

These tests certify the cost-gate primitive ``forward_ic.long_short_edge_bps``
(the gross top−bottom-bucket forward-return spread in bps).  The edge *evidence*
on real data is operator-run; see ``docs/research/gas_02_fast_ofi_momentum.md``.
"""

from __future__ import annotations

import math

import pytest

from feelies.research.forward_ic import bucketed_forward_return, long_short_edge_bps


def test_long_short_edge_bps_positive_for_momentum_feature() -> None:
    # Feature co-monotone with forward return ⇒ top bucket earns more than
    # bottom ⇒ positive long-short edge.
    feat = [float(i) for i in range(10)]
    fwd = [0.001 * i for i in range(10)]  # +0.1% per rank step
    edge = long_short_edge_bps(feat, fwd, n_buckets=5)
    # Top bucket {8,9} mean fwd = 0.0085, bottom {0,1} = 0.0005 ⇒ 0.008 ⇒ 80 bps.
    assert edge == pytest.approx((0.0085 - 0.0005) * 1e4)
    assert edge > 0.0


def test_long_short_edge_bps_negative_for_contrarian_feature() -> None:
    feat = [float(i) for i in range(10)]
    fwd = [-0.001 * i for i in range(10)]  # forward return falls as feature rises
    assert long_short_edge_bps(feat, fwd, n_buckets=5) < 0.0


def test_long_short_edge_bps_near_zero_for_unpredictive_feature() -> None:
    # Forward return independent of feature ordering ⇒ ~no long-short spread.
    feat = [float(i) for i in range(10)]
    fwd = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert long_short_edge_bps(feat, fwd, n_buckets=5) == pytest.approx(0.0)


def test_long_short_edge_bps_matches_bucket_spread() -> None:
    feat = [3.0, 1.0, 4.0, 1.5, 5.0, 9.0, 2.0, 6.0, 5.5, 3.5, 8.0, 7.0]
    fwd = [0.002 * f for f in feat]  # monotone in feature
    buckets = bucketed_forward_return(feat, fwd, n_buckets=4)
    expected = (buckets[-1].mean_forward_return - buckets[0].mean_forward_return) * 1e4
    assert long_short_edge_bps(feat, fwd, n_buckets=4) == pytest.approx(expected)


def test_long_short_edge_bps_drops_nonfinite_pairs() -> None:
    feat = [1.0, 2.0, float("nan"), 4.0, 5.0, 6.0]
    fwd = [0.001, 0.002, 0.5, 0.004, 0.005, 0.006]
    edge = long_short_edge_bps(feat, fwd, n_buckets=2)
    assert math.isfinite(edge) and edge > 0.0
