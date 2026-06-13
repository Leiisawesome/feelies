#!/usr/bin/env python3
"""Regime diagnostics harness — is the regime posterior discriminative, and
does ``P(vol_breakout)`` actually predict adverse forward behaviour? (audit
second-pass R-2).

Read-only offline falsification tool.  Given cached NBBO for one or more
``(symbol, date)`` pairs (the platform's :class:`DiskEventCache`) **or** a raw
NBBO JSONL event log, this script:

1. Builds the *same* :class:`RegimeEngine` a real run would (from a
   ``PlatformConfig``), calibrates it on the causal prefix of
   ``regime_calibration_max_quotes`` quotes (mirroring the orchestrator's
   ``_calibrate_regime_engine``), then runs ``posterior()`` over the full
   stream.
2. Reports the engine's **discriminative power**: calibrated emission
   means/sigmas, the min pairwise separation ``d = |mu_i-mu_j| /
   sqrt(sig_i^2+sig_j^2)``, argmax occupancy, the per-state posterior
   distribution, and the posterior-entropy distribution.
3. Reports how the shipped / candidate regime gate clauses would **prune**
   entries (``P(normal) > x``, ``P(vol_breakout) < tau``, ``entropy <= e``)
   so a threshold's effect is measured before it ships.
4. Buckets the **forward mid log-return** (and its absolute value, a realized-
   vol / cost proxy) by ``P(vol_breakout)`` decile and by entropy decile —
   directly testing the P1-6 premise that high ``P(vol_breakout)`` marks
   adverse / costly windows.  No lookahead: a tick is dropped if its forward
   window extends past the last quote.

This makes **no** trading-edge claim and proposes **no** threshold.  It is the
merge gate the second pass (R-2) requires: any change to a regime-gate
condition, hazard threshold, or regime-conditioned scaling must show its delta
here on a cached symbol first.

Usage
-----
    # Cache mode (mirrors a real backtest's engine + calibration):
    uv run python scripts/regime_diagnostics.py \
        --config configs/backtest_app.yaml \
        --symbol APP --date 2026-06-01 --date 2026-06-05 \
        [--cache-dir ~/.feelies/cache] [--horizon 120] [--vol-bound 0.30]

    # JSONL mode (smoke / no cache; uses default engine unless --config given):
    uv run python scripts/regime_diagnostics.py \
        --event-log tests/fixtures/event_logs/synth_5min_aapl.jsonl

``--symbol`` / ``--date`` may be repeated or comma-separated; dates expand to
the inclusive calendar range when exactly two are given.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics as st
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Sequence

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.core.events import NBBOQuote  # noqa: E402
from feelies.services.regime_engine import (  # noqa: E402
    HMM3StateFractional,
    RegimeEngine,
    get_regime_engine,
    regime_posterior_entropy_nats,
)

_NS_PER_SECOND = 1_000_000_000


# ── Forward mid series (causal; mirrors scripts/sensor_feature_ic.py) ─────


@dataclass
class _MidSeries:
    ts: list[int]
    mid: list[float]

    @classmethod
    def from_quotes(cls, quotes: Iterable[NBBOQuote]) -> "_MidSeries":
        ts: list[int] = []
        mid: list[float] = []
        for q in quotes:
            b, a = float(q.bid), float(q.ask)
            if b > 0.0 and a > 0.0:
                ts.append(q.timestamp_ns)
                mid.append((b + a) / 2.0)
        return cls(ts=ts, mid=mid)

    def at(self, t_ns: int) -> float | None:
        i = bisect.bisect_right(self.ts, t_ns) - 1
        return self.mid[i] if i >= 0 else None

    @property
    def last_ts(self) -> int:
        return self.ts[-1] if self.ts else 0

    def forward_log_return(self, t0: int, horizon_s: int) -> float | None:
        t1 = t0 + horizon_s * _NS_PER_SECOND
        if t1 > self.last_ts:
            return None  # no realised forward window — drop (no lookahead)
        m0, m1 = self.at(t0), self.at(t1)
        if m0 is None or m1 is None or m0 <= 0.0 or m1 <= 0.0 or m1 == m0:
            return None
        return math.log(m1 / m0)


# ── Diagnostics core (pure; unit-tested on the synth fixture) ─────────────


@dataclass
class _Bucket:
    lo: float
    hi: float
    n: int
    mean_fwd_bps: float
    mean_abs_fwd_bps: float


@dataclass
class RegimeDiagnostics:
    n_quotes: int
    calibrated: bool
    state_names: tuple[str, ...]
    emission_mu: tuple[float, ...]
    emission_sigma: tuple[float, ...]
    min_separation: float
    pairwise_separation: dict[str, float]
    occupancy: dict[str, float]
    p_state_mean: dict[str, float]
    entropy_mean: float
    entropy_max: float
    entropy_frac_gt_095: float
    p_normal_gt_05_frac: float
    prune_table: list[tuple[str, float]] = field(default_factory=list)
    fwd_by_vol_decile: list[_Bucket] = field(default_factory=list)
    fwd_by_entropy_decile: list[_Bucket] = field(default_factory=list)
    horizon_seconds: int = 0
    vol_bound: float = 0.30


def _pairwise_separation(mu: Sequence[float], sigma: Sequence[float]) -> dict[tuple[int, int], float]:
    out: dict[tuple[int, int], float] = {}
    k = len(mu)
    for i in range(k):
        for j in range(i + 1, k):
            denom = math.sqrt(sigma[i] ** 2 + sigma[j] ** 2)
            out[(i, j)] = abs(mu[j] - mu[i]) / denom if denom > 1e-12 else 0.0
    return out


def _decile_buckets(
    keys: list[float],
    fwd: list[float | None],
    n_buckets: int = 10,
) -> list[_Bucket]:
    """Bucket forward returns by quantile of ``keys`` (paired by index)."""
    paired = [(k, f) for k, f in zip(keys, fwd) if f is not None]
    if len(paired) < n_buckets:
        return []
    paired.sort(key=lambda t: t[0])
    out: list[_Bucket] = []
    n = len(paired)
    for b in range(n_buckets):
        lo_i = b * n // n_buckets
        hi_i = (b + 1) * n // n_buckets
        chunk = paired[lo_i:hi_i]
        if not chunk:
            continue
        rets = [f for _, f in chunk]
        out.append(
            _Bucket(
                lo=chunk[0][0],
                hi=chunk[-1][0],
                n=len(chunk),
                mean_fwd_bps=1e4 * st.mean(rets),
                mean_abs_fwd_bps=1e4 * st.mean(abs(r) for r in rets),
            )
        )
    return out


def compute_diagnostics(
    quotes: Sequence[NBBOQuote],
    engine: RegimeEngine,
    *,
    calibration_max_quotes: int | None,
    horizon_seconds: int,
    vol_bound: float,
) -> RegimeDiagnostics:
    """Calibrate (causal prefix), run posteriors, and summarise discriminability."""
    quotes = sorted(quotes, key=lambda q: (q.timestamp_ns, q.sequence))
    calibrate = getattr(engine, "calibrate", None)
    already = bool(getattr(engine, "calibrated", False))
    if calibrate is not None and not already and calibration_max_quotes:
        calibrate(list(quotes[:calibration_max_quotes]))

    names = tuple(engine.state_names)
    nm = names.index("normal") if "normal" in names else 0
    vb = names.index("vol_breakout") if "vol_breakout" in names else len(names) - 1

    mids = _MidSeries.from_quotes(quotes)
    occ = [0] * len(names)
    p_sum = [0.0] * len(names)
    ents: list[float] = []
    pvb_series: list[float] = []
    fwd_series: list[float | None] = []
    n = 0
    pass_pnorm = pass_pnorm_vol = pass_pnorm_vol_ent = 0
    for q in quotes:
        p = engine.posterior(q)
        n += 1
        occ[max(range(len(p)), key=lambda i: p[i])] += 1
        for i, pi in enumerate(p):
            p_sum[i] += pi
        e = regime_posterior_entropy_nats(p)
        ents.append(e)
        pvb_series.append(p[vb])
        fwd_series.append(mids.forward_log_return(q.timestamp_ns, horizon_seconds))
        if p[nm] > 0.5:
            pass_pnorm += 1
            if p[vb] < vol_bound:
                pass_pnorm_vol += 1
                if e <= 0.95:
                    pass_pnorm_vol_ent += 1

    emis = getattr(engine, "_emission", tuple((0.0, 1.0) for _ in names))
    mu = tuple(float(m) for m, _ in emis)
    sigma = tuple(float(s) for _, s in emis)
    pw = _pairwise_separation(mu, sigma)
    pw_named = {f"{names[i]}|{names[j]}": d for (i, j), d in pw.items()}
    denom = max(n, 1)

    return RegimeDiagnostics(
        n_quotes=n,
        calibrated=bool(getattr(engine, "calibrated", False)),
        state_names=names,
        emission_mu=mu,
        emission_sigma=sigma,
        min_separation=min(pw.values()) if pw else float("inf"),
        pairwise_separation=pw_named,
        occupancy={names[i]: occ[i] / denom for i in range(len(names))},
        p_state_mean={names[i]: p_sum[i] / denom for i in range(len(names))},
        entropy_mean=st.mean(ents) if ents else 0.0,
        entropy_max=max(ents) if ents else 0.0,
        entropy_frac_gt_095=sum(e > 0.95 for e in ents) / denom,
        p_normal_gt_05_frac=pass_pnorm / denom,
        prune_table=[
            ("P(normal) > 0.5", pass_pnorm / denom),
            (f"  + P(vol_breakout) < {vol_bound}", pass_pnorm_vol / denom),
            ("  + entropy <= 0.95", pass_pnorm_vol_ent / denom),
        ],
        fwd_by_vol_decile=_decile_buckets(pvb_series, fwd_series),
        fwd_by_entropy_decile=_decile_buckets(ents, fwd_series),
        horizon_seconds=horizon_seconds,
        vol_bound=vol_bound,
    )


def format_report(d: RegimeDiagnostics, *, label: str = "") -> str:
    lines: list[str] = []
    hdr = f"== Regime diagnostics{(' — ' + label) if label else ''} =="
    lines.append(hdr)
    lines.append(f"quotes={d.n_quotes}  calibrated={d.calibrated}  horizon={d.horizon_seconds}s")
    lines.append(
        "emissions (mu,sigma): "
        + ", ".join(
            f"{n}=({mu:.3f},{sg:.3f})"
            for n, mu, sg in zip(d.state_names, d.emission_mu, d.emission_sigma)
        )
    )
    flag = "  <-- DEGENERATE (< 0.5 weak-discrimination floor)" if d.min_separation < 0.5 else ""
    lines.append(f"min pairwise separation d = {d.min_separation:.3f}{flag}")
    lines.append("  " + "  ".join(f"{k}={v:.3f}" for k, v in d.pairwise_separation.items()))
    lines.append("argmax occupancy: " + "  ".join(f"{k}={v:.1%}" for k, v in d.occupancy.items()))
    lines.append("P(state) mean:    " + "  ".join(f"{k}={v:.3f}" for k, v in d.p_state_mean.items()))
    lines.append(
        f"posterior entropy: mean={d.entropy_mean:.3f} max={d.entropy_max:.3f} "
        f"(ln K={math.log(len(d.state_names)):.3f})  frac>0.95={d.entropy_frac_gt_095:.1%}"
    )
    lines.append("gate-clause pruning (fraction of ticks regime-eligible):")
    for clause, frac in d.prune_table:
        lines.append(f"  {clause:<32} {frac:.2%}")
    lines.append(f"forward mid return by P(vol_breakout) decile (horizon={d.horizon_seconds}s):")
    lines.append("  decile  P(vb) range        n     mean_fwd_bps   mean|fwd|_bps")
    for i, b in enumerate(d.fwd_by_vol_decile):
        lines.append(
            f"  {i + 1:>5}  [{b.lo:.3f},{b.hi:.3f}]  {b.n:>6}  {b.mean_fwd_bps:>+12.3f}  {b.mean_abs_fwd_bps:>12.3f}"
        )
    lines.append("forward mid return by entropy decile:")
    lines.append("  decile  entropy range      n     mean_fwd_bps   mean|fwd|_bps")
    for i, b in enumerate(d.fwd_by_entropy_decile):
        lines.append(
            f"  {i + 1:>5}  [{b.lo:.3f},{b.hi:.3f}]  {b.n:>6}  {b.mean_fwd_bps:>+12.3f}  {b.mean_abs_fwd_bps:>12.3f}"
        )
    lines.append(
        "INTERPRETATION: if min separation < 0.5 OR entropy is mostly > 0.95, "
        "the posterior is near-noise and ANY P(state)/entropy gate threshold "
        "filters noise (see audit 2026-06-13). If mean|fwd| does NOT rise with "
        "P(vol_breakout), that state is not marking adverse/costly windows and "
        "a `P(vol_breakout) < tau` entry bound has no economic basis."
    )
    return "\n".join(lines)


# ── Loaders ───────────────────────────────────────────────────────────────


def _load_quotes_from_jsonl(path: Path) -> list[NBBOQuote]:
    quotes: list[NBBOQuote] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if d.get("kind") != "NBBOQuote":
                continue
            quotes.append(
                NBBOQuote(
                    timestamp_ns=int(d["timestamp_ns"]),
                    correlation_id=d.get("correlation_id", "diag"),
                    sequence=int(d["sequence"]),
                    symbol=d["symbol"],
                    bid=Decimal(str(d["bid"])),
                    ask=Decimal(str(d["ask"])),
                    bid_size=int(d.get("bid_size", 0)),
                    ask_size=int(d.get("ask_size", 0)),
                    exchange_timestamp_ns=int(d.get("exchange_timestamp_ns", d["timestamp_ns"])),
                )
            )
    return quotes


def _load_quotes_from_cache(
    config_path: Path | None,
    symbols: list[str],
    dates: list[str],
    cache_dir: Path | None,
) -> tuple[list[NBBOQuote], int | None]:
    """Return (quotes, calibration_max_quotes). Engine is built via _build_engine."""
    from feelies.core.platform_config import PlatformConfig
    from feelies.storage.cache_replay import load_event_log_from_disk_cache

    cal_max: int | None = None
    if config_path is not None:
        cal_max = PlatformConfig.from_yaml(config_path).regime_calibration_max_quotes

    # ``load_event_log_from_disk_cache`` expands [start, end] over the calendar,
    # so first..last covers both an explicit pair and a longer date list.
    event_log, _ingest, _meta = load_event_log_from_disk_cache(
        symbols, dates[0], dates[-1], cache_dir=cache_dir
    )
    quotes = [e for e in event_log.replay() if isinstance(e, NBBOQuote)]
    return quotes, cal_max


def _parse_multi(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(p.strip() for p in v.split(",") if p.strip())
    return out


def _build_engine(config_path: Path | None) -> RegimeEngine:
    if config_path is None:
        return HMM3StateFractional()
    from feelies.core.platform_config import PlatformConfig

    cfg = PlatformConfig.from_yaml(config_path)
    name = cfg.regime_engine or "hmm_3state_fractional"
    return get_regime_engine(name, **dict(cfg.regime_engine_options))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, default=None, help="PlatformConfig YAML (engine + calibration)")
    ap.add_argument("--symbol", action="append", default=[])
    ap.add_argument("--date", action="append", default=[])
    ap.add_argument("--cache-dir", type=Path, default=None)
    ap.add_argument("--event-log", type=Path, default=None, help="raw NBBO JSONL (skips the cache)")
    ap.add_argument("--horizon", type=int, default=120)
    ap.add_argument("--vol-bound", type=float, default=0.30)
    ap.add_argument(
        "--calibration-max-quotes",
        type=int,
        default=None,
        help="override calibration prefix (JSONL mode default: all quotes)",
    )
    args = ap.parse_args(argv)

    if args.event_log is not None:
        quotes = _load_quotes_from_jsonl(args.event_log)
        engine = _build_engine(args.config)
        cal_max = args.calibration_max_quotes or len(quotes)
        label = str(args.event_log)
    else:
        symbols = _parse_multi(args.symbol)
        dates = _parse_multi(args.date)
        if not symbols or not dates:
            print("Provide --event-log, or --symbol and --date (with --config).", file=sys.stderr)
            return 2
        quotes, cal_max = _load_quotes_from_cache(
            args.config, symbols, dates, args.cache_dir
        )
        engine = _build_engine(args.config)
        if args.calibration_max_quotes is not None:
            cal_max = args.calibration_max_quotes
        label = f"{','.join(symbols)} {','.join(dates)}"

    if len(quotes) < 50:
        print(f"Too few quotes ({len(quotes)}) for diagnostics.", file=sys.stderr)
        return 1

    diag = compute_diagnostics(
        quotes,
        engine,
        calibration_max_quotes=cal_max,
        horizon_seconds=args.horizon,
        vol_bound=args.vol_bound,
    )
    print(format_report(diag, label=label))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
