"""Forward-return and information-coefficient utilities.

Pure-Python (stdlib only — no numpy/scipy, matching ``research/cpcv`` and
``research/dsr``) tooling to validate a feature's *directional* edge: the
Spearman rank information coefficient (IC) of a feature value against the
forward return over a fixed horizon, plus an equal-count bucketed
conditional-forward-return view.

Use these measures to confirm or refute the sign convention of
``sig_inventory_revert_v1`` — does a positive
``quote_replenish_asymmetry_zscore`` predict a *positive* forward
30-second micro-price return (LONG), or is the sign inverted/absent?  The
alpha's own comment flags this as unconfirmed; this module is the
measurement tool.  Re-run via a custom replay harness that imports this module
and the alpha's sensor stack on cached L1 NBBO.

Statistics notes:

* Spearman ρ is Pearson correlation on average-tie ranks.
* The two-sided p-value uses the Fisher z-transform normal approximation
  ``z = atanh(ρ) * sqrt(n - 3)`` — adequate for n >> 3 and avoids a scipy
  dependency.  Treat it as indicative, not exact, for small n.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ICResult:
    """Result of a Spearman IC computation."""

    rho: float
    n: int
    p_value: float

    def __str__(self) -> str:
        return f"Spearman IC rho={self.rho:+.4f}  n={self.n}  p~={self.p_value:.4g}"


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Return 1-based average ranks; ties share the mean of their ranks."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    n = len(values)
    while i < n:
        j = i + 1
        while j < n and values[order[j]] == values[order[i]]:
            j += 1
        mean_rank = (i + 1 + j) / 2.0  # mean of 1-based ranks (i+1 .. j)
        for k in range(i, j):
            ranks[order[k]] = mean_rank
        i = j
    return ranks


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    vx = sum((xi - mx) ** 2 for xi in x)
    vy = sum((yi - my) ** 2 for yi in y)
    if vx == 0.0 or vy == 0.0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def spearman_ic(
    feature: Sequence[float],
    forward_return: Sequence[float],
) -> ICResult:
    """Spearman rank IC of *feature* vs *forward_return*.

    Non-finite pairs (NaN/inf in either array) are dropped pairwise.
    Requires at least 3 valid pairs; raises ``ValueError`` otherwise.
    Returns ``rho=0.0`` when either side is constant.
    """
    if len(feature) != len(forward_return):
        raise ValueError(
            f"feature and forward_return must align: {len(feature)} != {len(forward_return)}"
        )
    pairs = [
        (float(a), float(b))
        for a, b in zip(feature, forward_return)
        if math.isfinite(a) and math.isfinite(b)
    ]
    n = len(pairs)
    if n < 3:
        raise ValueError(f"need >= 3 finite paired observations, got {n}")

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    rho = _pearson(_average_ranks(xs), _average_ranks(ys))
    rho = max(-1.0, min(1.0, rho))

    if rho == 0.0:
        return ICResult(rho=0.0, n=n, p_value=1.0)
    if abs(rho) >= 1.0:
        return ICResult(rho=rho, n=n, p_value=0.0)
    if n <= 3:
        return ICResult(rho=rho, n=n, p_value=1.0)

    z = math.atanh(rho) * math.sqrt(n - 3)
    p_value = math.erfc(abs(z) / math.sqrt(2.0))
    return ICResult(rho=rho, n=n, p_value=p_value)


@dataclass(frozen=True)
class Bucket:
    """One feature-value bucket and its conditional forward return."""

    lo: float
    hi: float
    n: int
    mean_forward_return: float


def bucketed_forward_return(
    feature: Sequence[float],
    forward_return: Sequence[float],
    *,
    n_buckets: int = 5,
) -> list[Bucket]:
    """Equal-count (rank) buckets of *feature*, mean forward return each.

    A monotone progression of ``mean_forward_return`` across buckets is the
    signature of a real conditional edge; a flat or non-monotone profile
    says the feature is not predictive of forward direction.
    """
    if len(feature) != len(forward_return):
        raise ValueError(
            f"feature and forward_return must align: {len(feature)} != {len(forward_return)}"
        )
    pairs = [
        (float(a), float(b))
        for a, b in zip(feature, forward_return)
        if math.isfinite(a) and math.isfinite(b)
    ]
    if len(pairs) < n_buckets:
        raise ValueError(f"need >= n_buckets ({n_buckets}) observations, got {len(pairs)}")
    pairs.sort(key=lambda p: p[0])
    n = len(pairs)
    out: list[Bucket] = []
    for b in range(n_buckets):
        lo_i = (b * n) // n_buckets
        hi_i = ((b + 1) * n) // n_buckets
        if hi_i <= lo_i:
            continue
        group = pairs[lo_i:hi_i]
        rets = [p[1] for p in group]
        out.append(
            Bucket(
                lo=group[0][0],
                hi=group[-1][0],
                n=len(group),
                mean_forward_return=sum(rets) / len(rets),
            )
        )
    return out


def long_short_edge_bps(
    feature: Sequence[float],
    forward_return: Sequence[float],
    *,
    n_buckets: int = 5,
) -> float:
    """Gross long-short edge of the feature, in basis points.

    The mean-forward-return spread between the **top** and **bottom** feature
    buckets — i.e. what a market-neutral "long the top bucket, short the bottom
    bucket" book earns *gross* per decision, expressed in bps
    (``(top.mean − bottom.mean) * 1e4``).  Positive ⇒ the feature is a momentum
    signal (high feature → high forward return); negative ⇒ contrarian.

    This is the quantity the tradability / cost gate compares against round-trip
    cost (Inv-12: the *captured* edge must exceed ~1.5× round-trip cost).  A
    RankIC can be statistically significant yet imply an edge far below the
    cost hurdle — especially at short horizons — so this is the binding check
    for fast-horizon features, not RankIC alone.
    """
    buckets = bucketed_forward_return(feature, forward_return, n_buckets=n_buckets)
    if len(buckets) < 2:
        return float("nan")
    return (buckets[-1].mean_forward_return - buckets[0].mean_forward_return) * 1e4


def forward_return_at(
    times_ns: Sequence[int],
    mids: Sequence[float],
    anchor_ns: int,
    horizon_seconds: float,
) -> float:
    """Forward return from the mid at-or-before *anchor_ns* to the mid
    at-or-after ``anchor_ns + horizon``.

    Returns NaN when either endpoint cannot be located (e.g. the anchor is
    within ``horizon`` of the end of the series).  ``times_ns`` must be
    sorted ascending.
    """
    horizon_ns = int(horizon_seconds * 1_000_000_000)
    target_ns = anchor_ns + horizon_ns
    i0 = bisect.bisect_right(times_ns, anchor_ns) - 1
    i1 = bisect.bisect_left(times_ns, target_ns)
    if i0 < 0 or i1 >= len(times_ns):
        return float("nan")
    base = mids[i0]
    if base == 0.0 or not math.isfinite(base):
        return float("nan")
    return mids[i1] / base - 1.0


__all__ = [
    "ICResult",
    "Bucket",
    "spearman_ic",
    "bucketed_forward_return",
    "long_short_edge_bps",
    "forward_return_at",
]
