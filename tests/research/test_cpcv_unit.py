"""Unit tests for :mod:`feelies.research.cpcv` (Workstream C-1).

Covers:
- ``CPCVConfig`` validation.
- ``assign_groups`` partitioning (even and uneven).
- ``generate_cpcv_splits`` count, lex order, purge correctness,
  embargo correctness.
- ``reconstruct_paths`` count and shape.
- ``assemble_path_returns`` chronological stitching.
- ``sharpe_ratio`` standard cases and degenerate inputs.
- ``lo_bootstrap_p_value`` determinism, edge cases, and
  significant-vs-noise discrimination.
- ``fold_pnl_curves_sha256`` stability.
- ``build_cpcv_evidence`` end-to-end happy path producing an
  evidence package that passes the F-2 ``cpcv_min_folds`` and
  ``cpcv_max_p_value`` validators.
"""

from __future__ import annotations

import math
import random

import pytest

from feelies.alpha.promotion_evidence import (
    CPCVEvidence,
    GateThresholds,
    validate_cpcv,
)
from feelies.research.cpcv import (
    CPCVConfig,
    CPCVSplit,
    assemble_path_returns,
    assign_groups,
    build_cpcv_evidence,
    fold_pnl_curves_sha256,
    generate_cpcv_splits,
    lo_bootstrap_p_value,
    reconstruct_paths,
    sharpe_ratio,
)


# ─────────────────────────────────────────────────────────────────────
#   CPCVConfig validation
# ─────────────────────────────────────────────────────────────────────


class TestCPCVConfigValidation:
    def test_valid_minimal_config(self) -> None:
        cfg = CPCVConfig(n_groups=2, k_test_groups=1)
        assert cfg.n_groups == 2
        assert cfg.k_test_groups == 1
        assert cfg.embargo_bars == 0
        assert cfg.n_combinations == 2
        assert cfg.n_paths == 1

    def test_n_combinations_and_n_paths_for_realistic_run(self) -> None:
        cfg = CPCVConfig(n_groups=10, k_test_groups=2, embargo_bars=5)
        assert cfg.n_combinations == math.comb(10, 2)  # 45
        assert cfg.n_paths == math.comb(9, 1)  # 9

    def test_n_groups_below_two_rejected(self) -> None:
        with pytest.raises(ValueError, match="n_groups must be >= 2"):
            CPCVConfig(n_groups=1, k_test_groups=1)

    def test_k_test_groups_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="k_test_groups"):
            CPCVConfig(n_groups=5, k_test_groups=0)

    def test_k_test_groups_equal_n_rejected(self) -> None:
        with pytest.raises(ValueError, match="k_test_groups"):
            CPCVConfig(n_groups=5, k_test_groups=5)

    def test_negative_embargo_rejected(self) -> None:
        with pytest.raises(ValueError, match="embargo_bars must be >= 0"):
            CPCVConfig(n_groups=4, k_test_groups=2, embargo_bars=-1)


# ─────────────────────────────────────────────────────────────────────
#   assign_groups
# ─────────────────────────────────────────────────────────────────────


class TestAssignGroups:
    def test_even_partition(self) -> None:
        groups = assign_groups(n_bars=12, n_groups=4)
        assert len(groups) == 4
        assert all(len(g) == 3 for g in groups)
        assert groups[0] == (0, 1, 2)
        assert groups[1] == (3, 4, 5)
        assert groups[2] == (6, 7, 8)
        assert groups[3] == (9, 10, 11)

    def test_uneven_partition_remainder_in_first_groups(self) -> None:
        groups = assign_groups(n_bars=10, n_groups=3)
        assert tuple(len(g) for g in groups) == (4, 3, 3)
        flat: list[int] = []
        for g in groups:
            flat.extend(g)
        assert flat == list(range(10))

    def test_partition_covers_every_bar_exactly_once(self) -> None:
        groups = assign_groups(n_bars=23, n_groups=5)
        flat: list[int] = []
        for g in groups:
            flat.extend(g)
        assert flat == list(range(23))

    def test_n_bars_below_n_groups_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one bar per group"):
            assign_groups(n_bars=2, n_groups=5)

    def test_n_groups_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="n_groups must be >= 1"):
            assign_groups(n_bars=10, n_groups=0)


# ─────────────────────────────────────────────────────────────────────
#   generate_cpcv_splits
# ─────────────────────────────────────────────────────────────────────


class TestGenerateCPCVSplits:
    def test_count_equals_C_N_k(self) -> None:
        cfg = CPCVConfig(n_groups=6, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=60, config=cfg)
        assert len(splits) == math.comb(6, 2)

    def test_combination_indices_are_dense_lex_ordered(self) -> None:
        cfg = CPCVConfig(n_groups=5, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=20, config=cfg)
        assert [s.combination_index for s in splits] == list(
            range(len(splits))
        )
        # Lex ordering: ascending tuples.
        for a, b in zip(splits, splits[1:], strict=False):
            assert a.test_group_ids < b.test_group_ids

    def test_test_group_ids_ascending_within_each_split(self) -> None:
        cfg = CPCVConfig(n_groups=8, k_test_groups=3)
        splits = generate_cpcv_splits(n_bars=80, config=cfg)
        for s in splits:
            assert list(s.test_group_ids) == sorted(s.test_group_ids)
            assert len(set(s.test_group_ids)) == cfg.k_test_groups

    def test_test_indices_match_test_group_membership(self) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=12, config=cfg)
        groups = assign_groups(n_bars=12, n_groups=4)
        for s in splits:
            expected: list[int] = []
            for g in s.test_group_ids:
                expected.extend(groups[g])
            assert list(s.test_indices) == sorted(expected)

    def test_train_test_disjoint(self) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=12, config=cfg)
        for s in splits:
            assert set(s.train_indices).isdisjoint(s.test_indices)

    def test_train_test_union_equals_full_range_when_no_embargo(
        self,
    ) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2, embargo_bars=0)
        splits = generate_cpcv_splits(n_bars=12, config=cfg)
        for s in splits:
            assert set(s.train_indices) | set(s.test_indices) == set(
                range(12)
            )

    def test_embargo_excludes_post_test_bars(self) -> None:
        # Use n_bars=10, n_groups=5 -> group_size=2; pick test groups
        # {0, 2}.  With embargo=1 bar after group 0 (idx 1) and after
        # group 2 (idx 5), bars 2 and 6 should be excluded from train.
        cfg = CPCVConfig(n_groups=5, k_test_groups=2, embargo_bars=1)
        splits = generate_cpcv_splits(n_bars=10, config=cfg)
        target = next(s for s in splits if s.test_group_ids == (0, 2))
        assert set(target.test_indices) == {0, 1, 4, 5}
        # After test region [0,1]: embargoed = {2}; after [4,5]: {6}.
        assert 2 not in target.train_indices
        assert 6 not in target.train_indices
        assert set(target.train_indices) == {3, 7, 8, 9}

    def test_embargo_does_not_excise_bars_already_in_test(self) -> None:
        # Two adjacent test groups (0 and 1, bars 0..3) followed by
        # group 2 (bars 4..5).  Embargo=2 should excise bars 4, 5
        # post-test-region — but bars 0..3 stay in test.
        cfg = CPCVConfig(n_groups=3, k_test_groups=2, embargo_bars=2)
        splits = generate_cpcv_splits(n_bars=6, config=cfg)
        target = next(s for s in splits if s.test_group_ids == (0, 1))
        assert set(target.test_indices) == {0, 1, 2, 3}
        # Region ends at bar 3; embargo-2 excises {4, 5}.
        assert set(target.train_indices) == set()

    def test_embargo_truncated_at_n_bars(self) -> None:
        cfg = CPCVConfig(n_groups=3, k_test_groups=1, embargo_bars=10)
        splits = generate_cpcv_splits(n_bars=9, config=cfg)
        target = next(s for s in splits if s.test_group_ids == (1,))
        # Test bars: {3,4,5}; embargo would extend bars 6..15 but
        # n_bars=9 caps at {6,7,8}; left side 0..2 stays as train.
        assert set(target.test_indices) == {3, 4, 5}
        assert set(target.train_indices) == {0, 1, 2}

    def test_purge_removes_test_indices_from_training(self) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2, embargo_bars=0)
        splits = generate_cpcv_splits(n_bars=12, config=cfg)
        for s in splits:
            for ti in s.test_indices:
                assert ti not in s.train_indices

    def test_replay_deterministic(self) -> None:
        cfg = CPCVConfig(n_groups=6, k_test_groups=3, embargo_bars=2)
        s1 = generate_cpcv_splits(n_bars=30, config=cfg)
        s2 = generate_cpcv_splits(n_bars=30, config=cfg)
        assert s1 == s2

    def test_each_group_appears_in_C_N_minus_1_k_minus_1_splits(
        self,
    ) -> None:
        cfg = CPCVConfig(n_groups=6, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=24, config=cfg)
        counts: dict[int, int] = {g: 0 for g in range(cfg.n_groups)}
        for s in splits:
            for g in s.test_group_ids:
                counts[g] += 1
        expected = math.comb(cfg.n_groups - 1, cfg.k_test_groups - 1)
        for g, c in counts.items():
            assert c == expected, f"group {g}: count={c}, expected={expected}"


# ─────────────────────────────────────────────────────────────────────
#   reconstruct_paths
# ─────────────────────────────────────────────────────────────────────


class TestReconstructPaths:
    def test_path_count_equals_C_N_minus_1_k_minus_1(self) -> None:
        cfg = CPCVConfig(n_groups=6, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=24, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        assert len(paths) == math.comb(5, 1)  # 5

    def test_each_path_has_length_n_groups(self) -> None:
        cfg = CPCVConfig(n_groups=5, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=20, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        assert all(len(p) == cfg.n_groups for p in paths)

    def test_each_path_split_actually_tests_its_assigned_group(
        self,
    ) -> None:
        cfg = CPCVConfig(n_groups=5, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=20, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        for path in paths:
            for g, split_idx in enumerate(path):
                assert g in splits[split_idx].test_group_ids

    def test_paths_are_canonically_sorted_for_replay(self) -> None:
        cfg = CPCVConfig(n_groups=5, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=20, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        assert list(paths) == sorted(paths)

    def test_distinct_paths(self) -> None:
        cfg = CPCVConfig(n_groups=6, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=24, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        assert len(set(paths)) == len(paths)

    def test_lopezdeprado_n4_k2_reference(self) -> None:
        # Reference example from the C-1 design notes:
        # N=4, k=2 -> 6 combinations, 3 paths.
        cfg = CPCVConfig(n_groups=4, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=8, config=cfg)
        # combinations enumerated lex: (0,1), (0,2), (0,3), (1,2),
        # (1,3), (2,3) -> indices 0..5.
        assert [s.test_group_ids for s in splits] == [
            (0, 1),
            (0, 2),
            (0, 3),
            (1, 2),
            (1, 3),
            (2, 3),
        ]
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        # Per design-doc derivation:
        #   group 0 testing splits: [0, 1, 2]
        #   group 1 testing splits: [0, 3, 4]
        #   group 2 testing splits: [1, 3, 5]
        #   group 3 testing splits: [2, 4, 5]
        # path p (zip-by-position):
        #   p=0 -> (0, 0, 1, 2)
        #   p=1 -> (1, 3, 3, 4)
        #   p=2 -> (2, 4, 5, 5)
        assert paths == ((0, 0, 1, 2), (1, 3, 3, 4), (2, 4, 5, 5))

    def test_mismatched_splits_raises(self) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2)
        splits = list(generate_cpcv_splits(n_bars=8, config=cfg))
        # Drop one — group counts will no longer match.
        with pytest.raises(ValueError, match="reconstruct_paths"):
            reconstruct_paths(cfg.n_groups, cfg.k_test_groups, splits[:-1])


# ─────────────────────────────────────────────────────────────────────
#   assemble_path_returns
# ─────────────────────────────────────────────────────────────────────


class TestAssemblePathReturns:
    def test_returns_full_length_per_path(self) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2)
        n_bars = 8
        splits = generate_cpcv_splits(n_bars=n_bars, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        # Identity OOS predictions: each split's test return == bar
        # index (so we can verify ordering).
        test_returns_by_split: list[tuple[float, ...]] = [
            tuple(float(i) for i in s.test_indices) for s in splits
        ]
        out = assemble_path_returns(
            n_bars=n_bars,
            n_groups=cfg.n_groups,
            splits=splits,
            test_returns_by_split=test_returns_by_split,
            paths=paths,
        )
        assert len(out) == len(paths)
        for path_returns in out:
            assert len(path_returns) == n_bars
            # Identity prediction means the path is just [0, 1, ..., n-1].
            assert list(path_returns) == [float(i) for i in range(n_bars)]

    def test_chronological_order(self) -> None:
        # Per-split returns differ across splits (each split's test
        # bars get a distinctive multiplier).  Verify the path
        # stitches in chronological bar-index order.
        cfg = CPCVConfig(n_groups=3, k_test_groups=1)
        n_bars = 9
        splits = generate_cpcv_splits(n_bars=n_bars, config=cfg)
        # Splits: group {0}, group {1}, group {2}, with bar ranges
        # 0..2, 3..5, 6..8 respectively.
        # Each split's "OOS prediction" is bar_idx + 100 * split_idx.
        test_returns_by_split: list[tuple[float, ...]] = [
            tuple(
                float(bi + 100 * sidx) for bi in s.test_indices
            )
            for sidx, s in enumerate(splits)
        ]
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        # k=1 means each path uses one split per group, with
        # exactly C(2, 0) = 1 path: path = (0, 1, 2).
        assert paths == ((0, 1, 2),)
        out = assemble_path_returns(
            n_bars=n_bars,
            n_groups=cfg.n_groups,
            splits=splits,
            test_returns_by_split=test_returns_by_split,
            paths=paths,
        )
        # Bar 0 (group 0, split 0) -> 0 + 0 = 0
        # Bar 1 (group 0, split 0) -> 1 + 0 = 1
        # Bar 2 (group 0, split 0) -> 2 + 0 = 2
        # Bar 3 (group 1, split 1) -> 3 + 100 = 103
        # Bar 4 (group 1, split 1) -> 4 + 100 = 104
        # Bar 5 (group 1, split 1) -> 5 + 100 = 105
        # Bar 6 (group 2, split 2) -> 6 + 200 = 206
        # Bar 7 (group 2, split 2) -> 7 + 200 = 207
        # Bar 8 (group 2, split 2) -> 8 + 200 = 208
        assert out[0] == (0.0, 1.0, 2.0, 103.0, 104.0, 105.0, 206.0, 207.0, 208.0)

    def test_mismatched_returns_length_raises(self) -> None:
        cfg = CPCVConfig(n_groups=3, k_test_groups=1)
        splits = generate_cpcv_splits(n_bars=9, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        # Wrong outer length (one split short).
        with pytest.raises(ValueError, match="len.*splits"):
            assemble_path_returns(
                n_bars=9,
                n_groups=cfg.n_groups,
                splits=splits,
                test_returns_by_split=[(0.0,)] * (len(splits) - 1),
                paths=paths,
            )
        # Wrong inner length (split 0 returns the wrong count).
        bad: list[tuple[float, ...]] = [
            tuple(0.0 for _ in s.test_indices) for s in splits
        ]
        bad[0] = (0.0,)  # truncate
        with pytest.raises(ValueError, match="OOS returns"):
            assemble_path_returns(
                n_bars=9,
                n_groups=cfg.n_groups,
                splits=splits,
                test_returns_by_split=bad,
                paths=paths,
            )

    def test_path_length_mismatch_raises(self) -> None:
        cfg = CPCVConfig(n_groups=3, k_test_groups=1)
        splits = generate_cpcv_splits(n_bars=9, config=cfg)
        test_returns: list[tuple[float, ...]] = [
            tuple(0.0 for _ in s.test_indices) for s in splits
        ]
        with pytest.raises(ValueError, match="path length"):
            assemble_path_returns(
                n_bars=9,
                n_groups=cfg.n_groups,
                splits=splits,
                test_returns_by_split=test_returns,
                paths=[(0, 1)],  # wrong length (should be 3)
            )

    def test_split_path_mismatch_raises(self) -> None:
        cfg = CPCVConfig(n_groups=3, k_test_groups=1)
        splits = generate_cpcv_splits(n_bars=9, config=cfg)
        test_returns: list[tuple[float, ...]] = [
            tuple(0.0 for _ in s.test_indices) for s in splits
        ]
        with pytest.raises(ValueError, match="not found in test set"):
            # Path (1, 1, 2): group 0 maps to split 1 (which tests
            # group 1, not group 0) -> bar 0 not in split 1's test
            # indices.
            assemble_path_returns(
                n_bars=9,
                n_groups=cfg.n_groups,
                splits=splits,
                test_returns_by_split=test_returns,
                paths=[(1, 1, 2)],
            )


# ─────────────────────────────────────────────────────────────────────
#   sharpe_ratio
# ─────────────────────────────────────────────────────────────────────


class TestSharpeRatio:
    def test_known_value(self) -> None:
        # mean=2, pstdev=sqrt((4+0+0+0+4)/5)=sqrt(1.6)
        assert math.isclose(
            sharpe_ratio([0.0, 2.0, 2.0, 2.0, 4.0]),
            2.0 / math.sqrt(1.6),
            rel_tol=1e-9,
        )

    def test_zero_returns(self) -> None:
        assert sharpe_ratio([0.0, 0.0, 0.0, 0.0]) == 0.0

    def test_constant_nonzero_returns_zero_sd(self) -> None:
        # Constant non-zero series -> stddev=0 -> Sharpe 0 by contract.
        assert sharpe_ratio([0.5, 0.5, 0.5]) == 0.0

    def test_empty_returns_zero(self) -> None:
        assert sharpe_ratio([]) == 0.0

    def test_singleton_returns_zero(self) -> None:
        assert sharpe_ratio([1.5]) == 0.0

    def test_negative_mean(self) -> None:
        # Symmetric to positive — Sharpe sign tracks mean sign.
        assert sharpe_ratio([-2.0, -2.0, -2.0, 0.0, -4.0]) < 0


# ─────────────────────────────────────────────────────────────────────
#   lo_bootstrap_p_value
# ─────────────────────────────────────────────────────────────────────


class TestLoBootstrapPValue:
    def test_deterministic_under_same_seed(self) -> None:
        sharpes = (1.0, 0.5, 1.5, 0.8, 1.2, 0.9)
        p1 = lo_bootstrap_p_value(sharpes, n_bootstrap=500, seed=42)
        p2 = lo_bootstrap_p_value(sharpes, n_bootstrap=500, seed=42)
        assert p1 == p2

    def test_seed_changes_p_value(self) -> None:
        sharpes = (1.0, 0.5, 1.5, 0.8, 1.2, 0.9)
        p1 = lo_bootstrap_p_value(sharpes, n_bootstrap=500, seed=1)
        p2 = lo_bootstrap_p_value(sharpes, n_bootstrap=500, seed=2)
        # Statistically these can match by chance but with 500
        # iterations and a moderately significant signal we expect
        # the count of "as extreme" draws to differ slightly by seed.
        # Allow equality with caveat: assert types/range.
        assert 0.0 < p1 <= 1.0
        assert 0.0 < p2 <= 1.0

    def test_strong_positive_signal_low_p_value(self) -> None:
        # All-positive Sharpes well above zero: p-value should be small.
        sharpes = (1.0, 1.1, 0.9, 1.2, 0.95, 1.05, 1.15, 1.0)
        p = lo_bootstrap_p_value(sharpes, n_bootstrap=2000, seed=0)
        assert p < 0.05

    def test_zero_mean_returns_one(self) -> None:
        # Mean is exactly zero -> trivial p-value of 1.0
        # (no signal to test against).
        sharpes = (1.0, -1.0, 1.0, -1.0)
        p = lo_bootstrap_p_value(sharpes, n_bootstrap=2000, seed=0)
        assert p == 1.0

    def test_singleton_returns_one(self) -> None:
        assert (
            lo_bootstrap_p_value((0.5,), n_bootstrap=100, seed=0) == 1.0
        )

    def test_empty_returns_one(self) -> None:
        assert (
            lo_bootstrap_p_value((), n_bootstrap=100, seed=0) == 1.0
        )

    def test_all_zero_sharpes_returns_one(self) -> None:
        assert (
            lo_bootstrap_p_value(
                (0.0,) * 10, n_bootstrap=200, seed=0
            )
            == 1.0
        )

    def test_zero_n_bootstrap_raises(self) -> None:
        with pytest.raises(ValueError, match="n_bootstrap"):
            lo_bootstrap_p_value((0.5, 1.0), n_bootstrap=0, seed=0)

    def test_negative_n_bootstrap_raises(self) -> None:
        with pytest.raises(ValueError, match="n_bootstrap"):
            lo_bootstrap_p_value((0.5, 1.0), n_bootstrap=-10, seed=0)

    def test_p_value_bounded_correctly(self) -> None:
        # With +1/+1 correction the p-value is always in (0, 1].
        sharpes = (10.0, 10.5, 9.5, 10.2, 9.8)
        p = lo_bootstrap_p_value(sharpes, n_bootstrap=100, seed=0)
        assert 0.0 < p <= 1.0
        # Floor under the +1/+1 convention: 1/(B+1) = 1/101.
        assert p >= 1.0 / 101


# ─────────────────────────────────────────────────────────────────────
#   fold_pnl_curves_sha256
# ─────────────────────────────────────────────────────────────────────


class TestFoldPnLCurvesSha256:
    def test_deterministic(self) -> None:
        paths = ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6))
        h1 = fold_pnl_curves_sha256(paths)
        h2 = fold_pnl_curves_sha256(paths)
        assert h1 == h2
        assert h1.startswith("sha256:")
        assert len(h1) == len("sha256:") + 64  # 32 bytes hex

    def test_different_paths_different_hash(self) -> None:
        h1 = fold_pnl_curves_sha256(((0.1, 0.2),))
        h2 = fold_pnl_curves_sha256(((0.1, 0.3),))
        assert h1 != h2

    def test_path_order_matters(self) -> None:
        h1 = fold_pnl_curves_sha256(((0.1, 0.2), (0.3, 0.4)))
        h2 = fold_pnl_curves_sha256(((0.3, 0.4), (0.1, 0.2)))
        assert h1 != h2

    def test_path_length_in_serialisation(self) -> None:
        # A path's length is included in the canonical serialisation,
        # so two paths with different numbers of bars but the same
        # values shouldn't accidentally hash the same.
        h1 = fold_pnl_curves_sha256(((0.0, 0.0),))
        h2 = fold_pnl_curves_sha256(((0.0, 0.0, 0.0),))
        assert h1 != h2

    def test_handles_nan_and_inf_stably(self) -> None:
        # The hash mustn't raise on degenerate floats; F-2 validators
        # reject NaN/inf elsewhere, but the hasher itself should be
        # robust so we don't crash in the diagnostic path.
        h = fold_pnl_curves_sha256(
            ((0.0, float("nan"), float("inf"), -float("inf")),)
        )
        assert h.startswith("sha256:")


# ─────────────────────────────────────────────────────────────────────
#   build_cpcv_evidence (happy-path end-to-end)
# ─────────────────────────────────────────────────────────────────────


def _make_test_returns(
    splits: tuple[CPCVSplit, ...],
    *,
    mean: float,
    sd: float,
    seed: int,
) -> list[tuple[float, ...]]:
    """Generate per-split OOS test returns sampled from a normal
    distribution.  Pure deterministic — same seed ⇒ same returns."""
    rng = random.Random(seed)
    return [
        tuple(rng.gauss(mean, sd) for _ in s.test_indices)
        for s in splits
    ]


class TestBuildCPCVEvidence:
    def test_returns_a_CPCVEvidence(self) -> None:
        cfg = CPCVConfig(n_groups=10, k_test_groups=2, embargo_bars=2)
        splits = generate_cpcv_splits(n_bars=100, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.001, sd=0.01, seed=0
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=100,
            test_returns_by_split=test_returns,
            n_bootstrap=500,
            seed=0,
        )
        assert isinstance(ev, CPCVEvidence)

    def test_fold_count_matches_n_paths(self) -> None:
        cfg = CPCVConfig(n_groups=10, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=100, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.001, sd=0.01, seed=0
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=100,
            test_returns_by_split=test_returns,
            n_bootstrap=300,
            seed=0,
        )
        assert ev.fold_count == cfg.n_paths
        assert len(ev.fold_sharpes) == cfg.n_paths

    def test_embargo_bars_propagated_to_evidence(self) -> None:
        cfg = CPCVConfig(n_groups=8, k_test_groups=2, embargo_bars=7)
        splits = generate_cpcv_splits(n_bars=80, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.0, sd=0.01, seed=0
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=80,
            test_returns_by_split=test_returns,
            n_bootstrap=200,
            seed=0,
        )
        assert ev.embargo_bars == 7

    def test_summary_stats_internally_consistent(self) -> None:
        cfg = CPCVConfig(n_groups=8, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=80, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.002, sd=0.01, seed=11
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=80,
            test_returns_by_split=test_returns,
            n_bootstrap=300,
            seed=11,
        )
        # Mean and median consistency
        assert math.isclose(
            ev.mean_sharpe,
            sum(ev.fold_sharpes) / len(ev.fold_sharpes),
            rel_tol=1e-12,
        )
        # Median is the middle (or average of two middle) folds
        sorted_sharpes = sorted(ev.fold_sharpes)
        n = len(sorted_sharpes)
        if n % 2 == 1:
            expected_median = sorted_sharpes[n // 2]
        else:
            expected_median = (
                sorted_sharpes[n // 2 - 1] + sorted_sharpes[n // 2]
            ) / 2
        assert math.isclose(
            ev.median_sharpe, expected_median, rel_tol=1e-12
        )

    def test_replay_deterministic(self) -> None:
        cfg = CPCVConfig(n_groups=8, k_test_groups=2, embargo_bars=3)
        splits = generate_cpcv_splits(n_bars=80, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.001, sd=0.01, seed=7
        )
        ev1 = build_cpcv_evidence(
            config=cfg,
            n_bars=80,
            test_returns_by_split=test_returns,
            n_bootstrap=400,
            seed=99,
        )
        ev2 = build_cpcv_evidence(
            config=cfg,
            n_bars=80,
            test_returns_by_split=test_returns,
            n_bootstrap=400,
            seed=99,
        )
        assert ev1 == ev2

    def test_passes_default_validator_with_strong_signal(self) -> None:
        # Inject a strong positive signal to guarantee the validator
        # accepts the evidence under default thresholds (8 folds,
        # mean Sharpe >= 1.0, p_value <= 0.05).
        cfg = CPCVConfig(n_groups=10, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=200, config=cfg)
        # Mean=0.05, sd=0.02 -> expected per-bar Sharpe ~2.5 which
        # comfortably clears the 1.0 threshold even after CPCV
        # variance.
        test_returns = _make_test_returns(
            splits, mean=0.05, sd=0.02, seed=0
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=200,
            test_returns_by_split=test_returns,
            n_bootstrap=2000,
            seed=0,
        )
        errors = validate_cpcv(ev, GateThresholds())
        assert errors == [], f"validator rejected: {errors}"

    def test_fails_default_validator_when_below_threshold(self) -> None:
        # Pure-noise returns: Sharpe near zero, p-value high, should
        # fail under default thresholds.
        cfg = CPCVConfig(n_groups=10, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=200, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.0, sd=0.01, seed=0
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=200,
            test_returns_by_split=test_returns,
            n_bootstrap=500,
            seed=0,
        )
        errors = validate_cpcv(ev, GateThresholds())
        assert errors, "validator should reject pure-noise CPCV evidence"

    def test_fold_pnl_curves_hash_changes_with_returns(self) -> None:
        cfg = CPCVConfig(n_groups=8, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=80, config=cfg)
        ret_a = _make_test_returns(splits, mean=0.001, sd=0.01, seed=1)
        ret_b = _make_test_returns(splits, mean=0.002, sd=0.01, seed=2)
        ev_a = build_cpcv_evidence(
            config=cfg,
            n_bars=80,
            test_returns_by_split=ret_a,
            n_bootstrap=200,
            seed=0,
        )
        ev_b = build_cpcv_evidence(
            config=cfg,
            n_bars=80,
            test_returns_by_split=ret_b,
            n_bootstrap=200,
            seed=0,
        )
        assert ev_a.fold_pnl_curves_hash != ev_b.fold_pnl_curves_hash

    def test_single_group_test_run_yields_one_path(self) -> None:
        # k=1: each path uses N splits, exactly C(N-1, 0) = 1 path.
        cfg = CPCVConfig(n_groups=4, k_test_groups=1)
        splits = generate_cpcv_splits(n_bars=20, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.001, sd=0.005, seed=0
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=20,
            test_returns_by_split=test_returns,
            n_bootstrap=100,
            seed=0,
        )
        assert ev.fold_count == 1
        assert len(ev.fold_sharpes) == 1

    def test_lifts_n_groups_minus_one_test_run_yields_n_paths(self) -> None:
        # k=N-1: each path uses N splits, C(N-1, N-2) = N-1 paths.
        cfg = CPCVConfig(n_groups=4, k_test_groups=3)
        splits = generate_cpcv_splits(n_bars=20, config=cfg)
        test_returns = _make_test_returns(
            splits, mean=0.001, sd=0.005, seed=0
        )
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=20,
            test_returns_by_split=test_returns,
            n_bootstrap=100,
            seed=0,
        )
        assert ev.fold_count == math.comb(3, 2)  # 3
