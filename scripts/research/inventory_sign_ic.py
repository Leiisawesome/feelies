#!/usr/bin/env python3
"""P2-1 — inventory sign confirmation via forward-return Spearman IC.

Replays cached L1 NBBO for one (symbol, date) through the
``quote_replenish_asymmetry`` sensor + a 30s rolling-z feature, joins each
horizon-boundary z-score to the forward 30s micro-price return, and reports
the Spearman information coefficient, the bucketed conditional-return
profile, and a sign-decision verdict.

This validates (or refutes) the ``sig_inventory_revert_v1`` convention
"LONG when quote_replenish_asymmetry_zscore > 0".  See
``docs/research/inventory_sign_ic.md`` for the methodology + decision gate.

Usage:
    python scripts/research/inventory_sign_ic.py --symbol AAPL --date 2026-03-26
    # optional: --horizon 30 --buckets 5 --cache-dir ~/.feelies/cache

Reads real cached NBBO via the disk cache (no network).  Populate the cache
with a normal backtest download first if the day is missing.
"""

from __future__ import annotations

import argparse
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
from feelies.storage.cache_replay import load_event_log_from_disk_cache

_FEATURE_ID = "quote_replenish_asymmetry_zscore"


def compute_feature_and_forward_returns(
    events: Sequence[Event],
    *,
    symbol: str,
    horizon_seconds: int,
) -> tuple[list[float], list[float]]:
    """Replay *events*; return aligned (asym_z, forward_return) lists.

    ``forward_return`` is NaN where the boundary is within ``horizon`` of
    the end of the session (no forward mid available).
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

    # Boundaries are anchored to the first event so the study does not
    # depend on session-open / DST arithmetic (Inv-6: event-time only).
    first_ts = events[0].timestamp_ns
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
                "quote_replenish_asymmetry",
                horizon_seconds,
                feature_id=_FEATURE_ID,
            )
        ],
    )
    aggregator.attach()

    boundaries: list[tuple[int, float]] = []  # (boundary_ts_ns, asym_z)

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
    forward = [
        forward_return_at(times, mids, ts, float(horizon_seconds)) for ts, _ in boundaries
    ]
    return feature, forward


def _verdict(rho: float, p_value: float) -> str:
    if abs(rho) < 0.02 or p_value >= 0.05:
        return (
            "VERDICT: |rho| < 0.02 or not significant (p >= 0.05) -> the "
            "asymmetry z-score does not predict forward direction at this "
            "horizon. Mark sig_inventory_revert_v1 for decommission / "
            "re-research."
        )
    if rho > 0:
        return (
            "VERDICT: rho > 0 and significant -> the LONG-on-positive-asym_z "
            "convention is CONFIRMED. Pin this baseline in the alpha's "
            "falsification_criteria."
        )
    return (
        "VERDICT: rho < 0 and significant -> the sign is INVERTED. Flip the "
        "alpha to LONG when asym_z < 0, re-baseline, and re-lock the per-alpha "
        "test."
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD (cached session)")
    ap.add_argument("--horizon", type=int, default=30)
    ap.add_argument("--buckets", type=int, default=5)
    ap.add_argument("--cache-dir", default=None, help="defaults to ~/.feelies/cache")
    args = ap.parse_args(argv)

    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    log, _ingest, _meta = load_event_log_from_disk_cache(
        [args.symbol], args.date, args.date, cache_dir=cache_dir
    )
    events = [e for e in log.replay() if isinstance(e, (NBBOQuote, Trade))]
    if not events:
        print(f"no NBBOQuote/Trade events for {args.symbol} {args.date}")
        return 1

    feature, forward = compute_feature_and_forward_returns(
        events, symbol=args.symbol, horizon_seconds=args.horizon
    )
    pairs = [(f, r) for f, r in zip(feature, forward) if r == r]  # drop NaN forward
    print(
        f"{args.symbol} {args.date}: {len(events)} events, "
        f"{len(feature)} warm boundaries, {len(pairs)} with a forward "
        f"{args.horizon}s return"
    )
    if len(pairs) < 3:
        print(
            "insufficient warm boundaries with a forward return — need a "
            "fuller session (the rolling z-score needs ~30 warm boundaries)."
        )
        return 1

    feat = [p[0] for p in pairs]
    fwd = [p[1] for p in pairs]
    res = spearman_ic(feat, fwd)
    print(res)
    print("bucketed forward return (low asym_z -> high asym_z):")
    for b in bucketed_forward_return(feat, fwd, n_buckets=args.buckets):
        print(
            f"  asym_z in [{b.lo:+.3f}, {b.hi:+.3f}]  n={b.n:5d}  "
            f"mean_fwd_ret={b.mean_forward_return:+.6e}"
        )
    print(_verdict(res.rho, res.p_value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
