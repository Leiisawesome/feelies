"""Deterministic metric helpers — stdlib only."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def safe_mean(values: Sequence[float]) -> float | None:
    clean = [float(v) for v in values if v == v and math.isfinite(float(v))]
    if not clean:
        return None
    return sum(clean) / len(clean)


def safe_std_sample(values: Sequence[float]) -> float | None:
    clean = [float(v) for v in values if v == v and math.isfinite(float(v))]
    n = len(clean)
    if n < 2:
        return None
    m = sum(clean) / n
    var = sum((x - m) ** 2 for x in clean) / (n - 1)
    if var <= 0.0:
        return 0.0
    return math.sqrt(var)


def pearson_correlation(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    xs = [float(a) for a in x]
    ys = [float(b) for b in y]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    denx = math.sqrt(sum((v - mx) ** 2 for v in xs))
    deny = math.sqrt(sum((v - my) ** 2 for v in ys))
    if denx <= 0.0 or deny <= 0.0:
        return None
    r = num / (denx * deny)
    if not math.isfinite(r):
        return None
    if r > 1.0:
        r = 1.0
    if r < -1.0:
        r = -1.0
    return r


def _rank_average(values: Sequence[float]) -> list[float]:
    indexed = sorted((float(v), i) for i, v in enumerate(values))
    ranks = [0.0] * len(values)
    i = 0
    n = len(indexed)
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][0] == indexed[i][0]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-based midrank
        for k in range(i, j + 1):
            _, orig_idx = indexed[k]
            ranks[orig_idx] = avg_rank
        i = j + 1
    return ranks


def spearman_correlation(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 2:
        return None
    rx = _rank_average([float(v) for v in x])
    ry = _rank_average([float(v) for v in y])
    return pearson_correlation(rx, ry)


def ic_t_statistic(ic: float, n: int) -> float | None:
    if n < 3:
        return None
    if ic <= -1.0 or ic >= 1.0:
        return None
    denom = math.sqrt(max(1e-18, 1.0 - ic * ic))
    t = ic * math.sqrt(n - 2) / denom
    return t if math.isfinite(t) else None


def sharpe_ratio(
    returns: Sequence[float],
    *,
    annualization_factor: float,
) -> float | None:
    mu = safe_mean(returns)
    sd = safe_std_sample(returns)
    if mu is None or sd is None:
        return None
    if sd <= 0.0:
        return None
    return (mu / sd) * math.sqrt(annualization_factor)


def max_drawdown_from_equity(equity: Sequence[float]) -> tuple[float, int] | None:
    if len(equity) < 2:
        return None
    peak = float(equity[0])
    max_dd = 0.0
    duration = 0
    cur_dur = 0
    for v in equity[1:]:
        x = float(v)
        if x > peak:
            peak = x
            cur_dur = 0
        if peak > 0:
            dd = (peak - x) / peak
            if dd > max_dd:
                max_dd = dd
                duration = cur_dur
        cur_dur += 1
    return max_dd, duration


def hit_rate(directional_hits: Sequence[bool]) -> float | None:
    if not directional_hits:
        return None
    return sum(1 for h in directional_hits if h) / len(directional_hits)


def quantile_bucket_returns(
    signal: Sequence[float],
    forward_return: Sequence[float],
    *,
    quantiles: int,
) -> list[float] | None:
    if quantiles < 2:
        return None
    if len(signal) != len(forward_return) or len(signal) < quantiles:
        return None
    pairs = sorted(zip((float(s) for s in signal), (float(r) for r in forward_return)), key=lambda p: p[0])
    n = len(pairs)
    out: list[float] = []
    for q in range(quantiles):
        start = (q * n) // quantiles
        end = ((q + 1) * n) // quantiles
        chunk = pairs[start:end]
        if not chunk:
            return None
        m = safe_mean([c[1] for c in chunk])
        if m is None:
            return None
        out.append(m)
    return out


def monotonicity_score(bucket_means: Sequence[float]) -> float | None:
    if len(bucket_means) < 2:
        return None
    inc = sum(
        1 for i in range(len(bucket_means) - 1) if bucket_means[i + 1] > bucket_means[i]
    )
    dec = sum(
        1 for i in range(len(bucket_means) - 1) if bucket_means[i + 1] < bucket_means[i]
    )
    ties = (len(bucket_means) - 1) - inc - dec
    return max(inc, dec) / max(1, (len(bucket_means) - 1 - ties))


def signal_autocorrelation(signal_series: Sequence[float], lag: int = 1) -> float | None:
    if lag < 1 or len(signal_series) <= lag:
        return None
    x = [float(signal_series[i]) for i in range(len(signal_series) - lag)]
    y = [float(signal_series[i + lag]) for i in range(len(signal_series) - lag)]
    return pearson_correlation(x, y)


def max_concentration_fraction(weights: Mapping[Any, float]) -> float | None:
    if not weights:
        return None
    total = sum(max(0.0, float(v)) for v in weights.values())
    if total <= 0.0:
        return None
    return max(max(0.0, float(v)) / total for v in weights.values())


def participation_rate(notional: float, interval_dollar_volume: float) -> float | None:
    if interval_dollar_volume <= 0.0:
        return None
    return abs(float(notional)) / interval_dollar_volume


def skew_kurtosis(values: Sequence[float]) -> tuple[float | None, float | None]:
    clean = [float(v) for v in values if v == v and math.isfinite(float(v))]
    n = len(clean)
    if n < 3:
        return None, None
    m = sum(clean) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in clean) / (n - 1))
    if sd <= 0.0:
        return 0.0, 0.0
    m3 = sum((x - m) ** 3 for x in clean) / n
    m4 = sum((x - m) ** 4 for x in clean) / n
    skew = m3 / (sd**3)
    kurt = m4 / (sd**4) - 3.0
    return skew, kurt


def summarize_trade_pnls(trade_pnls: Sequence[float]) -> dict[str, float | int | None]:
    clean = sorted(float(x) for x in trade_pnls if x == x and math.isfinite(float(x)))
    n = len(clean)
    if n == 0:
        return {"count": 0, "mean": None, "median": None, "worst": None, "best": None}
    mid = n // 2
    median = clean[mid] if n % 2 == 1 else 0.5 * (clean[mid - 1] + clean[mid])
    return {
        "count": n,
        "mean": safe_mean(clean),
        "median": median,
        "worst": clean[0],
        "best": clean[-1],
    }


def iteration_pairs(iterable: Iterable[Mapping[str, Any]], key: str) -> list[tuple[int, Mapping[str, Any]]]:
    out: list[tuple[int, Mapping[str, Any]]] = []
    for i, row in enumerate(iterable):
        if key in row and row[key] is not None and str(row[key]).strip() != "":
            try:
                ts = int(float(row[key]))
            except (TypeError, ValueError):
                continue
            out.append((ts, row))
    out.sort(key=lambda t: t[0])
    return out


__all__ = [
    "hit_rate",
    "ic_t_statistic",
    "iteration_pairs",
    "max_concentration_fraction",
    "max_drawdown_from_equity",
    "monotonicity_score",
    "participation_rate",
    "pearson_correlation",
    "quantile_bucket_returns",
    "safe_mean",
    "safe_std_sample",
    "sharpe_ratio",
    "signal_autocorrelation",
    "skew_kurtosis",
    "spearman_correlation",
    "summarize_trade_pnls",
]
