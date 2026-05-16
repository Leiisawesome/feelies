"""Empirical regime-engine audit on disk-cached NBBO (read-only).

Usage::

    .venv\\Scripts\\python.exe scripts/audit_regime_aapl_cache.py \\
        --symbol AAPL --date 2026-03-26

Streams quotes from ``{cache_dir}/{SYMBOL}/{date}.jsonl.gz`` without
loading the full day into memory.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import statistics
import sys
from collections import Counter
from pathlib import Path

from feelies.core.events import NBBOQuote
from feelies.services.regime_engine import (
    HMM3StateFractional,
    regime_posterior_entropy_nats,
)
from feelies.storage.disk_event_cache import _dict_to_event


def _iter_quotes(cache_dir: Path, symbol: str, date: str):
    path = cache_dir / symbol.upper() / f"{date}.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            if d.get("__type__") != "NBBOQuote":
                continue
            yield _dict_to_event(d)


def _log_spread(quote: NBBOQuote) -> float | None:
    spread = float(quote.ask - quote.bid)
    mid = float(quote.ask + quote.bid) / 2.0
    if spread <= 0 or mid <= 0:
        return None
    return math.log(spread / mid)


def main() -> int:
    p = argparse.ArgumentParser(description="Regime engine cache audit")
    p.add_argument("--symbol", default="AAPL")
    p.add_argument("--date", default="2026-03-26")
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".feelies" / "cache",
    )
    p.add_argument("--calibration-quotes", type=int, default=100_000)
    p.add_argument(
        "--stride",
        type=int,
        default=100,
        help="Update posteriors every N quotes after calibration (1 = all)",
    )
    p.add_argument("--time-scaling", action="store_true")
    args = p.parse_args()

    manifest_path = args.cache_dir / args.symbol.upper() / f"{args.date}.manifest.json"
    if not manifest_path.is_file():
        print(f"ERROR: no manifest at {manifest_path}", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print("=== Cache manifest ===")
    for k in (
        "symbol",
        "date",
        "event_count",
        "quotes_count",
        "trades_count",
        "ingestion_health",
    ):
        print(f"  {k}: {manifest.get(k)}")

    # ── Prefix spread / dt sample (first calibration window) ─────────
    log_sample: list[float] = []
    dts: list[float] = []
    prev_ts: int | None = None
    calib_quotes: list[NBBOQuote] = []
    n_locked = 0
    n_bad_spread = 0

    for i, q in enumerate(_iter_quotes(args.cache_dir, args.symbol, args.date)):
        ls = _log_spread(q)
        if ls is not None and len(log_sample) < 50_000:
            log_sample.append(ls)
        if prev_ts is not None and len(dts) < 50_000:
            dts.append(max(0.0, (q.timestamp_ns - prev_ts) / 1e9))
        prev_ts = q.timestamp_ns
        if float(q.ask - q.bid) <= 0:
            n_locked += 1
        if ls is None:
            n_bad_spread += 1
        if len(calib_quotes) < args.calibration_quotes:
            calib_quotes.append(q)
        if len(calib_quotes) >= args.calibration_quotes and len(log_sample) >= 50_000:
            break

    print("\n=== Prefix microstructure (first quotes scanned) ===")
    print(f"  quotes scanned for prefix: {len(calib_quotes):,}")
    print(f"  locked/crossed (spread<=0): {n_locked:,}")
    print(f"  bad spread (spread<=0 or mid<=0): {n_bad_spread:,}")
    if log_sample:
        log_sample.sort()
        n = len(log_sample)
        print(f"  log(spread/mid) p01: {log_sample[int(0.01 * n)]:.6f}")
        print(f"  log(spread/mid) p50: {log_sample[n // 2]:.6f}")
        print(f"  log(spread/mid) p99: {log_sample[int(0.99 * n)]:.6f}")
        print(f"  log(spread/mid) mean: {statistics.mean(log_sample):.6f}")
    if dts:
        dts.sort()
        m = len(dts)
        med = dts[m // 2]
        print(f"  inter-arrival median: {med:.6f} s  (~{1.0 / med:.1f} quotes/s)" if med > 0 else "  inter-arrival median: 0")
        print(f"  inter-arrival p99: {dts[int(0.99 * m)]:.6f} s")

    # ── Default vs calibrated emissions ─────────────────────────────
    default_emission = HMM3StateFractional._DEFAULT_EMISSION
    print("\n=== Default emission params (placeholder) ===")
    for i, (mu, sig) in enumerate(default_emission):
        print(f"  state {i}: mu={mu:.4f} sigma={sig:.4f}")

    engine = HMM3StateFractional(
        transition_time_scaling_enabled=args.time_scaling,
        transition_dt_reference_seconds=0.05,
    )
    ok = engine.calibrate(calib_quotes)
    print(f"\n=== Calibration ({len(calib_quotes):,} prefix quotes, pooled) ===")
    print(f"  calibrate() -> {ok}")
    if ok:
        for i, (mu, sig) in enumerate(engine._emission):
            name = engine.state_names[i]
            print(f"  fitted state {i} ({name}): mu={mu:.6f} sigma={sig:.6f}")
        for i in range(engine.n_states - 1):
            mu_a, sa = engine._emission[i]
            mu_b, sb = engine._emission[i + 1]
            d = abs(mu_b - mu_a) / math.sqrt(sa * sa + sb * sb)
            print(f"  adjacent d({engine.state_names[i]},{engine.state_names[i+1]}): {d:.3f}")

    # ── Full-day posterior pass (strided) ───────────────────────────
    if ok:
        engine2 = HMM3StateFractional(
            emission_params=list(engine._emission),
            transition_time_scaling_enabled=args.time_scaling,
            transition_dt_reference_seconds=0.05,
        )
    else:
        engine2 = HMM3StateFractional(
            transition_time_scaling_enabled=args.time_scaling,
        )

    dominant_counts: Counter[str] = Counter()
    entropies: list[float] = []
    p_normal: list[float] = []
    updates = 0
    idx_normal = list(engine2.state_names).index("normal")

    for i, q in enumerate(_iter_quotes(args.cache_dir, args.symbol, args.date)):
        if i < args.calibration_quotes:
            continue
        if (i - args.calibration_quotes) % args.stride != 0:
            continue
        post = engine2.posterior(q)
        updates += 1
        dominant_counts[engine2.state_names[max(range(len(post)), key=lambda j: post[j])]] += 1
        entropies.append(regime_posterior_entropy_nats(post))
        p_normal.append(post[idx_normal])

    print(f"\n=== Strided posterior pass (stride={args.stride}, after calibration prefix) ===")
    print(f"  posterior updates: {updates:,}")
    print(f"  time_scaling: {args.time_scaling}")
    if dominant_counts:
        total = sum(dominant_counts.values())
        for name in engine2.state_names:
            c = dominant_counts.get(name, 0)
            print(f"  dominant {name}: {c:,} ({100.0 * c / total:.1f}%)")
    if entropies:
        entropies.sort()
        m = len(entropies)
        print(f"  entropy nats p50: {entropies[m // 2]:.4f}")
        print(f"  entropy nats p99: {entropies[int(0.99 * m)]:.4f}")
    if p_normal:
        print(f"  P(normal) mean: {statistics.mean(p_normal):.4f}")
        print(f"  P(normal) min: {min(p_normal):.4f}")

    # Default engine discrimination spot-check on median spread quote
    if log_sample:
        med_ls = log_sample[len(log_sample) // 2]
        def _like(emission, x):
            out = []
            for mu, sigma in emission:
                z = (x - mu) / sigma
                out.append(math.exp(-0.5 * z * z) / (sigma * math.sqrt(2 * math.pi)))
            return out
        print("\n=== Likelihood ratio at median log-spread (prefix) ===")
        print(f"  x = {med_ls:.6f}")
        print(f"  default L: {_like(default_emission, med_ls)}")
        if ok:
            print(f"  calibrated L: {_like(engine._emission, med_ls)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
