#!/usr/bin/env python3
"""P2-1 — inventory sign confirmation via forward-return Spearman IC.

Replays cached L1 NBBO through the ``quote_replenish_asymmetry`` sensor + a
30s rolling-z feature, joins each horizon-boundary z-score to the forward
30s micro-price return, and reports:

* the Spearman information coefficient (pooled across days),
* the bucketed conditional-return profile, and
* a **per-leg, threshold-conditioned** realized edge in bps — the number
  that actually matters, because ``sig_inventory_revert_v1`` only fires at
  ``|asym_z| > entry threshold`` (default 2.0).

This validates / refutes the convention "LONG when
quote_replenish_asymmetry_zscore > 0".  See
``docs/research/inventory_sign_ic.md`` for the methodology + decision gate.

Usage:
    # single day
    python scripts/research/inventory_sign_ic.py --symbol AAPL --date 2026-03-26
    # date range (pooled), tighter entry threshold
    python scripts/research/inventory_sign_ic.py --symbol AAPL \\
        --start 2026-03-16 --end 2026-03-27 --threshold 2.0

Reads real cached NBBO via the disk cache (no network).  Missing days in a
range are skipped with a warning.
"""

from __future__ import annotations

import argparse
import math
import statistics
from pathlib import Path
from typing import Sequence

from feelies.bus.event_bus import EventBus
from feelies.core.events import Event, HorizonFeatureSnapshot, NBBOQuote, Trade
from feelies.core.identifiers import SequenceGenerator
from feelies.features.aggregator import HorizonAggregator
from feelies.features.impl.rolling_stats import RollingZscoreFeature
from feelies.research.forward_ic import (
    bucketed_forward_return,
    forward_return_at,
    spearman_ic,
)
from feelies.sensors.horizon_scheduler import HorizonScheduler
from feelies.sensors.impl.quote_replenish_asymmetry import QuoteReplenishAsymmetrySensor
from feelies.sensors.registry import SensorRegistry
from feelies.sensors.spec import SensorSpec
from feelies.storage.cache_replay import (
    CacheReplayError,
    iter_calendar_dates,
    load_event_log_from_disk_cache,
)

_FEATURE_ID = "quote_replenish_asymmetry_zscore"
_ROUND_TRIP_COST_BPS = 11.0  # disclosed one-way 5.5 -> ~11 round-trip


def compute_feature_and_forward_returns(
    events: Sequence[Event],
    *,
    symbol: str,
    horizon_seconds: int,
) -> tuple[list[float], list[float]]:
    """Replay one session's *events*; return aligned (asym_z, fwd_return).

    Forward return is NaN where the boundary is within ``horizon`` of the
    session end.  Sensor/feature state is per-call, so each session is
    replayed independently (correct — sessions are independent).
    """
    bus = EventBus()
    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({symbol}),
    )
    registry.register(
        SensorSpec(
            sensor_id="quote_replenish_asymmetry",
            sensor_version="1.1.0",
            cls=QuoteReplenishAsymmetrySensor,
            params={"window_seconds": 5, "min_observations": 20},
            subscribes_to=(NBBOQuote,),
        )
    )
    first_ts = events[0].timestamp_ns  # anchor boundaries to data start (Inv-6)
    scheduler = HorizonScheduler(
        horizons=frozenset({horizon_seconds}),
        session_id="P2_1_IC",
        symbols=frozenset({symbol}),
        session_open_ns=first_ts,
        sequence_generator=SequenceGenerator(),
    )
    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({symbol}),
        sensor_buffer_seconds=max(600, horizon_seconds * 4),
        sequence_generator=SequenceGenerator(),
        horizon_features=[
            RollingZscoreFeature(
                "quote_replenish_asymmetry", horizon_seconds, feature_id=_FEATURE_ID
            )
        ],
    )
    aggregator.attach()

    boundaries: list[tuple[int, float]] = []

    def _on_snapshot(snap: HorizonFeatureSnapshot) -> None:
        if snap.symbol != symbol:
            return
        if not snap.warm.get(_FEATURE_ID, False) or snap.stale.get(_FEATURE_ID, False):
            return
        z = snap.values.get(_FEATURE_ID)
        if z is not None:
            boundaries.append((snap.timestamp_ns, float(z)))

    bus.subscribe(HorizonFeatureSnapshot, _on_snapshot)  # type: ignore[arg-type]

    times: list[int] = []
    mids: list[float] = []
    for ev in events:
        if isinstance(ev, NBBOQuote) and ev.symbol == symbol:
            times.append(ev.timestamp_ns)
            mids.append((float(ev.bid) + float(ev.ask)) / 2.0)
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)

    feature = [z for _, z in boundaries]
    forward = [forward_return_at(times, mids, ts, float(horizon_seconds)) for ts, _ in boundaries]
    return feature, forward


def _load_day(symbol: str, date: str, cache_dir: Path | None) -> list[Event] | None:
    try:
        log, _ingest, _meta = load_event_log_from_disk_cache(
            [symbol], date, date, cache_dir=cache_dir
        )
    except CacheReplayError:
        return None
    events = [e for e in log.replay() if isinstance(e, (NBBOQuote, Trade))]
    return events or None


def _leg_stats(pairs: list[tuple[float, float]]) -> tuple[int, float, float]:
    """(n, mean_forward_return_bps, t_stat) for a leg's (z, fwd) pairs."""
    n = len(pairs)
    if n == 0:
        return 0, float("nan"), float("nan")
    rets = [p[1] for p in pairs]
    mean_bps = statistics.fmean(rets) * 1e4
    if n < 2:
        return n, mean_bps, float("nan")
    sd_bps = statistics.stdev(rets) * 1e4
    t = mean_bps / (sd_bps / math.sqrt(n)) if sd_bps > 0 else float("nan")
    return n, mean_bps, t


def _verdict(
    rho: float,
    p_value: float,
    long_edge_bps: float,
    short_edge_bps: float,
    n_long: int,
    n_short: int,
) -> str:
    if n_long < 20 or n_short < 20:
        return (
            "VERDICT: too few tail observations at the entry threshold "
            f"(LONG n={n_long}, SHORT n={n_short}); widen the date range "
            "before deciding."
        )
    # Fade edge per leg: LONG wants +fwd, SHORT wants -fwd (so its edge is
    # -mean_short).  Both must clear cost for the fade to be viable.
    cost = _ROUND_TRIP_COST_BPS
    both_negative = long_edge_bps < 0 and short_edge_bps < 0
    if long_edge_bps > cost and short_edge_bps > cost:
        return (
            "VERDICT: both legs realize a fade edge above round-trip cost -> "
            "convention CONFIRMED. Lift the quarantine and pin this baseline."
        )
    if both_negative and abs((long_edge_bps + short_edge_bps) / 2) > cost:
        return (
            "VERDICT: both legs realize the OPPOSITE of the fade (momentum) "
            "above cost -> sign is INVERTED. Flip to LONG when asym_z < 0 and "
            "re-baseline."
        )
    return (
        "VERDICT: per-leg fade edge does not clear round-trip cost "
        f"(~{cost:.0f} bps) -> convention UNCONFIRMED / sub-cost. Keep "
        "sig_inventory_revert_v1 quarantined."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--date", default=None, help="single session YYYY-MM-DD")
    ap.add_argument("--start", default=None, help="range start YYYY-MM-DD (with --end)")
    ap.add_argument("--end", default=None, help="range end YYYY-MM-DD (inclusive)")
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=2.0, help="|asym_z| entry threshold")
    ap.add_argument("--buckets", type=int, default=5)
    ap.add_argument("--cache-dir", default=None, help="defaults to ~/.feelies/cache")
    args = ap.parse_args(argv)

    if args.date and (args.start or args.end):
        ap.error("use either --date or --start/--end, not both")
    if not args.date and not (args.start and args.end):
        ap.error("provide --date, or both --start and --end")
    dates = [args.date] if args.date else iter_calendar_dates(args.start, args.end)
    cache_dir = Path(args.cache_dir) if args.cache_dir else None

    pooled: list[tuple[float, float]] = []  # (asym_z, fwd_return), NaN-dropped
    used, missing = 0, 0
    for d in dates:
        events = _load_day(args.symbol, d, cache_dir)
        if events is None:
            print(f"  [skip] {args.symbol} {d}: no cached data")
            missing += 1
            continue
        feat, fwd = compute_feature_and_forward_returns(
            events, symbol=args.symbol, horizon_seconds=args.horizon
        )
        day_pairs = [(f, r) for f, r in zip(feat, fwd) if r == r]
        if len(day_pairs) >= 3:
            day_ic = spearman_ic([p[0] for p in day_pairs], [p[1] for p in day_pairs])
            print(
                f"  {args.symbol} {d}: {len(events):>8d} events, "
                f"{len(day_pairs):>4d} boundaries, day {day_ic}"
            )
        pooled.extend(day_pairs)
        used += 1

    print(
        f"\n{args.symbol}: {used} session(s) used, {missing} missing; "
        f"{len(pooled)} pooled boundaries"
    )
    if len(pooled) < 3:
        print("insufficient pooled boundaries — widen the range / check the cache.")
        return 1

    feat = [p[0] for p in pooled]
    fwd = [p[1] for p in pooled]
    res = spearman_ic(feat, fwd)
    print(f"POOLED {res}")
    print("bucketed forward return (low asym_z -> high asym_z):")
    for b in bucketed_forward_return(feat, fwd, n_buckets=args.buckets):
        print(
            f"  asym_z in [{b.lo:+.3f}, {b.hi:+.3f}]  n={b.n:5d}  "
            f"mean_fwd_ret={b.mean_forward_return * 1e4:+.3f} bps"
        )

    thr = args.threshold
    long_pairs = [p for p in pooled if p[0] > thr]
    short_pairs = [p for p in pooled if p[0] < -thr]
    n_long, long_fwd_bps, t_long = _leg_stats(long_pairs)
    n_short, short_fwd_bps, t_short = _leg_stats(short_pairs)
    long_edge = long_fwd_bps  # LONG fade edge = +fwd
    short_edge = -short_fwd_bps  # SHORT fade edge = -fwd
    print(f"\nper-leg edge at |asym_z| > {thr} (fade convention):")
    print(
        f"  LONG  (asym_z > +{thr}): n={n_long:5d}  fwd={long_fwd_bps:+.3f} bps  "
        f"t={t_long:+.2f}  -> fade edge {long_edge:+.3f} bps (want >0)"
    )
    print(
        f"  SHORT (asym_z < -{thr}): n={n_short:5d}  fwd={short_fwd_bps:+.3f} bps  "
        f"t={t_short:+.2f}  -> fade edge {short_edge:+.3f} bps (want >0)"
    )
    print(
        f"  (round-trip cost ~{_ROUND_TRIP_COST_BPS:.0f} bps; t-stats ignore "
        "intra-session autocorrelation — treat as indicative.)"
    )
    print(_verdict(res.rho, res.p_value, long_edge, short_edge, n_long, n_short))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
