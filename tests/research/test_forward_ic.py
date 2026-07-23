"""Unit tests for forward-return and Spearman-IC calculations."""

from __future__ import annotations

import math
import random

import pytest

from feelies.research.forward_ic import (
    bucketed_forward_return,
    forward_return_at,
    spearman_ic,
)


def test_perfect_monotone_increasing_is_plus_one() -> None:
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [10.0, 20.0, 30.0, 40.0, 50.0]
    res = spearman_ic(x, y)
    assert res.rho == pytest.approx(1.0)
    assert res.n == 5
    assert res.p_value < 0.05


def test_perfect_monotone_decreasing_is_minus_one() -> None:
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [50.0, 40.0, 30.0, 20.0, 10.0]
    assert spearman_ic(x, y).rho == pytest.approx(-1.0)


def test_nonlinear_but_monotone_still_plus_one() -> None:
    # Spearman is rank-based: a monotone nonlinear map is still rho=1.
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [1.0, 4.0, 9.0, 16.0, 25.0]
    assert spearman_ic(x, y).rho == pytest.approx(1.0)


def test_constant_side_returns_zero() -> None:
    x = [1.0, 1.0, 1.0, 1.0]
    y = [1.0, 2.0, 3.0, 4.0]
    res = spearman_ic(x, y)
    assert res.rho == 0.0
    assert res.p_value == 1.0


def test_ties_use_average_ranks() -> None:
    # Matches scipy.stats.spearmanr on this vector (rho ~= 0.94868...).
    x = [1.0, 2.0, 2.0, 3.0]
    y = [1.0, 2.0, 3.0, 4.0]
    assert spearman_ic(x, y).rho == pytest.approx(0.9486832980505138, abs=1e-9)


def test_nan_pairs_dropped() -> None:
    x = [1.0, 2.0, float("nan"), 4.0, 5.0]
    y = [10.0, 20.0, 30.0, 40.0, 50.0]
    res = spearman_ic(x, y)
    assert res.n == 4
    assert res.rho == pytest.approx(1.0)


def test_too_few_observations_raises() -> None:
    with pytest.raises(ValueError, match=">= 3"):
        spearman_ic([1.0, 2.0], [3.0, 4.0])


def test_shape_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="align"):
        spearman_ic([1.0, 2.0, 3.0], [1.0, 2.0])


def test_bucketed_forward_return_monotone_profile() -> None:
    rng = random.Random(0)
    x = [rng.gauss(0.0, 1.0) for _ in range(500)]
    y = [0.5 * xi + rng.gauss(0.0, 0.1) for xi in x]  # forward return rises with x
    buckets = bucketed_forward_return(x, y, n_buckets=5)
    means = [b.mean_forward_return for b in buckets]
    assert len(buckets) == 5
    assert means == sorted(means)  # monotone increasing
    assert means[0] < 0 < means[-1]


def test_forward_return_at_basic() -> None:
    times = [i * 1_000_000_000 for i in range(10)]
    mids = [100.0 + i for i in range(10)]
    # anchor at 2s -> base mid=102; target 5s -> mid=105; return = 105/102 - 1
    r = forward_return_at(times, mids, anchor_ns=2_000_000_000, horizon_seconds=3.0)
    assert r == pytest.approx(105.0 / 102.0 - 1.0)


def test_forward_return_at_past_end_is_nan() -> None:
    times = [0, 1_000_000_000, 2_000_000_000]
    mids = [100.0, 101.0, 102.0]
    r = forward_return_at(times, mids, anchor_ns=2_000_000_000, horizon_seconds=30.0)
    assert math.isnan(r)
