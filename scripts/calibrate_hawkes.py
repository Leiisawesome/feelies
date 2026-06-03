#!/usr/bin/env python3
"""Hawkes (exp-kernel) MLE calibration for ``hawkes_intensity`` (audit P1-4b).

Read-only. Fits the univariate exponential-kernel Hawkes intensity

    λ(t) = μ + α · Σ_{t_j < t} exp(-β (t - t_j))

to cached trade arrival times (per side and combined) by maximum
likelihood, so ``α, β`` for a new ``hawkes_intensity`` sensor version can
be chosen from **data** instead of the hand-set ``α=0.4, β=0.05``
(``α/β = 8``).  Reports the fitted ``μ, α, β``, the impulse-decay ratio
``α/β``, the decay half-life ``ln2/β``, and the stationarity branching
ratio ``α/β`` (for a *true* Hawkes process this must be < 1).

Pure-Python (no scipy/numpy): O(n) recursive log-likelihood + a compact
Nelder-Mead simplex optimiser in log-parameter space (keeps μ, α, β > 0).

Usage
-----
    uv run python scripts/calibrate_hawkes.py \
        --cache-dir data/cache --symbol AAPL --date 2026-03-26 \
        [--target-half-life 30]
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    os.chdir(_REPO_ROOT)

from feelies.core.events import Trade  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402

_NS_PER_SECOND = 1_000_000_000


# ── Exp-kernel Hawkes log-likelihood (O(n) recursion) ────────────────────


def _neg_log_likelihood(ts: Sequence[float], mu: float, alpha: float, beta: float) -> float:
    """Negative log-likelihood of an exp-kernel Hawkes on ``ts`` (seconds,
    ascending, starting at 0).  Returns +inf for invalid params."""
    if mu <= 0.0 or alpha <= 0.0 or beta <= 0.0:
        return math.inf
    n = len(ts)
    if n < 2:
        return math.inf
    T = ts[-1]
    # Sum of log intensities at event times via the standard recursion
    #   A_i = exp(-β Δ)(1 + A_{i-1}),  A_1 = 0.
    log_term = 0.0
    A = 0.0
    prev = ts[0]
    # i = 0 contributes log(mu) (A_0 = 0).
    log_term += math.log(mu)
    for i in range(1, n):
        dt = ts[i] - prev
        A = math.exp(-beta * dt) * (1.0 + A)
        intensity = mu + alpha * A
        if intensity <= 0.0:
            return math.inf
        log_term += math.log(intensity)
        prev = ts[i]
    # Compensator ∫_0^T λ = μT + (α/β) Σ (1 - exp(-β(T - t_i))).
    comp = mu * T
    ab = alpha / beta
    for t in ts:
        comp += ab * (1.0 - math.exp(-beta * (T - t)))
    return -(log_term - comp)


# ── Nelder-Mead in log-parameter space (positivity by construction) ──────


def _nelder_mead(
    f: Callable[[list[float]], float],
    x0: list[float],
    *,
    iters: int = 400,
    step: float = 0.5,
) -> tuple[list[float], float]:
    n = len(x0)
    simplex = [list(x0)]
    for i in range(n):
        x = list(x0)
        x[i] += step
        simplex.append(x)
    fvals = [f(x) for x in simplex]

    a, g, r, s = 1.0, 2.0, 0.5, 0.5  # reflect, expand, contract, shrink
    for _ in range(iters):
        order = sorted(range(n + 1), key=lambda i: fvals[i])
        simplex = [simplex[i] for i in order]
        fvals = [fvals[i] for i in order]
        if abs(fvals[-1] - fvals[0]) < 1e-9:
            break
        centroid = [sum(simplex[i][d] for i in range(n)) / n for d in range(n)]
        # Reflection
        xr = [centroid[d] + a * (centroid[d] - simplex[-1][d]) for d in range(n)]
        fr = f(xr)
        if fvals[0] <= fr < fvals[-2]:
            simplex[-1], fvals[-1] = xr, fr
            continue
        if fr < fvals[0]:
            xe = [centroid[d] + g * (xr[d] - centroid[d]) for d in range(n)]
            fe = f(xe)
            if fe < fr:
                simplex[-1], fvals[-1] = xe, fe
            else:
                simplex[-1], fvals[-1] = xr, fr
            continue
        xc = [centroid[d] + r * (simplex[-1][d] - centroid[d]) for d in range(n)]
        fc = f(xc)
        if fc < fvals[-1]:
            simplex[-1], fvals[-1] = xc, fc
            continue
        # Shrink
        for i in range(1, n + 1):
            simplex[i] = [simplex[0][d] + s * (simplex[i][d] - simplex[0][d]) for d in range(n)]
            fvals[i] = f(simplex[i])
    best = min(range(n + 1), key=lambda i: fvals[i])
    return simplex[best], fvals[best]


@dataclass
class _Fit:
    label: str
    n: int
    mu: float
    alpha: float
    beta: float

    @property
    def half_life(self) -> float:
        return math.log(2.0) / self.beta if self.beta > 0 else float("inf")

    @property
    def ratio(self) -> float:
        return self.alpha / self.beta if self.beta > 0 else float("inf")


def _fit(ts_ns: Sequence[int], label: str) -> _Fit | None:
    if len(ts_ns) < 10:
        return None
    t0 = ts_ns[0]
    ts = [(t - t0) / _NS_PER_SECOND for t in ts_ns]
    # Note: exact-duplicate timestamps yield dt=0.0 gaps; the recursion remains
    # well-defined under dt=0, so we keep the full series as-is.
    n = len(ts)
    # Initial guess: μ ≈ baseline rate, β ≈ 1/median gap, α ≈ 0.5 β.
    gaps = sorted(ts[i] - ts[i - 1] for i in range(1, n) if ts[i] > ts[i - 1])
    med_gap = gaps[len(gaps) // 2] if gaps else 1.0
    mu0 = max(n / ts[-1] * 0.5, 1e-6)
    beta0 = 1.0 / max(med_gap, 1e-3)
    alpha0 = 0.5 * beta0
    x0 = [math.log(mu0), math.log(alpha0), math.log(beta0)]

    def obj(theta: list[float]) -> float:
        mu, alpha, beta = math.exp(theta[0]), math.exp(theta[1]), math.exp(theta[2])
        return _neg_log_likelihood(ts, mu, alpha, beta)

    best, _ = _nelder_mead(obj, x0)
    mu, alpha, beta = math.exp(best[0]), math.exp(best[1]), math.exp(best[2])
    return _Fit(label=label, n=n, mu=mu, alpha=alpha, beta=beta)


# ── Side classification (tick rule, matching the sensor) ─────────────────


def _split_sides(trades: list[Trade]) -> tuple[list[int], list[int]]:
    buys: list[int] = []
    sells: list[int] = []
    last_price: float | None = None
    last_side = +1
    for tr in trades:
        price = float(tr.price)
        if last_price is None:
            side = last_side
        elif price > last_price:
            side = +1
        elif price < last_price:
            side = -1
        else:
            side = last_side
        last_price, last_side = price, side
        (buys if side > 0 else sells).append(tr.timestamp_ns)
    return buys, sells


def _report(fit: _Fit | None, target_hl: float) -> None:
    if fit is None:
        print(f"  {'':<8}insufficient trades")
        return
    stable = "OK (<1)" if fit.ratio < 1.0 else "UNSTABLE (>=1)"
    rec_beta = math.log(2.0) / target_hl
    print(
        f"  {fit.label:<8} n={fit.n:>6}  mu={fit.mu:.4g}  alpha={fit.alpha:.4g}  "
        f"beta={fit.beta:.4g}  a/b={fit.ratio:.3f} [{stable}]  "
        f"half_life={fit.half_life:.1f}s"
    )
    print(
        f"           → for a {target_hl:.0f}s half-life target use "
        f"beta≈{rec_beta:.4g}; pick alpha<beta (e.g. alpha≈{0.5 * rec_beta:.4g}) "
        f"for a stationary kernel."
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", required=True, type=Path)
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--target-half-life", type=float, default=30.0,
                    help="Target decay half-life in seconds (default 30).")
    args = ap.parse_args(argv)

    cache = DiskEventCache(args.cache_dir)
    events = cache.load(args.symbol, args.date)
    if not events:
        print(f"No cached events for {args.symbol}/{args.date}", file=sys.stderr)
        return 1
    trades = sorted(
        (e for e in events if isinstance(e, Trade)),
        key=lambda e: (e.timestamp_ns, e.sequence),
    )
    if len(trades) < 10:
        print(f"Too few trades ({len(trades)}) to fit", file=sys.stderr)
        return 1

    buys, sells = _split_sides(trades)
    all_ts = [t.timestamp_ns for t in trades]

    print(f"# Hawkes MLE fit — {args.symbol} {args.date} ({len(trades)} trades)")
    _report(_fit(all_ts, "all"), args.target_half_life)
    _report(_fit(buys, "buy"), args.target_half_life)
    _report(_fit(sells, "sell"), args.target_half_life)
    print(
        "\nApply the chosen (alpha, beta) as a new hawkes_intensity "
        "sensor_version (P1-4b); keep 1.2.0 for replay parity."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
