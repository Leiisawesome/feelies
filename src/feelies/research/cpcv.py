"""Combinatorial Purged Cross-Validation (CPCV) — Workstream **C-1**.

CPCV is the statistical-significance procedure the platform uses to
compute :class:`feelies.alpha.promotion_evidence.CPCVEvidence` for the
``RESEARCH → PAPER`` and ``PAPER → LIVE`` promotion gates.  This
module implements the algorithm in pure Python (stdlib only, no
numpy / scipy) so it is bit-identical across hosts and replays
deterministically (Inv-5).

Reference
=========

López de Prado, *Advances in Financial Machine Learning* (2018), §12
("Cross-Validation in Finance") and §7 ("Cross-Validation in
Finance").  The algorithm partitions the time series into ``N``
contiguous groups, generates every ``k``-out-of-``N`` test
combination (``φ = C(N, k)`` total), purges any training-set bar
whose label window overlaps a test-set bar (here implemented as a
straightforward index-overlap purge), embargoes the ``e`` bars
immediately following each test region from training, and then
reconstructs ``C(N-1, k-1)`` distinct full-length backtest paths
from the resulting predictions — each path covering every bar
exactly once but each bar's prediction sourced from a different
combination, giving a *distribution* of full-length backtest
results rather than a single point estimate.

Public API
==========

- :class:`CPCVConfig`            — immutable hyperparameters.
- :class:`CPCVSplit`             — one (combination, test-groups,
  purged train-indices) tuple.
- :func:`assign_groups`          — partition ``[0, n_bars)`` into
  ``N`` contiguous groups (uneven splits land the remainder in the
  early groups, as is conventional).
- :func:`generate_cpcv_splits`   — produce all ``φ`` splits with
  purging + embargo applied to the train indices.
- :func:`reconstruct_paths`      — build the
  ``C(N-1, k-1)`` full-length backtest paths.
- :func:`assemble_path_returns`  — stitch per-split test returns
  into the ``n_bars``-long return series for each path.
- :func:`sharpe_ratio`           — population-style Sharpe (mean /
  stddev), 0.0 on degenerate inputs.
- :func:`lo_bootstrap_p_value`   — two-sided bootstrap p-value for
  ``H0: mean Sharpe = 0`` over the per-path Sharpes.
- :func:`fold_pnl_curves_sha256` — content-addressable hash of the
  per-path PnL curves.
- :func:`build_cpcv_evidence`    — top-level entry-point: emit
  :class:`feelies.alpha.promotion_evidence.CPCVEvidence`.

Determinism
===========

Every public function in this module is a pure function of its
arguments.  The only stochastic element is the bootstrap p-value,
which uses :class:`random.Random` seeded by the caller — so repeated
calls with the same ``seed`` and the same fold-Sharpe sequence
produce a bit-identical p-value (Inv-5).  The
``fold_pnl_curves_hash`` is computed via :mod:`hashlib.sha256` over
a canonical floating-point textualisation of the path returns and
is therefore stable across operating systems and Python builds
(the canonical formatter is :func:`_canonical_float_repr`).

Caveats
=======

This module *organises* per-split OOS test returns into paths and
computes the resulting Sharpe distribution; it does **not** retrain
models.  The caller is expected to have run a CPCV-style backtest
(a separate training run per combination) and to pass the
per-split realised OOS test returns in the order matching
:attr:`CPCVSplit.test_indices`.  See :func:`build_cpcv_evidence`'s
docstring for the contract.

The bootstrap p-value treats the per-path Sharpes as observations
from an unknown distribution and bootstraps the *centred* sample
to assess ``H0: mean Sharpe = 0``.  This implicitly assumes the
across-path correlation is benign; in practice CPCV paths share
most bars and are correlated, so the resulting p-value is a
conservative-leaning *summary* statistic suitable for the F-2
gate threshold ``cpcv_max_p_value`` and not a publication-grade
significance test on its own.  The post-trade-forensics skill
documents the further checks (e.g. block-bootstrap on the
underlying per-bar returns) that supplement this evidence at the
LIVE-promotion review.
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
    "build_cpcv_evidence",
    "fold_pnl_curves_sha256",
    "generate_cpcv_splits",
    "lo_bootstrap_p_value",
    "reconstruct_paths",
    "sharpe_ratio",
]


# ─────────────────────────────────────────────────────────────────────
#   Hyperparameters and split records
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class CPCVConfig:
    """Immutable hyperparameters for a single CPCV run.

    Attributes
    ----------
    n_groups
        Number of contiguous time groups (``N`` in López de Prado's
        notation).  Must satisfy ``n_groups >= 2``.
    k_test_groups
        Number of groups held out as the test set per combination
        (``k`` in the notation).  Must satisfy
        ``1 <= k_test_groups < n_groups``.
    embargo_bars
        Number of bars immediately following each test region
        excluded from training, to guard against serial-correlation
        leakage from the immediate post-test bars.  Must be
        ``>= 0``.
    """

    n_groups: int
    k_test_groups: int
    embargo_bars: int = 0

    def __post_init__(self) -> None:
        if self.n_groups < 2:
            raise ValueError(
                f"CPCVConfig.n_groups must be >= 2 (got {self.n_groups})"
            )
        if not (1 <= self.k_test_groups < self.n_groups):
            raise ValueError(
                f"CPCVConfig.k_test_groups must satisfy "
                f"1 <= k < n_groups (got k={self.k_test_groups}, "
                f"n_groups={self.n_groups})"
            )
        if self.embargo_bars < 0:
            raise ValueError(
                f"CPCVConfig.embargo_bars must be >= 0 "
                f"(got {self.embargo_bars})"
            )

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


def assign_groups(
    n_bars: int, n_groups: int
) -> tuple[tuple[int, ...], ...]:
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
        raise ValueError(
            f"need at least one bar per group: n_bars={n_bars} "
            f"< n_groups={n_groups}"
        )

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
    embargo_bars: int,
    n_bars: int,
) -> tuple[int, ...]:
    """Return the training bar indices given the test set,
    after applying purge + embargo.

    Purge: any bar whose index lies in the test set is removed from
    training (the simple index-overlap purge appropriate when
    *labels* are computed at the bar boundary itself; if the alpha
    uses overlapping label windows the caller should pass a wider
    test set or pre-purge the returns themselves before calling
    :func:`build_cpcv_evidence`).

    Embargo: the ``embargo_bars`` bars immediately following each
    *contiguous test region* are also excluded from training.  The
    embargo is one-sided (post-test only) by convention, since
    causal alphas only leak forward through serial correlation.
    """
    test_set = set(test_indices)

    embargoed: set[int] = set()
    if embargo_bars > 0 and test_indices:
        in_region = False
        region_end = -1
        for i in range(n_bars):
            if i in test_set:
                if not in_region:
                    in_region = True
                region_end = i
            else:
                if in_region:
                    in_region = False
                    for j in range(
                        region_end + 1,
                        min(region_end + 1 + embargo_bars, n_bars),
                    ):
                        if j not in test_set:
                            embargoed.add(j)

    return tuple(
        i
        for i in range(n_bars)
        if i not in test_set and i not in embargoed
    )


def generate_cpcv_splits(
    n_bars: int, config: CPCVConfig
) -> tuple[CPCVSplit, ...]:
    """Generate the ``φ = C(N, k)`` train/test splits.

    Splits are emitted in the lexicographic order of
    ``itertools.combinations(range(n_groups), k_test_groups)``.  The
    enumeration is deterministic so repeated calls with identical
    ``(n_bars, config)`` produce the *same* sequence of
    :class:`CPCVSplit` records — replay determinism (Inv-5) holds
    by construction, and the F-3 ``feelies promote replay-evidence``
    CLI re-derives bit-identical fold sharpes.
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
            test_indices_tuple, config.embargo_bars, n_bars
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
    """Reconstruct ``C(N-1, k-1)`` full-length backtest paths.

    Each returned path is a length-``n_groups`` tuple of split
    indices: ``path[g]`` is the index into ``splits`` whose test
    set contributed group ``g``'s OOS predictions for that path.
    The same combination may appear multiple times in a single
    path — this is correct: a combination that tests ``k`` groups
    contributes the predictions for all ``k`` of those groups in
    every path it participates in.

    The algorithm is the standard López de Prado §12.5 procedure:

    1. For each group ``g``, list the splits whose ``test_group_ids``
       contains ``g``, in the canonical order produced by
       :func:`generate_cpcv_splits` (which is itself the lex order of
       ``itertools.combinations``).  This list has exactly
       ``C(N-1, k-1)`` entries.
    2. Path ``p`` for ``p ∈ [0, C(N-1, k-1))`` is the tuple of
       ``splits_by_group[g][p]`` for ``g`` in ``[0, n_groups)``.

    Paths are returned in lex order over their split-index tuples,
    so the enumeration is replay-stable.

    Raises ``ValueError`` if the supplied ``splits`` are missing or
    duplicated (e.g. came from a different :class:`CPCVConfig`).
    """
    expected_per_group = math.comb(n_groups - 1, k_test_groups - 1)

    splits_by_group: dict[int, list[int]] = {
        g: [] for g in range(n_groups)
    }
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
        paths.append(
            tuple(splits_by_group[g][p] for g in range(n_groups))
        )
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
            f"len(test_returns_by_split)={len(test_returns_by_split)} "
            f"!= len(splits)={len(splits)}"
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
            raise ValueError(
                f"path length {len(path)} != n_groups={n_groups}"
            )
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
    """Sample Sharpe ratio = mean(returns) / stddev(returns).

    Uses the *population* standard deviation (``ddof=0``) — the same
    convention as the F-2 ``CPCVEvidence`` defaults and the
    testing-validation skill's worked examples.  Returns ``0.0``
    when fewer than two observations are available or when the
    standard deviation is exactly zero (degenerate cases that should
    contribute zero "edge" in the bootstrap distribution).

    The mean and standard deviation are evaluated on the series
    after dividing by ``max_i |r_i|`` when that scale is non-zero.
    This is algebraically identical to ``mean/sd`` but avoids
    spurious ``std == 0`` / ``mean == 0`` artifacts from IEEE-754
    underflow when returns span extremely small magnitudes yet are
    not strictly constant — preserving positive-scale invariance for
    :func:`statistics.fmean` / :func:`statistics.pstdev`.

    No annualisation is applied: the returned number has the units
    of the *input series* (i.e. per-bar).  The caller is expected
    to know whether the input is per-bar / per-day / per-period and
    annualise externally if needed; the F-2 threshold defaults
    (``cpcv_min_mean_sharpe = 1.0``) are stated in *whatever unit
    the alpha hands in*, so the contract here is simply "compute
    Sharpe over the supplied series and we'll check it against the
    threshold the alpha author chose."
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
    """Two-sided bootstrap p-value for ``H0: mean Sharpe = 0``.

    Algorithm
    ---------
    1. Compute the observed mean Sharpe ``μ̂``.
    2. Centre: ``c_i = sharpes[i] - μ̂``.  These have mean exactly
       ``0`` and are an empirical sample under H0.
    3. For ``n_bootstrap`` iterations: draw ``len(sharpes)`` samples
       from the centred sequence with replacement and compute the
       resampled mean.
    4. Two-sided p-value: ``P(|resampled_mean| >= |μ̂|)``.  Following
       the standard convention, the count is ``+1`` in both
       numerator and denominator to avoid a zero p-value when the
       observation is more extreme than every bootstrap draw — see
       Davison & Hinkley (1997) §4.2.

    Determinism
    -----------
    Uses a :class:`random.Random` instance seeded by ``seed``.  Two
    invocations with the same ``(sharpes, n_bootstrap, seed)``
    return a bit-identical p-value (Inv-5).

    Caveats
    -------
    The per-path Sharpes from CPCV are correlated (paths share most
    bars), so this bootstrap is a *summary* statistic and not a
    rigorous independence-bootstrap p-value.  The resulting
    p-value is appropriate for the F-2 ``cpcv_max_p_value`` gate
    threshold but should be supplemented with the post-trade-
    forensics block-bootstrap on the underlying per-bar returns
    when reviewing a candidate for the LIVE-promotion gate.

    Edge cases
    ----------
    - ``len(sharpes) < 2``: returns ``1.0`` (no evidence).
    - All-zero ``sharpes``: returns ``1.0`` (the centred sequence
      is identically zero, every resample is zero, so the
      observation is exactly the bootstrap mean).
    - ``n_bootstrap <= 0``: ``ValueError`` (zero iterations is a
      configuration mistake, not a degenerate case).
    """
    if n_bootstrap <= 0:
        raise ValueError(
            f"n_bootstrap must be >= 1 (got {n_bootstrap})"
        )
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
    happen to include them; the F-2 validators independently
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
    review time (the F-2 ``CPCVEvidence`` only stores the hash, not
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
    n_bootstrap: int = 10_000,
    seed: int = 0,
) -> CPCVEvidence:
    """End-to-end CPCV evidence builder.

    Workflow
    --------
    1. Generate ``φ = C(N, k)`` splits with purging + embargo
       applied to the train indices (the caller is responsible for
       having retrained their model on each split's
       ``train_indices`` and produced OOS test predictions in the
       order matching ``splits[s].test_indices``).
    2. Reconstruct ``C(N-1, k-1)`` full-length backtest paths.
    3. Assemble per-path return series.
    4. Compute per-path Sharpes, summary stats, bootstrap p-value,
       and content-addressable hash.
    5. Emit a :class:`CPCVEvidence` ready for
       :func:`feelies.alpha.promotion_evidence.validate_gate` against
       :data:`feelies.alpha.promotion_evidence.GateId.PAPER_TO_LIVE`.

    Inputs
    ------
    config
        Hyperparameters.  See :class:`CPCVConfig`.
    n_bars
        Length of the original return series.  Must satisfy
        ``n_bars >= config.n_groups`` (so each group has at least
        one bar).
    test_returns_by_split
        Per-split realised OOS test returns: a sequence whose
        ``s``-th element is the sequence of returns produced by the
        caller's model — trained on ``splits[s].train_indices`` —
        for the bars listed in ``splits[s].test_indices`` (in that
        same order).  The contract is checked at runtime by
        :func:`assemble_path_returns`.
    n_bootstrap
        Bootstrap iterations for the across-path p-value.  Default
        ``10_000`` matches the testing-validation skill's stated
        floor for promotion-gate evidence.
    seed
        Bootstrap seed.  Two builds with the same ``seed`` and the
        same ``test_returns_by_split`` produce a bit-identical
        evidence package (Inv-5).

    Determinism
    -----------
    Pure function.  No I/O, no clock reads, no global state.
    """
    splits = generate_cpcv_splits(n_bars, config)
    paths = reconstruct_paths(
        config.n_groups, config.k_test_groups, splits
    )
    paths_returns = assemble_path_returns(
        n_bars=n_bars,
        n_groups=config.n_groups,
        splits=splits,
        test_returns_by_split=test_returns_by_split,
        paths=paths,
    )

    fold_sharpes = tuple(sharpe_ratio(p) for p in paths_returns)
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
    p_value = lo_bootstrap_p_value(
        fold_sharpes, n_bootstrap=n_bootstrap, seed=seed
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
