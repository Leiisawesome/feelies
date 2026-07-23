"""Deterministic Combinatorial Purged Cross-Validation evidence.

The algorithm partitions time into contiguous groups, enumerates test-group
combinations, purges overlapping labels, applies a post-test embargo, and
reconstructs full-length out-of-sample paths. It organizes caller-supplied OOS
returns; it does not train models.

Gate evidence uses a seeded circular block bootstrap over mean per-bar OOS
returns, preserving serial dependence and avoiding degenerate path-level Sharpe
bootstrap results. Canonical float serialization keeps PnL hashes stable.
"""

from __future__ import annotations

import hashlib
import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from feelies.alpha.promotion_evidence import CPCVEvidence

__all__ = [
    "CPCVConfig",
    "CPCVSplit",
    "assemble_path_returns",
    "assign_groups",
    "block_bootstrap_p_value",
    "build_cpcv_evidence",
    "fold_pnl_curves_sha256",
    "generate_cpcv_splits",
    "lo_bootstrap_p_value",
    "mean_path_return_per_bar",
    "reconstruct_paths",
    "sharpe_ratio",
]


# ─────────────────────────────────────────────────────────────────────
#   Hyperparameters and split records
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class CPCVConfig:
    """Immutable CPCV hyperparameters.

    ``label_horizon_bars`` purges overlapping label windows on both sides of
    each test region. ``embargo_bars`` additionally removes bars immediately
    after the region. Both must be nonnegative.
    """

    n_groups: int
    k_test_groups: int
    label_horizon_bars: int = 0
    embargo_bars: int = 0

    def __post_init__(self) -> None:
        if self.n_groups < 2:
            raise ValueError(f"CPCVConfig.n_groups must be >= 2 (got {self.n_groups})")
        if not (1 <= self.k_test_groups < self.n_groups):
            raise ValueError(
                f"CPCVConfig.k_test_groups must satisfy "
                f"1 <= k < n_groups (got k={self.k_test_groups}, "
                f"n_groups={self.n_groups})"
            )
        if self.label_horizon_bars < 0:
            raise ValueError(
                f"CPCVConfig.label_horizon_bars must be >= 0 (got {self.label_horizon_bars})"
            )
        if self.embargo_bars < 0:
            raise ValueError(f"CPCVConfig.embargo_bars must be >= 0 (got {self.embargo_bars})")

    @property
    def n_combinations(self) -> int:
        """``φ = C(N, k)`` — number of distinct test combinations
        and therefore the number of training-set rebuilds the
        caller's CPCV backtest must perform."""
        return math.comb(self.n_groups, self.k_test_groups)

    @property
    def n_paths(self) -> int:
        """``C(N-1, k-1)`` — number of distinct full-length backtest
        paths the per-split test predictions can be reassembled
        into.  Equivalently each group is in test for exactly this
        many combinations."""
        return math.comb(self.n_groups - 1, self.k_test_groups - 1)


@dataclass(frozen=True, kw_only=True)
class CPCVSplit:
    """One ``(combination, test groups, purged train indices)``
    record produced by :func:`generate_cpcv_splits`.

    Attributes
    ----------
    combination_index
        0-based index into the lex-ordered enumeration of
        ``itertools.combinations(range(n_groups), k_test_groups)``.
        Stable across replays (the enumeration is deterministic).
    test_group_ids
        The ``k`` group ids comprising the test set, in ascending
        order.
    test_indices
        Bar indices in the test set, in ascending order.
        ``len(test_indices) == sum(group_size[g] for g in
        test_group_ids)``.
    train_indices
        Bar indices remaining in training **after** the purge +
        embargo step.  May be empty for pathological hyperparameters
        (e.g. an embargo so large that every bar would be embargoed
        out); the caller is responsible for handling that case.
    """

    combination_index: int
    test_group_ids: tuple[int, ...]
    test_indices: tuple[int, ...]
    train_indices: tuple[int, ...]


# ─────────────────────────────────────────────────────────────────────
#   Group assignment
# ─────────────────────────────────────────────────────────────────────


def assign_groups(n_bars: int, n_groups: int) -> tuple[tuple[int, ...], ...]:
    """Partition ``[0, n_bars)`` into ``n_groups`` contiguous groups.

    When ``n_bars`` is not a multiple of ``n_groups`` the remainder
    ``n_bars % n_groups`` is distributed one extra bar at a time
    over the *first* groups — the standard convention used in
    López de Prado §12 and the scikit-learn ``KFold`` implementation
    so that group sizes never differ by more than one.

    Returns a tuple of length ``n_groups``; each inner tuple holds
    the bar indices belonging to that group, in ascending order.

    Raises ``ValueError`` if ``n_bars < n_groups`` (a partition with
    empty groups is not meaningful).
    """
    if n_groups < 1:
        raise ValueError(f"n_groups must be >= 1 (got {n_groups})")
    if n_bars < n_groups:
        raise ValueError(f"need at least one bar per group: n_bars={n_bars} < n_groups={n_groups}")

    base, extra = divmod(n_bars, n_groups)
    out: list[tuple[int, ...]] = []
    cursor = 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)
        out.append(tuple(range(cursor, cursor + size)))
        cursor += size
    return tuple(out)


# ─────────────────────────────────────────────────────────────────────
#   Combination enumeration + purge + embargo
# ─────────────────────────────────────────────────────────────────────


def _purged_train_indices(
    test_indices: tuple[int, ...],
    label_horizon_bars: int,
    embargo_bars: int,
    n_bars: int,
) -> tuple[int, ...]:
    """Return the training bar indices given the test set, after
    applying the López de Prado purge + embargo (*AFML* 2018, §7.4).

    Purge (§7.4.1): a training observation whose label window overlaps
    a test observation's label window is removed.  With a forward
    label span of ``label_horizon_bars`` (``h``), two length-``h``
    windows at bars ``j`` and ``t`` overlap iff ``|j - t| <= h``, so
    every contiguous test region ``[a, b]`` purges the ``h`` training
    bars on **both** sides — ``[a - h, a - 1]`` (backward) and the
    forward window below.  At ``h == 0`` this collapses to removing
    only the exact test indices (the historical behaviour, so existing
    pinned references are unchanged).

    Embargo (§7.4.2): an *additional* ``embargo_bars`` bars beyond the
    forward purge window are excluded after each region, suppressing
    serial-correlation leakage.  The forward exclusion is therefore
    ``[b + 1, b + h + embargo_bars]``; the embargo is one-sided
    (post-test only) by convention, since causal alphas leak forward
    through serial correlation.

    Both windows are clipped to ``[0, n_bars)`` and never re-add a
    test bar to training.
    """
    test_set = set(test_indices)
    if not test_indices:
        return tuple(range(n_bars))

    # Collapse the (ascending) test indices into contiguous regions.
    sorted_test = sorted(test_set)
    regions: list[tuple[int, int]] = []
    a = prev = sorted_test[0]
    for cur in sorted_test[1:]:
        if cur == prev + 1:
            prev = cur
        else:
            regions.append((a, prev))
            a = prev = cur
    regions.append((a, prev))

    excluded: set[int] = set()
    for region_start, region_end in regions:
        # Backward label-overlap purge: [a - h, a - 1].
        for j in range(max(0, region_start - label_horizon_bars), region_start):
            excluded.add(j)
        # Forward label-overlap purge (h) + serial-correlation embargo:
        # [b + 1, b + h + embargo_bars].
        for j in range(
            region_end + 1,
            min(region_end + 1 + label_horizon_bars + embargo_bars, n_bars),
        ):
            excluded.add(j)

    return tuple(i for i in range(n_bars) if i not in test_set and i not in excluded)


def generate_cpcv_splits(n_bars: int, config: CPCVConfig) -> tuple[CPCVSplit, ...]:
    """Generate the ``φ = C(N, k)`` train/test splits.

    Splits are emitted in the lexicographic order of
    ``itertools.combinations(range(n_groups), k_test_groups)``.  The
    enumeration is deterministic so repeated calls with identical
    ``(n_bars, config)`` produce the *same* sequence of
    :class:`CPCVSplit` records, allowing the evidence-replay CLI to
    re-derive identical fold Sharpes.
    """
    groups = assign_groups(n_bars, config.n_groups)

    from itertools import combinations as _combinations

    splits: list[CPCVSplit] = []
    for idx, test_group_ids in enumerate(
        _combinations(range(config.n_groups), config.k_test_groups)
    ):
        test_indices: list[int] = []
        for g in test_group_ids:
            test_indices.extend(groups[g])
        test_indices.sort()
        test_indices_tuple = tuple(test_indices)

        train_indices = _purged_train_indices(
            test_indices_tuple,
            config.label_horizon_bars,
            config.embargo_bars,
            n_bars,
        )

        splits.append(
            CPCVSplit(
                combination_index=idx,
                test_group_ids=tuple(test_group_ids),
                test_indices=test_indices_tuple,
                train_indices=train_indices,
            )
        )
    return tuple(splits)


# ─────────────────────────────────────────────────────────────────────
#   Path reconstruction
# ─────────────────────────────────────────────────────────────────────


def reconstruct_paths(
    n_groups: int,
    k_test_groups: int,
    splits: Sequence[CPCVSplit],
) -> tuple[tuple[int, ...], ...]:
    """Reconstruct ``C(N-1, k-1)`` replay-stable full-length paths.

    ``path[g]`` names the split supplying group ``g``. Missing or duplicate
    split combinations raise ``ValueError``.
    """
    expected_per_group = math.comb(n_groups - 1, k_test_groups - 1)

    splits_by_group: dict[int, list[int]] = {g: [] for g in range(n_groups)}
    for split_idx, split in enumerate(splits):
        for g in split.test_group_ids:
            splits_by_group[g].append(split_idx)

    for g, lst in splits_by_group.items():
        if len(lst) != expected_per_group:
            raise ValueError(
                f"reconstruct_paths: group {g} appears in {len(lst)} "
                f"splits but expected {expected_per_group} = "
                f"C({n_groups - 1}, {k_test_groups - 1}); did the "
                f"caller pass splits from a different CPCVConfig?"
            )

    paths: list[tuple[int, ...]] = []
    for p in range(expected_per_group):
        paths.append(tuple(splits_by_group[g][p] for g in range(n_groups)))
    paths.sort()
    return tuple(paths)


# ─────────────────────────────────────────────────────────────────────
#   Assembling per-path return series
# ─────────────────────────────────────────────────────────────────────


def assemble_path_returns(
    *,
    n_bars: int,
    n_groups: int,
    splits: Sequence[CPCVSplit],
    test_returns_by_split: Sequence[Sequence[float]],
    paths: Sequence[Sequence[int]],
) -> tuple[tuple[float, ...], ...]:
    """For each path, stitch a length-``n_bars`` chronological
    return series from per-split OOS test returns.

    Inputs
    ------
    n_bars
        Total number of bars in the original time series.
    n_groups
        Number of CPCV groups (must match the run that produced
        ``splits`` and ``paths``).
    splits
        The :class:`CPCVSplit` records from
        :func:`generate_cpcv_splits`.
    test_returns_by_split
        Per-split OOS test returns, in the same order as
        ``splits[s].test_indices`` for each ``s``.  ``len(...) ==
        len(splits)``; ``len(test_returns_by_split[s]) ==
        len(splits[s].test_indices)`` (otherwise ``ValueError``).
    paths
        The path enumeration from :func:`reconstruct_paths`.

    Output
    ------
    A tuple of ``len(paths)`` inner tuples; each inner tuple has
    length ``n_bars`` and gives the path's full-length return
    series in chronological bar-index order.

    Causality
    ---------
    The function is pure: same inputs ⇒ same output, byte-identical
    across hosts.  No clock reads, no PRNG, no global state.
    """
    if len(test_returns_by_split) != len(splits):
        raise ValueError(
            f"len(test_returns_by_split)={len(test_returns_by_split)} != len(splits)={len(splits)}"
        )
    for s, split in enumerate(splits):
        if len(test_returns_by_split[s]) != len(split.test_indices):
            raise ValueError(
                f"split {s}: returned {len(test_returns_by_split[s])} "
                f"OOS returns but the split has "
                f"{len(split.test_indices)} test indices"
            )

    groups = assign_groups(n_bars, n_groups)
    bar_to_group = [0] * n_bars
    for g, members in enumerate(groups):
        for i in members:
            bar_to_group[i] = g

    # For each split, build a dict {bar_idx: oos_return} so the
    # path-stitching loop below can look up returns in O(1).  We
    # rely on the contract that test_returns_by_split[s] is in
    # the same order as splits[s].test_indices.
    by_split_lookup: list[dict[int, float]] = []
    for s, split in enumerate(splits):
        by_split_lookup.append(
            {
                bar_idx: float(ret)
                for bar_idx, ret in zip(
                    split.test_indices,
                    test_returns_by_split[s],
                    strict=True,
                )
            }
        )

    out: list[tuple[float, ...]] = []
    for path in paths:
        if len(path) != n_groups:
            raise ValueError(f"path length {len(path)} != n_groups={n_groups}")
        path_returns: list[float] = []
        for bar_idx in range(n_bars):
            g = bar_to_group[bar_idx]
            split_idx = path[g]
            try:
                path_returns.append(by_split_lookup[split_idx][bar_idx])
            except KeyError as exc:
                raise ValueError(
                    f"bar {bar_idx} (group {g}) not found in test set "
                    f"of split {split_idx}; path/splits mismatch"
                ) from exc
        out.append(tuple(path_returns))
    return tuple(out)


# ─────────────────────────────────────────────────────────────────────
#   Sharpe ratio
# ─────────────────────────────────────────────────────────────────────


def sharpe_ratio(returns: Sequence[float]) -> float:
    """Return unannualized population ``mean / stddev``.

    Scaling by the largest absolute return prevents underflow without changing
    the ratio. Fewer than two or constant observations return ``0.0``.
    """
    if len(returns) < 2:
        return 0.0
    scale = 0.0
    for x in returns:
        ax = abs(x)
        if ax > scale:
            scale = ax
    if scale == 0.0:
        return 0.0
    scaled = [x / scale for x in returns]
    mean = statistics.fmean(scaled)
    sd = statistics.pstdev(scaled)
    if sd == 0.0:
        return 0.0
    return mean / sd


# ─────────────────────────────────────────────────────────────────────
#   Bootstrap p-value
# ─────────────────────────────────────────────────────────────────────


def lo_bootstrap_p_value(
    sharpes: Sequence[float],
    *,
    n_bootstrap: int = 10_000,
    seed: int = 0,
) -> float:
    """Bootstrap ``H0: mean Sharpe = 0`` with a deterministic seed.

    This compatibility helper resamples centered path Sharpes. Gate evidence
    uses :func:`block_bootstrap_p_value` because CPCV paths are correlated.
    Fewer than two or all-zero Sharpes return ``1.0``.
    """
    if n_bootstrap <= 0:
        raise ValueError(f"n_bootstrap must be >= 1 (got {n_bootstrap})")
    n = len(sharpes)
    if n < 2:
        return 1.0
    mu = statistics.fmean(sharpes)
    if mu == 0.0:
        return 1.0
    centred = [s - mu for s in sharpes]
    abs_mu = abs(mu)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(n_bootstrap):
        # Random.choices is deterministic given the seed.
        sample_mean = sum(rng.choices(centred, k=n)) / n
        if abs(sample_mean) >= abs_mu:
            extreme += 1
    return (extreme + 1) / (n_bootstrap + 1)


def mean_path_return_per_bar(
    paths_returns: Sequence[Sequence[float]],
) -> tuple[float, ...]:
    """Per-bar mean OOS return across all reconstructed paths.

    Each CPCV path is a full-length per-bar return series over the
    *same* bars; their per-bar average is the natural pooled OOS
    return at each bar and the series :func:`block_bootstrap_p_value`
    tests.  Under an identity-model OOS projection (every path equal)
    this recovers the original return series exactly.

    Returns the empty tuple for an empty path set.  Raises
    ``ValueError`` if the paths are not all the same length.
    """
    if not paths_returns:
        return ()
    n_bars = len(paths_returns[0])
    for p in paths_returns:
        if len(p) != n_bars:
            raise ValueError("mean_path_return_per_bar: all paths must have equal length")
    k = len(paths_returns)
    return tuple(sum(float(p[i]) for p in paths_returns) / k for i in range(n_bars))


def block_bootstrap_p_value(
    returns: Sequence[float],
    *,
    block_size: int,
    n_bootstrap: int = 10_000,
    seed: int = 0,
) -> float:
    """Circular-block bootstrap for ``H0: mean return = 0``.

    Centered blocks wrap around the series, preserving serial dependence.
    ``block_size=1`` gives an iid bootstrap. The seeded result is deterministic;
    fewer than two or all-equal returns yield ``1.0``.
    """
    if n_bootstrap <= 0:
        raise ValueError(f"n_bootstrap must be >= 1 (got {n_bootstrap})")
    if block_size <= 0:
        raise ValueError(f"block_size must be >= 1 (got {block_size})")
    n = len(returns)
    if n < 2:
        return 1.0
    observed = sharpe_ratio(returns)
    if observed == 0.0:
        return 1.0
    mean = statistics.fmean(returns)
    centred = [float(r) - mean for r in returns]
    block = min(block_size, n)
    n_blocks = -(-n // block)  # ceil division
    abs_obs = abs(observed)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(n_bootstrap):
        sample: list[float] = []
        for _ in range(n_blocks):
            start = rng.randrange(n)
            for offset in range(block):
                sample.append(centred[(start + offset) % n])
        if abs(sharpe_ratio(sample[:n])) >= abs_obs:
            extreme += 1
    return (extreme + 1) / (n_bootstrap + 1)


# ─────────────────────────────────────────────────────────────────────
#   Content-addressable hash for fold PnL curves
# ─────────────────────────────────────────────────────────────────────


def _canonical_float_repr(x: float) -> str:
    """Stable cross-platform textualisation of a finite float.

    Uses :func:`repr` on a ``float`` — Python's :func:`repr` is
    guaranteed by CPython to produce the *shortest* string that
    round-trips back to the exact same float (PEP 3101 / IEEE-754
    binary → decimal short-representation), so the result is
    bit-identical across operating systems and Python builds at
    the same minor version.

    NaN and ±inf are explicitly mapped to fixed strings so the
    hash is stable even when the caller's per-path returns
    happen to include them; validators independently
    reject finite-value violations elsewhere in the pipeline.
    """
    if math.isnan(x):
        return "nan"
    if math.isinf(x):
        return "+inf" if x > 0 else "-inf"
    return repr(float(x))


def fold_pnl_curves_sha256(
    paths_returns: Sequence[Sequence[float]],
) -> str:
    """Content-addressable ``sha256:<hex>`` hash of the per-path PnL
    curves.

    The canonical serialisation is::

        n_paths\\n
        len_path_0,r_0_0,r_0_1,...,r_0_{T-1}\\n
        len_path_1,r_1_0,...\\n
        ...

    where each ``r_i_j`` is :func:`_canonical_float_repr`-formatted.
    Cumulative PnL curves are derived from the per-bar returns at
    review time (``CPCVEvidence`` stores only the hash, not
    the heavy artefact); pinning the hash on the *return series*
    rather than a derived cumulative curve keeps the hash stable
    against future PnL-derivation conventions.
    """
    sha = hashlib.sha256()
    sha.update(f"{len(paths_returns)}\n".encode())
    for path in paths_returns:
        parts = [str(len(path))]
        parts.extend(_canonical_float_repr(r) for r in path)
        sha.update((",".join(parts) + "\n").encode())
    return f"sha256:{sha.hexdigest()}"


# ─────────────────────────────────────────────────────────────────────
#   Top-level entry-point
# ─────────────────────────────────────────────────────────────────────


def build_cpcv_evidence(
    *,
    config: CPCVConfig,
    n_bars: int,
    test_returns_by_split: Sequence[Sequence[float]],
    annualization_factor: float = 1.0,
    n_bootstrap: int = 10_000,
    seed: int = 0,
) -> CPCVEvidence:
    """Build deterministic CPCV evidence from per-split OOS returns.

    Generates purged splits, reconstructs full paths, then computes path
    Sharpes, a block-bootstrap p-value, and the artifact hash. Returns for each
    split must follow that split's ``test_indices`` order. The positive
    ``annualization_factor`` scales Sharpes only; the p-value is unchanged.
    """
    if annualization_factor <= 0.0:
        raise ValueError(
            f"build_cpcv_evidence requires annualization_factor > 0, got {annualization_factor}"
        )
    splits = generate_cpcv_splits(n_bars, config)
    paths = reconstruct_paths(config.n_groups, config.k_test_groups, splits)
    paths_returns = assemble_path_returns(
        n_bars=n_bars,
        n_groups=config.n_groups,
        splits=splits,
        test_returns_by_split=test_returns_by_split,
        paths=paths,
    )

    fold_sharpes = tuple(sharpe_ratio(p) * annualization_factor for p in paths_returns)
    fold_count = len(fold_sharpes)

    if fold_count == 0:
        # Defensive: should never happen — config.__post_init__
        # already requires n_groups >= 2 and 1 <= k < n_groups,
        # both of which yield C(N-1, k-1) >= 1.
        raise ValueError(  # pragma: no cover
            "internal error: zero CPCV paths reconstructed; "
            "did config validation drift from this assertion?"
        )

    mean_sharpe = statistics.fmean(fold_sharpes)
    median_sharpe = statistics.median(fold_sharpes)
    mean_pnl = statistics.fmean(sum(p) for p in paths_returns)
    # Block-bootstrap the per-bar pooled OOS return (not the correlated
    # per-path Sharpes) so the p-value is non-degenerate and respects
    # serial correlation; block length = the declared embargo (>= 1).
    representative = mean_path_return_per_bar(paths_returns)
    p_value = block_bootstrap_p_value(
        representative,
        block_size=max(1, config.embargo_bars),
        n_bootstrap=n_bootstrap,
        seed=seed,
    )
    fold_pnl_curves_hash = fold_pnl_curves_sha256(paths_returns)

    return CPCVEvidence(
        fold_count=fold_count,
        embargo_bars=config.embargo_bars,
        fold_sharpes=fold_sharpes,
        mean_sharpe=mean_sharpe,
        median_sharpe=median_sharpe,
        mean_pnl=mean_pnl,
        p_value=p_value,
        fold_pnl_curves_hash=fold_pnl_curves_hash,
    )
