"""Pinned reference vectors for :mod:`feelies.research.cpcv`.

These tests fix the *floating-point output* of the CPCV pipeline to
hand-computed or computed-once-then-locked golden values.  Any
algorithmic regression — even one that preserves the structural
invariants the unit + property suites cover — will move at least
one of the pinned numbers and trip a clear, focused test.

Coverage
--------

1. :func:`generate_cpcv_splits` — pinned ``test_indices`` /
   ``train_indices`` for the canonical N=4 / k=2 / embargo=1
   reference run.
2. :func:`build_cpcv_evidence` — full ``CPCVEvidence`` payload
   pinned for two reference runs:

   - **identity-returns**: each split's OOS test returns equal the
     bar indices themselves, so every path's return series is
     identical and the per-path Sharpes are all equal to the
     analytical mean / pstdev of [0, …, n-1].
   - **split-perturbed-returns**: each split injects a tiny
     split-index-dependent offset, so per-path Sharpes diverge by
     a known amount.  Pins ``fold_sharpes``,
     ``mean_sharpe``, ``median_sharpe``, ``mean_pnl``, ``p_value``,
     and ``fold_pnl_curves_hash``.

3. :func:`lo_bootstrap_p_value` — pinned p-value for a fixed Sharpe
   vector + seed + bootstrap count.

4. :func:`fold_pnl_curves_sha256` — pinned hash for a fixed return
   matrix.

The hashes lock the **canonical float repr + comma-separated
serialisation** in :mod:`feelies.research.cpcv`; if those are ever
adjusted, the corresponding reference value here must be updated
in the same PR (and reviewers should verify the migration was
intentional).
"""

from __future__ import annotations

import math
import statistics

from feelies.alpha.promotion_evidence import (
    GateThresholds,
    validate_cpcv,
)
from feelies.research.cpcv import (
    CPCVConfig,
    build_cpcv_evidence,
    fold_pnl_curves_sha256,
    generate_cpcv_splits,
    lo_bootstrap_p_value,
    sharpe_ratio,
)


# ─────────────────────────────────────────────────────────────────────
#   Pinned generate_cpcv_splits output (N=4, k=2, embargo=1)
# ─────────────────────────────────────────────────────────────────────


class TestGenerateCPCVSplitsReference:
    def test_n4_k2_embargo1_pinned_splits(self) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2, embargo_bars=1)
        splits = generate_cpcv_splits(n_bars=8, config=cfg)
        assert len(splits) == 6

        # Group layout: [0,1] / [2,3] / [4,5] / [6,7].
        expected = [
            # (combination_index, test_group_ids, test_indices, train_indices)
            (0, (0, 1), (0, 1, 2, 3), (5, 6, 7)),
            # Combination (0,2): test bars {0,1,4,5}; group 0 ends
            # at bar 1 -> embargo bar 2 (a non-test bar); group 2
            # ends at bar 5 -> embargo bar 6.
            (1, (0, 2), (0, 1, 4, 5), (3, 7)),
            (2, (0, 3), (0, 1, 6, 7), (3, 4, 5)),
            (3, (1, 2), (2, 3, 4, 5), (0, 1, 7)),
            (4, (1, 3), (2, 3, 6, 7), (0, 1, 5)),
            # Final combination tests groups (2, 3) -> bars 4..7
            # consecutively; embargo would extend beyond n_bars and
            # is therefore truncated, leaving train = full prefix.
            (5, (2, 3), (4, 5, 6, 7), (0, 1, 2, 3)),
        ]

        for got, want in zip(splits, expected, strict=True):
            ci, tg, ti, tr = want
            assert got.combination_index == ci
            assert got.test_group_ids == tg
            assert got.test_indices == ti
            assert got.train_indices == tr


# ─────────────────────────────────────────────────────────────────────
#   Pinned reconstruct_paths output
# ─────────────────────────────────────────────────────────────────────


class TestReconstructPathsReference:
    """Path enumeration for the canonical N=4 / k=2 reference is
    derived in the C-1 design notes.  Pin it here so any future
    refactor of the path-construction algorithm has to migrate the
    expectation explicitly."""

    def test_n4_k2_paths_match_design_doc(self) -> None:
        from feelies.research.cpcv import reconstruct_paths

        cfg = CPCVConfig(n_groups=4, k_test_groups=2)
        splits = generate_cpcv_splits(n_bars=8, config=cfg)
        paths = reconstruct_paths(
            cfg.n_groups, cfg.k_test_groups, splits
        )
        # Per design-doc derivation:
        #   group 0 testing splits: [0, 1, 2]
        #   group 1 testing splits: [0, 3, 4]
        #   group 2 testing splits: [1, 3, 5]
        #   group 3 testing splits: [2, 4, 5]
        # paths (zip-by-position):
        assert paths == ((0, 0, 1, 2), (1, 3, 3, 4), (2, 4, 5, 5))


# ─────────────────────────────────────────────────────────────────────
#   Pinned build_cpcv_evidence — identity-returns reference
# ─────────────────────────────────────────────────────────────────────


class TestBuildCPCVEvidenceIdentityReturns:
    """Each split's OOS prediction at bar ``i`` is just ``float(i)``,
    so every reconstructed path is the same series ``[0.0, …, 7.0]``
    and the per-path Sharpes are all equal to the analytical
    mean/pstdev of the integers 0..7."""

    def _expected_path_sharpe(self) -> float:
        # mean(0..7) = 3.5; pstdev(0..7) = sqrt(variance) where
        # variance = sum((i - 3.5)**2)/8 = 5.25.
        return 3.5 / math.sqrt(5.25)

    def test_n4_k2_identity_returns_pinned_evidence(self) -> None:
        cfg = CPCVConfig(n_groups=4, k_test_groups=2, embargo_bars=0)
        splits = generate_cpcv_splits(n_bars=8, config=cfg)
        test_returns = [
            tuple(float(i) for i in s.test_indices) for s in splits
        ]

        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=8,
            test_returns_by_split=test_returns,
            n_bootstrap=100,
            seed=42,
        )

        expected_sharpe = self._expected_path_sharpe()

        # 3 paths reconstructed (C(N-1, k-1) = C(3, 1) = 3).
        assert ev.fold_count == 3
        assert ev.embargo_bars == 0

        # Every path is the same series so every Sharpe is identical
        # to the analytical value.  We use math.isclose rather than
        # equality because statistics.fmean on three identical floats
        # may round-trip through one ULP.
        for s in ev.fold_sharpes:
            assert math.isclose(s, expected_sharpe, rel_tol=1e-12)

        assert math.isclose(
            ev.median_sharpe, expected_sharpe, rel_tol=1e-12
        )
        assert math.isclose(
            ev.mean_sharpe, expected_sharpe, rel_tol=1e-12
        )

        # Each path's PnL is sum(0..7) = 28.0; mean across 3 paths = 28.0.
        assert ev.mean_pnl == 28.0

        # All path Sharpes are identical, so the *centred* sample
        # is identically zero — every bootstrap resample's mean is
        # therefore exactly 0.  The observed mean Sharpe is
        # ``1.5275…``, much larger in absolute value than 0, so the
        # "as extreme as observed" count is 0 and the bootstrap
        # collapses to the +1/+1 floor: ``1 / (B + 1) = 1 / 101``.
        assert ev.p_value == 1 / 101

        # Hash is deterministic: pin the prefix so a refactor of the
        # canonical-float-repr in cpcv.py is caught here.  We check
        # the structural prefix and the byte-length of the hex tail;
        # the full value is locked by the cross-platform property
        # tests in test_cpcv_props.py.
        assert ev.fold_pnl_curves_hash.startswith("sha256:")
        assert len(ev.fold_pnl_curves_hash) == len("sha256:") + 64


# ─────────────────────────────────────────────────────────────────────
#   Pinned build_cpcv_evidence — split-perturbed-returns reference
# ─────────────────────────────────────────────────────────────────────


class TestBuildCPCVEvidenceSplitPerturbedReturns:
    """Each split injects a small split-index-dependent offset so
    paths actually differ.  Locks every emitted CPCVEvidence field
    including the bootstrap p-value and content-addressable hash."""

    def test_n6_k2_embargo2_pinned_evidence(self) -> None:
        cfg = CPCVConfig(n_groups=6, k_test_groups=2, embargo_bars=2)
        splits = generate_cpcv_splits(n_bars=30, config=cfg)
        # Per-split OOS return for bar i in split s:
        #     r = bar_idx * 1e-3 + split_idx * 1e-4
        test_returns = [
            tuple(
                bi * 0.001 + sidx * 0.0001
                for bi in s.test_indices
            )
            for sidx, s in enumerate(splits)
        ]

        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=30,
            test_returns_by_split=test_returns,
            n_bootstrap=200,
            seed=7,
        )

        # Pinned scalars (computed once and locked here):
        assert ev.fold_count == 5
        assert ev.embargo_bars == 2
        assert ev.fold_sharpes == (
            1.6666786234834272,
            1.6971325386809162,
            1.711318347117981,
            1.7206809607751885,
            1.7308884836955287,
        )
        assert math.isclose(ev.mean_sharpe, 1.705339790750608, rel_tol=1e-12)
        assert ev.median_sharpe == 1.711318347117981
        assert math.isclose(ev.mean_pnl, 0.456, abs_tol=1e-12)
        assert ev.p_value == 0.004975124378109453
        assert (
            ev.fold_pnl_curves_hash
            == "sha256:906b0329678980b0cab7b8a2cc71e4c85110a4a2f6e4edabaf99a04a7bda170c"
        )

    def test_evidence_passes_validator_under_relaxed_thresholds(self) -> None:
        """Pinned evidence has only 5 folds, below the platform
        default ``cpcv_min_folds=8``.  Verify it nonetheless passes
        a relaxed-threshold validator when fold_count is honoured —
        proving the threshold-comparison plumbing in the validator
        is connected to the right field."""
        cfg = CPCVConfig(n_groups=6, k_test_groups=2, embargo_bars=2)
        splits = generate_cpcv_splits(n_bars=30, config=cfg)
        test_returns = [
            tuple(
                bi * 0.001 + sidx * 0.0001
                for bi in s.test_indices
            )
            for sidx, s in enumerate(splits)
        ]
        ev = build_cpcv_evidence(
            config=cfg,
            n_bars=30,
            test_returns_by_split=test_returns,
            n_bootstrap=200,
            seed=7,
        )
        relaxed = GateThresholds(
            cpcv_min_folds=4, cpcv_min_mean_sharpe=1.0
        )
        errors = validate_cpcv(ev, relaxed)
        assert errors == [], f"validator rejected: {errors}"


# ─────────────────────────────────────────────────────────────────────
#   Pinned lo_bootstrap_p_value reference
# ─────────────────────────────────────────────────────────────────────


class TestLoBootstrapPValueReference:
    """The bootstrap p-value depends on the order in which
    :class:`random.Random` draws samples — so a refactor that
    silently changes the call pattern (e.g. swapping
    ``rng.choices`` for an explicit per-iteration loop) will
    surface here."""

    def test_strong_signal_pinned(self) -> None:
        sharpes = (1.0, 0.8, 1.2, 0.9, 1.1, 1.05, 0.95, 1.15)
        p = lo_bootstrap_p_value(
            sharpes, n_bootstrap=10_000, seed=12345
        )
        # Strong, clean signal: every centred-resample mean is
        # bounded by the largest centred deviation, so the
        # observation lands at the +1/+1 floor.
        assert p == 9.999000099990002e-05

    def test_zero_mean_pinned(self) -> None:
        # Symmetric sharpes about zero -> mean is zero -> early-out
        # returns 1.0 (no signal).
        sharpes = (1.0, -1.0, 1.0, -1.0)
        assert lo_bootstrap_p_value(
            sharpes, n_bootstrap=200, seed=0
        ) == 1.0

    def test_singleton_pinned(self) -> None:
        assert lo_bootstrap_p_value(
            (0.5,), n_bootstrap=100, seed=0
        ) == 1.0


# ─────────────────────────────────────────────────────────────────────
#   Pinned fold_pnl_curves_sha256 reference
# ─────────────────────────────────────────────────────────────────────


class TestFoldPnLCurvesSha256Reference:
    """Lock the canonical float-repr + comma-serialisation; the
    test_cpcv_unit suite already covers the structural properties."""

    def test_simple_pinned_hash(self) -> None:
        paths = ((0.1, 0.2, 0.3), (0.4, 0.5, 0.6))
        h = fold_pnl_curves_sha256(paths)
        # Computed once via the canonical formatter:
        #   "2\n3,0.1,0.2,0.3\n3,0.4,0.5,0.6\n"
        # sha256-hex pinned below.
        expected_serialisation = (
            b"2\n"
            b"3,0.1,0.2,0.3\n"
            b"3,0.4,0.5,0.6\n"
        )
        import hashlib as _hashlib

        expected_hash = (
            "sha256:" + _hashlib.sha256(expected_serialisation).hexdigest()
        )
        assert h == expected_hash

    def test_empty_paths_hash_pinned(self) -> None:
        # Even an empty input must produce a stable hash so the
        # F-2 ``CPCVEvidence`` round-trip never crashes when an
        # operator submits a stub package without the heavy
        # artefact.
        h = fold_pnl_curves_sha256(())
        # Canonical serialisation: "0\n".
        import hashlib as _hashlib

        expected = (
            "sha256:" + _hashlib.sha256(b"0\n").hexdigest()
        )
        assert h == expected


# ─────────────────────────────────────────────────────────────────────
#   Pinned sharpe_ratio reference (sanity check for the analytical
#   value used by the identity-returns evidence test)
# ─────────────────────────────────────────────────────────────────────


class TestSharpeRatioReference:
    def test_zero_through_seven(self) -> None:
        # mean = 3.5, pstdev = sqrt(5.25)
        s = sharpe_ratio(list(range(8)))
        assert math.isclose(s, 3.5 / math.sqrt(5.25), rel_tol=1e-12)

    def test_values_match_statistics_module(self) -> None:
        # cross-check our implementation against statistics directly
        rs = [0.01, -0.005, 0.02, 0.0, 0.015, -0.01, 0.005]
        ours = sharpe_ratio(rs)
        ref = statistics.fmean(rs) / statistics.pstdev(rs)
        assert math.isclose(ours, ref, rel_tol=1e-12)
