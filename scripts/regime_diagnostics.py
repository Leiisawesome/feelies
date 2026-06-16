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
        --config configs/bt_app.yaml \
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
from typing import Iterable, Mapping, Sequence

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
class _RegimeView:
    """Minimal regime snapshot the gate DSL reads (a stand-in for RegimeState)."""

    state_names: tuple[str, ...]
    posteriors: tuple[float, ...]
    dominant_name: str
    posterior_entropy_nats: float
    calibrated: bool = True


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
    boundary_views: list[_RegimeView] = field(default_factory=list)
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
    boundary_anchor_ns: int | None = None,
    boundary_event_timestamps_ns: Sequence[int] | None = None,
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
    horizon_ns = horizon_seconds * _NS_PER_SECOND
    # Anchor to the *first event* of the prepared replay (mirrors
    # ``HorizonScheduler.session_open_ns``, which ``backtest_runner`` derives
    # from ``prepare_backtest_event_log.first_event_ts_ns`` — the first kept
    # event of any type, possibly a trade).  Falling back to the first quote
    # would misalign the latch bins with the production cadence when the first
    # RTH event is not an NBBO.
    t0_ns = (
        boundary_anchor_ns
        if boundary_anchor_ns is not None
        else (quotes[0].timestamp_ns if quotes else 0)
    )
    n = 0
    pass_pnorm = pass_pnorm_vol = pass_pnorm_vol_ent = 0
    # Per-quote (timestamp, symbol, posterior, entropy) samples are retained
    # so the boundary-view pass below can latch the most-recent posterior at
    # each bin crossing — production ``HorizonSignalEngine`` evaluates the
    # gate against the cached regime *per symbol*, and ``RegimeEngine``
    # advances each symbol's posterior independently, so latching must be
    # keyed by symbol when quotes from multiple symbols are interleaved.
    quote_samples: list[tuple[int, str, tuple[float, ...], float]] = []
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
        quote_samples.append((q.timestamp_ns, q.symbol, tuple(p), e))

    # Sample one regime view per horizon-width window at the production
    # ``HorizonScheduler`` cadence: a tick is emitted on the first event of
    # *any* type that crosses a new bin (trades and metrics included), and
    # the gate evaluates against the *latched* posterior at that moment —
    # i.e. the most recent quote's posterior, since ``RegimeEngine`` only
    # updates on quotes.  When the caller supplies the full event-timestamp
    # stream we mirror that exactly; otherwise we fall back to quote
    # timestamps (correct only when no non-quote event ever leads a bin —
    # the JSONL/no-cache case where only quotes are loaded).
    boundary_views: list[_RegimeView] = []
    if horizon_ns > 0 and quote_samples:
        if boundary_event_timestamps_ns is not None:
            boundary_ts_seq: Sequence[int] = boundary_event_timestamps_ns
        else:
            boundary_ts_seq = [ts for ts, _sym, _p, _e in quote_samples]
        cal = bool(getattr(engine, "calibrated", False))
        # Group quote samples per symbol; production ``HorizonSignalEngine``
        # caches regime under ``(symbol, engine_name)`` and evaluates the
        # gate per symbol at each tick, so a boundary view for symbol A must
        # read A's most-recent posterior — never whichever symbol happens to
        # have quoted last on a merged multi-symbol stream.
        samples_by_sym: dict[str, list[tuple[int, tuple[float, ...], float]]] = {}
        for ts_q, sym, p_q, e_q in quote_samples:
            samples_by_sym.setdefault(sym, []).append((ts_q, p_q, e_q))
        qi_by_sym: dict[str, int] = {sym: -1 for sym in samples_by_sym}
        sorted_syms = sorted(samples_by_sym)
        cur_bin = -1
        for ts in boundary_ts_seq:
            if ts < t0_ns:
                continue
            b = (ts - t0_ns) // horizon_ns
            if b == cur_bin:
                continue
            cur_bin = b
            for sym in sorted_syms:
                sym_samples = samples_by_sym[sym]
                qi = qi_by_sym[sym]
                n_obs = len(sym_samples)
                while qi + 1 < n_obs and sym_samples[qi + 1][0] <= ts:
                    qi += 1
                qi_by_sym[sym] = qi
                if qi < 0:
                    # Boundary crossed before this symbol's first quote; no
                    # posterior is latched yet (production's cached regime
                    # is absent here too), so skip rather than fabricate
                    # one.  Other symbols may still emit a view for this bin.
                    continue
                _ts_q, p_t, e_t = sym_samples[qi]
                dom = max(range(len(p_t)), key=lambda i: p_t[i])
                boundary_views.append(
                    _RegimeView(
                        state_names=names,
                        posteriors=p_t,
                        dominant_name=names[dom],
                        posterior_entropy_nats=e_t,
                        calibrated=cal,
                    )
                )

    # 1-D engines expose ``_emission`` as (mu, sigma) pairs; 2-D engines (audit
    # R-3, spread+vol) use a nested structure.  Display the per-state mu/sigma
    # and pairwise table only for the 1-D shape; otherwise rely on the engine's
    # canonical ``discriminability`` property for min_separation.
    emis = getattr(engine, "_emission", tuple((0.0, 1.0) for _ in names))
    try:
        mu = tuple(float(m) for m, _ in emis)
        sigma = tuple(float(s) for _, s in emis)
        pw = _pairwise_separation(mu, sigma)
        pw_named = {f"{names[i]}|{names[j]}": d for (i, j), d in pw.items()}
        min_sep = min(pw.values()) if pw else float("inf")
    except (TypeError, ValueError):
        mu = ()
        sigma = ()
        pw_named = {}
        min_sep = float("inf")
    # Prefer the engine's own discriminability (defined on both 1-D and 2-D
    # engines); fall back to the 1-D pairwise min above.
    min_sep = float(getattr(engine, "discriminability", min_sep))
    denom = max(n, 1)

    return RegimeDiagnostics(
        n_quotes=n,
        calibrated=bool(getattr(engine, "calibrated", False)),
        state_names=names,
        emission_mu=mu,
        emission_sigma=sigma,
        min_separation=min_sep,
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
        boundary_views=boundary_views,
        horizon_seconds=horizon_seconds,
        vol_bound=vol_bound,
    )


def simulate_latch_on_fraction(
    views: Sequence["_RegimeView"],
    on_condition: str,
    off_condition: str,
    *,
    hysteresis: Mapping[str, float] | None = None,
) -> tuple[float, int]:
    """Fraction of horizon boundaries the hysteresis latch holds ON.

    Audit second-pass: instantaneous on-eligibility (the prune table) does NOT
    capture a gate's *latched* behaviour — an aggressive ``off_condition`` (e.g.
    ``P(vol_breakout) > 0.40``) can knock the latch OFF during exactly the
    windows the on-condition would admit, collapsing the realised ON-fraction
    far below the instantaneous eligibility.  This drives signal count, so it is
    the metric a gate change must be measured on.

    Sensor identifiers in the conditions are bound to **neutral** values (0.0 /
    z=0 / pct=0.5) so the regime terms are isolated: the result is the
    *regime-driven* ON-fraction, comparable old-vs-new.  Hysteresis margin
    identifiers (e.g. ``posterior_margin``) must be supplied via *hysteresis*
    so that off-clauses like ``P(normal) < 0.5 - posterior_margin`` evaluate at
    the YAML-declared values rather than collapsing to ``0.0`` and diverging
    from production gate behaviour.  Returns ``(on_fraction, n_boundaries)``.
    """
    from feelies.signals.regime_gate import Bindings, RegimeGate

    gate = RegimeGate(
        alpha_id="_diag",
        on_condition=on_condition,
        off_condition=off_condition,
        hysteresis=hysteresis,
    )
    # ``binding_identifier_names`` already excludes hysteresis keys, so the
    # neutral 0.0 / z=0 / pct=0.5 fill below never shadows declared margins —
    # ``RegimeGate.evaluate`` will overlay the margin values on top.
    referenced = gate.binding_identifier_names()
    sensor_values = {name: 0.0 for name in referenced if not name.endswith(("_zscore", "_percentile"))}
    zscores = {name[: -len("_zscore")]: 0.0 for name in referenced if name.endswith("_zscore")}
    percentiles = {
        name[: -len("_percentile")]: 0.5 for name in referenced if name.endswith("_percentile")
    }
    on_count = 0
    for v in views:
        b = Bindings(
            regime=v, sensor_values=sensor_values, percentiles=percentiles, zscores=zscores
        )
        if gate.evaluate(symbol="_diag", bindings=b):
            on_count += 1
    n = len(views)
    return (on_count / n if n else 0.0), n


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


def _load_event_timestamps_from_jsonl(path: Path) -> list[int]:
    """Timestamps of *all* events in a JSONL log, sorted ascending.

    Production ``HorizonScheduler`` boundary detection runs over every
    kept event regardless of kind; we mirror that here so trades and
    other non-quote events can lead a bin, matching production's
    boundary-tick emission cadence.
    """
    ts: list[int] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            try:
                ts.append(int(d["timestamp_ns"]))
            except (KeyError, TypeError, ValueError):
                continue
    ts.sort()
    return ts


def _load_quotes_from_cache(
    config_path: Path,
    symbols: list[str],
    dates: list[str],
    cache_dir: Path | None,
) -> tuple[list[NBBOQuote], int | None, int | None, list[int]]:
    """Return (quotes, calibration_max_quotes, first_event_ts_ns, all_event_ts_ns).

    Engine is built via :func:`_build_engine`.  Mirrors a real backtest:
    applies ``prepare_backtest_event_log`` so the ``session_kind`` filter
    (default RTH) and the calibration-prefix selection match what
    ``run_backtest`` feeds the orchestrator.
    Without this, cache-mode diagnostics would calibrate and score on a
    quote universe that diverges from the production replay.

    ``first_event_ts_ns`` is the timestamp of the *first kept event of any
    type* (possibly a Trade), exactly what ``backtest_runner`` uses to
    seed ``PlatformConfig.session_open_ns``; threading it through to
    :func:`compute_diagnostics` keeps boundary indices aligned with
    ``HorizonScheduler``.

    ``all_event_ts_ns`` is the sorted ascending timestamp stream of *every*
    kept event (quotes + trades + …) so the boundary-view sampler can
    mirror ``HorizonScheduler``'s cross-kind tick cadence — production
    emits a tick on the first event of *any* type to cross a bin.
    """
    from feelies.core.platform_config import PlatformConfig
    from feelies.harness.backtest_prep import prepare_backtest_event_log
    from feelies.storage.cache_replay import load_event_log_from_disk_cache

    config = PlatformConfig.from_yaml(config_path)
    cal_max = config.regime_calibration_max_quotes

    # ``load_event_log_from_disk_cache`` expands [start, end] over the calendar,
    # so min..max covers both an explicit pair and a longer date list and is
    # robust to dates passed in any order.
    sorted_dates = sorted(dates)
    event_log, _ingest, _meta = load_event_log_from_disk_cache(
        symbols, sorted_dates[0], sorted_dates[-1], cache_dir=cache_dir
    )
    prep = prepare_backtest_event_log(config, event_log)
    quotes: list[NBBOQuote] = []
    all_event_ts: list[int] = []
    for ev in prep.event_log.replay():
        all_event_ts.append(ev.timestamp_ns)
        if isinstance(ev, NBBOQuote):
            quotes.append(ev)
    all_event_ts.sort()
    return quotes, cal_max, prep.first_event_ts_ns, all_event_ts


def _parse_multi(values: list[str]) -> list[str]:
    out: list[str] = []
    for v in values:
        out.extend(p.strip() for p in v.split(",") if p.strip())
    return out


def _parse_hysteresis(raw: str | None) -> dict[str, float] | None:
    """Parse a ``key=value,key=value`` CLI string into a margin mapping.

    Mirrors the ``regime_gate.hysteresis:`` YAML block so callers can pass
    e.g. ``--baseline-hysteresis posterior_margin=0.20,percentile_margin=0.30``
    and have the simulator evaluate off-clauses like
    ``P(normal) < 0.5 - posterior_margin`` against the production values.
    """
    if raw is None:
        return None
    out: dict[str, float] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise SystemExit(
                f"--*-hysteresis entry {chunk!r} must be key=value (e.g. posterior_margin=0.20)"
            )
        key, value = chunk.split("=", 1)
        out[key.strip()] = float(value.strip())
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
    # Latch simulation (the merge-gate metric): ON-fraction of a baseline gate
    # vs a candidate gate at horizon cadence, regime terms isolated.
    ap.add_argument("--baseline-on", default=None, help="baseline on_condition (regime terms)")
    ap.add_argument("--baseline-off", default=None, help="baseline off_condition")
    ap.add_argument(
        "--baseline-hysteresis",
        default=None,
        help="baseline hysteresis margins (k=v,k=v; e.g. posterior_margin=0.20)",
    )
    ap.add_argument("--candidate-on", default=None, help="candidate on_condition")
    ap.add_argument("--candidate-off", default=None, help="candidate off_condition")
    ap.add_argument(
        "--candidate-hysteresis",
        default=None,
        help="candidate hysteresis margins (k=v,k=v)",
    )
    args = ap.parse_args(argv)

    boundary_anchor_ns: int | None = None
    boundary_event_ts: list[int] | None = None
    if args.event_log is not None:
        quotes = _load_quotes_from_jsonl(args.event_log)
        boundary_event_ts = _load_event_timestamps_from_jsonl(args.event_log)
        engine = _build_engine(args.config)
        cal_max = args.calibration_max_quotes or len(quotes)
        label = str(args.event_log)
    else:
        symbols = _parse_multi(args.symbol)
        dates = _parse_multi(args.date)
        if not symbols or not dates or args.config is None:
            print(
                "Provide --event-log, or --symbol and --date together with --config "
                "(cache mode mirrors a configured backtest and requires the YAML "
                "to pick the engine + calibration prefix).",
                file=sys.stderr,
            )
            return 2
        quotes, cal_max, boundary_anchor_ns, boundary_event_ts = _load_quotes_from_cache(
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
        boundary_anchor_ns=boundary_anchor_ns,
        boundary_event_timestamps_ns=boundary_event_ts,
    )
    print(format_report(diag, label=label))

    # Optional latch comparison — the metric that predicts signal-count impact.
    baseline_hyst = _parse_hysteresis(args.baseline_hysteresis)
    candidate_hyst = _parse_hysteresis(args.candidate_hysteresis)
    pairs: list[tuple[str, str, str, Mapping[str, float] | None]] = []
    if args.baseline_on and args.baseline_off:
        pairs.append(("baseline", args.baseline_on, args.baseline_off, baseline_hyst))
    if args.candidate_on and args.candidate_off:
        pairs.append(("candidate", args.candidate_on, args.candidate_off, candidate_hyst))
    if pairs:
        print("\n== Latched ON-fraction at horizon cadence (regime terms isolated) ==")
        results: dict[str, float] = {}
        for name, on, off, hyst in pairs:
            frac, nb = simulate_latch_on_fraction(
                diag.boundary_views, on, off, hysteresis=hyst
            )
            results[name] = frac
            print(f"  {name:<10} ON {frac:.2%} of {nb} boundaries")
            print(f"             on:  {on.strip()}")
            print(f"             off: {off.strip()}")
            if hyst:
                print(
                    "             hysteresis: "
                    + ", ".join(f"{k}={v}" for k, v in hyst.items())
                )
        if "baseline" in results and "candidate" in results and results["baseline"] > 0:
            ratio = results["candidate"] / results["baseline"]
            print(
                f"  => candidate retains {ratio:.0%} of baseline ON-time "
                f"(a large drop here is the signal-count regression, BEFORE backtest)."
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
