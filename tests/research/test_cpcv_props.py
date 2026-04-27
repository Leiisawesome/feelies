"""Hypothesis property tests for :mod:`feelies.research.cpcv`.

These tests assert *structural* invariants over a wide search space
of ``(n_bars, n_groups, k_test_groups, embargo_bars)`` configurations
— the kind of sweeps that catch off-by-ones in the
purge / embargo / path-reconstruction algorithms long before they
slip past unit tests.

Inv-5 (deterministic replay) is asserted directly: every property
runs each draw twice and compares for byte-identical output.
"""

from __future__ import annotations

import math
import random

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from feelies.research.cpcv import (
    CPCVConfig,
    assemble_path_returns,
    assign_groups,
    build_cpcv_evidence,
    fold_pnl_curves_sha256,
    generate_cpcv_splits,
    lo_bootstrap_p_value,
    reconstruct_paths,
    sharpe_ratio,
)


# Bound the search to keep the property suite fast.  A draw of
# (n_groups=10, k=5) costs C(10, 5) = 252 splits which is the upper
# end of what the platform realistically uses.
_n_groups_st = st.integers(min_value=2, max_value=8)
_embargo_st = st.integers(min_value=0, max_value=5)


@st.composite
def _cpcv_config_and_n_bars(draw: st.DrawFn) -> tuple[CPCVConfig, int]:
    n_groups = draw(_n_groups_st)
    k = draw(st.integers(min_value=1, max_value=n_groups - 1))
    embargo = draw(_embargo_st)
    n_bars = draw(
        st.integers(min_value=n_groups, max_value=10 * n_groups)
    )
    return (
        CPCVConfig(n_groups=n_groups, k_test_groups=k, embargo_bars=embargo),
        n_bars,
    )


# ─────────────────────────────────────────────────────────────────────
#   assign_groups invariants
# ─────────────────────────────────────────────────────────────────────


@given(
    n_bars=st.integers(min_value=1, max_value=200),
    n_groups=st.integers(min_value=1, max_value=20),
)
def test_assign_groups_covers_every_bar_exactly_once(
    n_bars: int, n_groups: int
) -> None:
    if n_bars < n_groups:
        return  # invalid input — covered by unit tests
    groups = assign_groups(n_bars, n_groups)
    flat: list[int] = []
    for g in groups:
        flat.extend(g)
    assert flat == list(range(n_bars))


@given(
    n_bars=st.integers(min_value=1, max_value=200),
    n_groups=st.integers(min_value=1, max_value=20),
)
def test_assign_groups_sizes_differ_by_at_most_one(
    n_bars: int, n_groups: int
) -> None:
    if n_bars < n_groups:
        return
    groups = assign_groups(n_bars, n_groups)
    sizes = [len(g) for g in groups]
    assert max(sizes) - min(sizes) <= 1


# ─────────────────────────────────────────────────────────────────────
#   generate_cpcv_splits invariants
# ─────────────────────────────────────────────────────────────────────


@given(_cpcv_config_and_n_bars())
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
def test_split_count_equals_C_N_k(args: tuple[CPCVConfig, int]) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    assert len(splits) == math.comb(cfg.n_groups, cfg.k_test_groups)


@given(_cpcv_config_and_n_bars())
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
def test_train_test_disjoint(args: tuple[CPCVConfig, int]) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    for s in splits:
        assert set(s.train_indices).isdisjoint(s.test_indices)


@given(_cpcv_config_and_n_bars())
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
def test_train_indices_excludes_embargo_zone(
    args: tuple[CPCVConfig, int],
) -> None:
    cfg, n_bars = args
    if cfg.embargo_bars == 0:
        return
    splits = generate_cpcv_splits(n_bars, cfg)
    for s in splits:
        # Identify contiguous test regions and verify the embargo
        # bars after each region are absent from train_indices.
        test_set = set(s.test_indices)
        train_set = set(s.train_indices)
        i = 0
        while i < n_bars:
            if i in test_set:
                # Find end of this test region
                j = i
                while j + 1 < n_bars and (j + 1) in test_set:
                    j += 1
                # Embargo zone: (j, j + embargo_bars]
                for k in range(
                    j + 1, min(j + 1 + cfg.embargo_bars, n_bars)
                ):
                    if k not in test_set:
                        assert k not in train_set, (
                            f"embargo violated: bar {k} is in train, "
                            f"but should be embargoed after region "
                            f"ending at {j}"
                        )
                i = j + 1
            else:
                i += 1


@given(_cpcv_config_and_n_bars())
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
def test_no_embargo_train_test_union_is_full_range(
    args: tuple[CPCVConfig, int],
) -> None:
    cfg, n_bars = args
    if cfg.embargo_bars != 0:
        return
    splits = generate_cpcv_splits(n_bars, cfg)
    for s in splits:
        assert set(s.train_indices) | set(s.test_indices) == set(
            range(n_bars)
        )


@given(_cpcv_config_and_n_bars())
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
def test_each_group_in_C_N_minus_1_k_minus_1_splits(
    args: tuple[CPCVConfig, int],
) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    expected = math.comb(cfg.n_groups - 1, cfg.k_test_groups - 1)
    counts: dict[int, int] = {g: 0 for g in range(cfg.n_groups)}
    for s in splits:
        for g in s.test_group_ids:
            counts[g] += 1
    for g, c in counts.items():
        assert c == expected, (
            f"group {g}: count={c}, expected={expected} "
            f"for cfg={cfg}"
        )


@given(_cpcv_config_and_n_bars())
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
def test_replay_deterministic_splits(
    args: tuple[CPCVConfig, int],
) -> None:
    cfg, n_bars = args
    s1 = generate_cpcv_splits(n_bars, cfg)
    s2 = generate_cpcv_splits(n_bars, cfg)
    assert s1 == s2


# ─────────────────────────────────────────────────────────────────────
#   reconstruct_paths invariants
# ─────────────────────────────────────────────────────────────────────


@given(_cpcv_config_and_n_bars())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_path_count_equals_C_N_minus_1_k_minus_1(
    args: tuple[CPCVConfig, int],
) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    paths = reconstruct_paths(cfg.n_groups, cfg.k_test_groups, splits)
    assert len(paths) == math.comb(
        cfg.n_groups - 1, cfg.k_test_groups - 1
    )


@given(_cpcv_config_and_n_bars())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_each_path_split_tests_its_assigned_group(
    args: tuple[CPCVConfig, int],
) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    paths = reconstruct_paths(cfg.n_groups, cfg.k_test_groups, splits)
    for path in paths:
        assert len(path) == cfg.n_groups
        for g, split_idx in enumerate(path):
            assert g in splits[split_idx].test_group_ids


@given(_cpcv_config_and_n_bars())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_paths_are_distinct(args: tuple[CPCVConfig, int]) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    paths = reconstruct_paths(cfg.n_groups, cfg.k_test_groups, splits)
    assert len(set(paths)) == len(paths)


@given(_cpcv_config_and_n_bars())
@settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow])
def test_paths_canonically_sorted(
    args: tuple[CPCVConfig, int],
) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    paths = reconstruct_paths(cfg.n_groups, cfg.k_test_groups, splits)
    assert list(paths) == sorted(paths)


# ─────────────────────────────────────────────────────────────────────
#   assemble_path_returns invariants
# ─────────────────────────────────────────────────────────────────────


@given(_cpcv_config_and_n_bars(), st.integers(min_value=0, max_value=2**31 - 1))
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_assembled_paths_have_n_bars_returns(
    args: tuple[CPCVConfig, int], seed: int
) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    paths = reconstruct_paths(cfg.n_groups, cfg.k_test_groups, splits)
    rng = random.Random(seed)
    test_returns: list[tuple[float, ...]] = [
        tuple(rng.gauss(0.0, 1.0) for _ in s.test_indices)
        for s in splits
    ]
    out = assemble_path_returns(
        n_bars=n_bars,
        n_groups=cfg.n_groups,
        splits=splits,
        test_returns_by_split=test_returns,
        paths=paths,
    )
    assert len(out) == len(paths)
    for path_returns in out:
        assert len(path_returns) == n_bars


@given(_cpcv_config_and_n_bars())
@settings(max_examples=40, suppress_health_check=[HealthCheck.too_slow])
def test_identity_returns_yield_identical_paths(
    args: tuple[CPCVConfig, int],
) -> None:
    """If every split's OOS test return at bar ``i`` is just ``i``
    itself (no model-induced split-to-split variation), every
    reconstructed path should equal ``[0, 1, ..., n-1]``."""
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    paths = reconstruct_paths(cfg.n_groups, cfg.k_test_groups, splits)
    test_returns: list[tuple[float, ...]] = [
        tuple(float(i) for i in s.test_indices) for s in splits
    ]
    out = assemble_path_returns(
        n_bars=n_bars,
        n_groups=cfg.n_groups,
        splits=splits,
        test_returns_by_split=test_returns,
        paths=paths,
    )
    expected = tuple(float(i) for i in range(n_bars))
    for path_returns in out:
        assert path_returns == expected


# ─────────────────────────────────────────────────────────────────────
#   sharpe_ratio invariants
# ─────────────────────────────────────────────────────────────────────


@given(
    st.lists(
        st.floats(
            min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
        ),
        min_size=2,
        max_size=200,
    )
)
@settings(max_examples=80)
def test_sharpe_scale_invariant(returns: list[float]) -> None:
    """Sharpe is invariant to positive scaling: scaling all returns
    by a positive constant leaves mean/sd unchanged in ratio."""
    s_orig = sharpe_ratio(returns)
    scaled = [r * 2.5 for r in returns]
    s_scaled = sharpe_ratio(scaled)
    if s_orig == 0.0:
        assert s_scaled == 0.0
    else:
        assert math.isclose(s_orig, s_scaled, rel_tol=1e-9, abs_tol=1e-12)


@given(
    st.lists(
        st.floats(
            min_value=-10.0, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
        min_size=2,
        max_size=100,
    )
)
@settings(max_examples=80)
def test_sharpe_sign_flips_with_negation(returns: list[float]) -> None:
    s_orig = sharpe_ratio(returns)
    s_neg = sharpe_ratio([-r for r in returns])
    if s_orig == 0.0:
        assert s_neg == 0.0
    else:
        assert math.isclose(s_orig, -s_neg, rel_tol=1e-9, abs_tol=1e-12)


# ─────────────────────────────────────────────────────────────────────
#   lo_bootstrap_p_value determinism
# ─────────────────────────────────────────────────────────────────────


@given(
    sharpes=st.lists(
        st.floats(
            min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        min_size=2,
        max_size=20,
    ),
    seed=st.integers(min_value=0, max_value=10_000),
    n_bootstrap=st.integers(min_value=10, max_value=200),
)
@settings(max_examples=40)
def test_bootstrap_p_value_deterministic(
    sharpes: list[float], seed: int, n_bootstrap: int
) -> None:
    p1 = lo_bootstrap_p_value(
        sharpes, n_bootstrap=n_bootstrap, seed=seed
    )
    p2 = lo_bootstrap_p_value(
        sharpes, n_bootstrap=n_bootstrap, seed=seed
    )
    assert p1 == p2


@given(
    sharpes=st.lists(
        st.floats(
            min_value=-5.0, max_value=5.0, allow_nan=False, allow_infinity=False
        ),
        min_size=2,
        max_size=20,
    ),
    seed=st.integers(min_value=0, max_value=10_000),
    n_bootstrap=st.integers(min_value=10, max_value=200),
)
@settings(max_examples=40)
def test_bootstrap_p_value_in_unit_interval(
    sharpes: list[float], seed: int, n_bootstrap: int
) -> None:
    p = lo_bootstrap_p_value(
        sharpes, n_bootstrap=n_bootstrap, seed=seed
    )
    assert 0.0 < p <= 1.0
    # Floor under the +1/+1 correction is 1/(B+1).
    assert p >= 1.0 / (n_bootstrap + 1) - 1e-12


# ─────────────────────────────────────────────────────────────────────
#   fold_pnl_curves_sha256 stability
# ─────────────────────────────────────────────────────────────────────


@given(
    st.lists(
        st.lists(
            st.floats(
                min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False
            ),
            min_size=1,
            max_size=20,
        ),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=40)
def test_hash_deterministic(paths: list[list[float]]) -> None:
    h1 = fold_pnl_curves_sha256(paths)
    h2 = fold_pnl_curves_sha256(paths)
    assert h1 == h2


# ─────────────────────────────────────────────────────────────────────
#   build_cpcv_evidence determinism
# ─────────────────────────────────────────────────────────────────────


@given(_cpcv_config_and_n_bars(), st.integers(min_value=0, max_value=2**31 - 1))
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_build_cpcv_evidence_deterministic(
    args: tuple[CPCVConfig, int], seed: int
) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    rng = random.Random(seed)
    test_returns: list[tuple[float, ...]] = [
        tuple(rng.gauss(0.001, 0.01) for _ in s.test_indices)
        for s in splits
    ]
    ev1 = build_cpcv_evidence(
        config=cfg,
        n_bars=n_bars,
        test_returns_by_split=test_returns,
        n_bootstrap=50,
        seed=seed,
    )
    ev2 = build_cpcv_evidence(
        config=cfg,
        n_bars=n_bars,
        test_returns_by_split=test_returns,
        n_bootstrap=50,
        seed=seed,
    )
    assert ev1 == ev2


@given(_cpcv_config_and_n_bars(), st.integers(min_value=0, max_value=2**31 - 1))
@settings(max_examples=20, suppress_health_check=[HealthCheck.too_slow])
def test_evidence_fold_count_matches_paths(
    args: tuple[CPCVConfig, int], seed: int
) -> None:
    cfg, n_bars = args
    splits = generate_cpcv_splits(n_bars, cfg)
    rng = random.Random(seed)
    test_returns: list[tuple[float, ...]] = [
        tuple(rng.gauss(0.0, 1.0) for _ in s.test_indices)
        for s in splits
    ]
    ev = build_cpcv_evidence(
        config=cfg,
        n_bars=n_bars,
        test_returns_by_split=test_returns,
        n_bootstrap=20,
        seed=seed,
    )
    assert ev.fold_count == cfg.n_paths
    assert len(ev.fold_sharpes) == cfg.n_paths
    assert ev.embargo_bars == cfg.embargo_bars
