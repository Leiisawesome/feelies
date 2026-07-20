#!/usr/bin/env python3
"""Measure Class-B print contamination at the H8 entry point.

The read compares flagged-print shares in eligible trailing 60-second windows
with full-session base rates. A share at least twice APP's base rate is material.
It computes no forward returns, IC, or signals. Replays use production sensors,
the 300-second grid, causal regime calibration, and deterministic event order.
"""

from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from feelies.bootstrap import _horizon_features_for  # noqa: E402
from feelies.bus.event_bus import EventBus  # noqa: E402
from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote, Trade  # noqa: E402
from feelies.core.identifiers import SequenceGenerator  # noqa: E402
from feelies.core.session_clock import rth_open_ns  # noqa: E402
from feelies.features.aggregator import HorizonAggregator  # noqa: E402
from feelies.sensors.horizon_scheduler import HorizonScheduler  # noqa: E402
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor  # noqa: E402
from feelies.sensors.impl.micro_price import MicroPriceSensor  # noqa: E402
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor  # noqa: E402
from feelies.sensors.registry import SensorRegistry  # noqa: E402
from feelies.sensors.spec import SensorSpec  # noqa: E402
from feelies.services.regime_engine import get_regime_engine  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_HORIZON = 300

# ── Frozen evidence set (03c §5.1, same 10 dates as the 8-F census) ──────

SYMBOLS = ("APP", "RMBS")
DATES = (
    "2025-11-25",
    "2025-12-04",
    "2025-12-22",
    "2026-01-05",
    "2026-01-15",
    "2026-01-26",
    "2026-01-27",
    "2026-04-01",
    "2026-04-10",
    "2026-04-22",
)

# ── Frozen H8 entry constants (card; pack-05 medians) ────────────────────

LAMBDA_PCTL_MIN = 0.5  # the median split under resolution
# 0.75 x median sigma_300 (pack-05 map p50: APP 33.8084, RMBS 31.622 bps),
# expressed as a FRACTION of the micro-price level.
DISLOC_FRAC_MIN = {"APP": 25.3563e-4, "RMBS": 23.7165e-4}
P_VOL_BREAKOUT_MAX = 0.7
RV_Z_MAX = 3.0
ENTRY_WARM_IDS = (
    "kyle_lambda_60s_percentile",
    "micro_price_drift",
    "micro_price",
    "realized_vol_30s_zscore",
)
NO_ENTRY_FIRST_SECONDS = 300
SESSION_CUTOFF_ET = (15, 50)

# ── 03b contamination sets (§3.3 Class B / §4.4 correction records) ──────

CLASS_B_CONDITIONS = frozenset({2, 7, 8, 9, 10, 13, 15, 16, 17, 22, 29, 32, 35, 52, 53})
CORRECTION_RECORDS = frozenset({10, 11, 12})
CONTAM_WINDOW_NS = 60 * _NS  # the kyle_lambda_60s trailing sensor window

# ── Pre-registered materiality criterion ─────────────────────────────────

MATERIALITY_RATIO = 2.0  # region share >= 2.0 x base rate (count OR volume)

# ── Reference sensor specs (platform.yaml, verbatim params) ──────────────

SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="kyle_lambda_60s",
        sensor_version="2.0.0",
        cls=KyleLambda60sSensor,
        params={"min_samples": 30, "alignment": "causal", "sensor_version": "2.0.0"},
        subscribes_to=(NBBOQuote, Trade),
    ),
    SensorSpec(
        sensor_id="micro_price",
        sensor_version="1.1.0",
        cls=MicroPriceSensor,
        params={"warm_after": 1, "warm_window_seconds": 60},
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 16},
        subscribes_to=(NBBOQuote,),
    ),
)

REGIME_CALIBRATION_MAX_QUOTES = 100_000  # platform.yaml regime_calibration_max_quotes


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


@dataclass
class CellResult:
    symbol: str
    date: str
    n_events: int
    n_quotes: int
    n_trades: int
    n_boundaries: int
    n_in_window: int
    n_warm_eligible: int
    n_conditioning: int  # full H8 entry-point boundaries
    # Region print population (pooled trailing-60s windows of conditioning
    # boundaries; h=300 >> 60 s so windows never overlap):
    region_prints: int = 0
    region_flagged_prints: int = 0
    region_volume: float = 0.0
    region_flagged_volume: float = 0.0
    # Session tape base rate (all RTH prints):
    tape_prints: int = 0
    tape_flagged_prints: int = 0
    tape_volume: float = 0.0
    tape_flagged_volume: float = 0.0
    # Binary any-flag boundary rates (reference):
    conditioning_flagged_boundaries: int = 0
    in_window_flagged_boundaries: int = 0
    warm_fraction: dict[str, float] = field(default_factory=dict)


def run_cell(cache: DiskEventCache, symbol: str, date: str) -> CellResult | None:
    events = cache.load(symbol, date)
    if not events:
        return None
    events = [
        ev
        for ev in sorted(events, key=lambda e: (e.timestamp_ns, e.sequence))
        if _in_rth(ev.exchange_timestamp_ns)
    ]
    if not events:
        return None
    n_quotes = sum(1 for e in events if isinstance(e, NBBOQuote))
    session_open = rth_open_ns(events[0].timestamp_ns)

    feats = [
        f
        for sid in ("kyle_lambda_60s", "micro_price", "realized_vol_30s")
        for f in _horizon_features_for(sid, _HORIZON)
    ]
    fids = {f.feature_id for f in feats}
    assert {"kyle_lambda_60s_percentile", "micro_price_drift", "micro_price"} <= fids, (
        f"required h={_HORIZON} features not wired: {sorted(fids)}"
    )

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)  # type: ignore[arg-type]

    registry = SensorRegistry(
        bus=bus,
        sequence_generator=SequenceGenerator(),
        symbols=frozenset({symbol}),
    )
    for spec in SENSOR_SPECS:
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_HORIZON}),
        session_id=f"H8CONTAM_{symbol}_{date}",
        symbols=frozenset({symbol}),
        session_open_ns=session_open,
        sequence_generator=SequenceGenerator(),
    )
    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({symbol}),
        sensor_buffer_seconds=2 * _HORIZON,
        sequence_generator=SequenceGenerator(),
        horizon_features=feats,
    )
    aggregator.attach()

    engine = get_regime_engine("hmm_3state_fractional")
    cal_quotes = [e for e in events if isinstance(e, NBBOQuote)][:REGIME_CALIBRATION_MAX_QUOTES]
    engine.calibrate(cal_quotes)
    names = tuple(engine.state_names)
    idx_breakout = names.index("vol_breakout")

    # Print tape: (ts, size, flagged) for every RTH trade.
    trade_ts: list[int] = []
    trade_size: list[float] = []
    trade_flagged: list[bool] = []
    for t in events:
        if not isinstance(t, Trade):
            continue
        flagged = bool(CLASS_B_CONDITIONS.intersection(t.conditions)) or (
            t.correction is not None and t.correction in CORRECTION_RECORDS
        )
        trade_ts.append(t.timestamp_ns)
        trade_size.append(float(t.size))
        trade_flagged.append(flagged)

    boundary_rows: list[tuple[int, dict, dict, dict, float | None]] = []
    n_seen = 0
    for ev in events:
        if isinstance(ev, NBBOQuote):
            engine.posterior(ev)
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)
        while n_seen < len(captured):
            s = captured[n_seen]
            n_seen += 1
            if s.horizon_seconds != _HORIZON:
                continue
            post = engine.current_state(symbol)
            p_breakout = post[idx_breakout] if post is not None else None
            boundary_rows.append(
                (s.boundary_ts_ns, dict(s.values), dict(s.warm), dict(s.stale), p_breakout)
            )

    res = CellResult(
        symbol=symbol,
        date=date,
        n_events=len(events),
        n_quotes=n_quotes,
        n_trades=len(trade_ts),
        n_boundaries=len(boundary_rows),
        n_in_window=0,
        n_warm_eligible=0,
        n_conditioning=0,
        tape_prints=len(trade_ts),
        tape_flagged_prints=sum(trade_flagged),
        tape_volume=sum(trade_size),
        tape_flagged_volume=sum(sz for sz, fl in zip(trade_size, trade_flagged) if fl),
    )

    warm_counts = {fid: 0 for fid in ENTRY_WARM_IDS}
    cutoff_secs = SESSION_CUTOFF_ET[0] * 3600 + SESSION_CUTOFF_ET[1] * 60
    disloc_min = DISLOC_FRAC_MIN[symbol]
    for asof_ns, values, warm, stale, p_breakout in boundary_rows:
        for fid in ENTRY_WARM_IDS:
            if warm.get(fid, False):
                warm_counts[fid] += 1
        offset_s = (asof_ns - session_open) // _NS
        dt_et = datetime.fromtimestamp(asof_ns / 1e9, tz=_TZ_ET)
        et_secs = dt_et.hour * 3600 + dt_et.minute * 60 + dt_et.second
        if offset_s < NO_ENTRY_FIRST_SECONDS or et_secs > cutoff_secs:
            continue
        res.n_in_window += 1

        lo = bisect_left(trade_ts, asof_ns - CONTAM_WINDOW_NS + 1)
        hi = bisect_right(trade_ts, asof_ns)
        window_any_flag = any(trade_flagged[lo:hi])
        if window_any_flag:
            res.in_window_flagged_boundaries += 1

        all_warm = all(warm.get(fid, False) and not stale.get(fid, True) for fid in ENTRY_WARM_IDS)
        if not all_warm:
            continue
        res.n_warm_eligible += 1

        pctl = values.get("kyle_lambda_60s_percentile")
        drift = values.get("micro_price_drift")
        mp = values.get("micro_price")
        rvz = values.get("realized_vol_30s_zscore")
        if pctl is None or drift is None or mp is None or rvz is None or mp <= 0.0:
            continue
        if p_breakout is None:
            continue
        if (
            pctl < LAMBDA_PCTL_MIN
            or abs(drift) / mp < disloc_min
            or p_breakout >= P_VOL_BREAKOUT_MAX
            or rvz > RV_Z_MAX
        ):
            continue

        res.n_conditioning += 1
        if window_any_flag:
            res.conditioning_flagged_boundaries += 1
        res.region_prints += hi - lo
        res.region_flagged_prints += sum(trade_flagged[lo:hi])
        res.region_volume += sum(trade_size[lo:hi])
        res.region_flagged_volume += sum(
            sz for sz, fl in zip(trade_size[lo:hi], trade_flagged[lo:hi]) if fl
        )

    nb = max(res.n_boundaries, 1)
    res.warm_fraction = {fid: warm_counts[fid] / nb for fid in ENTRY_WARM_IDS}
    return res


def _share(num: float, den: float) -> float | None:
    return num / den if den > 0 else None


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path.home() / ".feelies" / "cache")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    cache = DiskEventCache(args.cache_dir)
    cells: list[CellResult] = []
    for symbol in SYMBOLS:
        for date in DATES:
            print(f"# {symbol} {date} ...", file=sys.stderr, flush=True)
            cell = run_cell(cache, symbol, date)
            if cell is None:
                print(f"  ! MISSING cache for {symbol}/{date}", file=sys.stderr)
                continue
            cells.append(cell)

    per_symbol: dict[str, dict] = {}
    for symbol in SYMBOLS:
        sc = [c for c in cells if c.symbol == symbol]
        rp = sum(c.region_prints for c in sc)
        rfp = sum(c.region_flagged_prints for c in sc)
        rv = sum(c.region_volume for c in sc)
        rfv = sum(c.region_flagged_volume for c in sc)
        tp = sum(c.tape_prints for c in sc)
        tfp = sum(c.tape_flagged_prints for c in sc)
        tv = sum(c.tape_volume for c in sc)
        tfv = sum(c.tape_flagged_volume for c in sc)
        region_count_share = _share(rfp, rp)
        region_vol_share = _share(rfv, rv)
        base_count_share = _share(tfp, tp)
        base_vol_share = _share(tfv, tv)
        ratio_count = (
            region_count_share / base_count_share
            if region_count_share is not None and base_count_share
            else None
        )
        ratio_vol = (
            region_vol_share / base_vol_share
            if region_vol_share is not None and base_vol_share
            else None
        )
        elevated = (ratio_count is not None and ratio_count >= MATERIALITY_RATIO) or (
            ratio_vol is not None and ratio_vol >= MATERIALITY_RATIO
        )
        n_cond = sum(c.n_conditioning for c in sc)
        n_win = sum(c.n_in_window for c in sc)
        per_symbol[symbol] = {
            "n_cells": len(sc),
            "n_boundaries_in_window": n_win,
            "n_warm_eligible": sum(c.n_warm_eligible for c in sc),
            "n_conditioning": n_cond,
            "region_prints": rp,
            "region_flagged_print_share": region_count_share,
            "region_flagged_volume_share": region_vol_share,
            "tape_prints": tp,
            "tape_flagged_print_share": base_count_share,
            "tape_flagged_volume_share": base_vol_share,
            "ratio_count_basis": ratio_count,
            "ratio_volume_basis": ratio_vol,
            "binary_flag_rate_conditioning": _share(
                sum(c.conditioning_flagged_boundaries for c in sc), n_cond
            ),
            "binary_flag_rate_all_in_window": _share(
                sum(c.in_window_flagged_boundaries for c in sc), n_win
            ),
            "materially_elevated": elevated,
        }

    out = {
        "protocol": "Task 7 Amendment C contamination read (H8 entry point)",
        "materiality_criterion": (
            f"region flagged-print share >= {MATERIALITY_RATIO} x tape base rate "
            "(count OR volume basis), pre-registered"
        ),
        "entry_constants": {
            "horizon_seconds": _HORIZON,
            "lambda_percentile_min": LAMBDA_PCTL_MIN,
            "dislocation_frac_min": DISLOC_FRAC_MIN,
            "p_vol_breakout_max": P_VOL_BREAKOUT_MAX,
            "rv_zscore_max": RV_Z_MAX,
        },
        "cells": [asdict(c) for c in cells],
        "per_symbol": per_symbol,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"wrote {args.json}", file=sys.stderr)

    print("\n== Cells ==")
    hdr = (
        f"{'sym':<5}{'date':<12}{'bnd':>5}{'win':>5}{'warm':>6}{'cond':>6}"
        f"{'rPrints':>9}{'rFlag%':>8}{'tape%':>8}{'binC%':>7}{'binW%':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for c in cells:
        r_share = _share(c.region_flagged_prints, c.region_prints)
        t_share = _share(c.tape_flagged_prints, c.tape_prints)
        bc = _share(c.conditioning_flagged_boundaries, c.n_conditioning)
        bw = _share(c.in_window_flagged_boundaries, c.n_in_window)
        fmt = lambda x: "  n/a" if x is None else f"{100 * x:5.2f}"  # noqa: E731
        print(
            f"{c.symbol:<5}{c.date:<12}{c.n_boundaries:>5}{c.n_in_window:>5}"
            f"{c.n_warm_eligible:>6}{c.n_conditioning:>6}{c.region_prints:>9}"
            f"{fmt(r_share):>8}{fmt(t_share):>8}{fmt(bc):>7}{fmt(bw):>7}"
        )
    print("\n== Per-symbol roll-up ==")
    for symbol in SYMBOLS:
        print(f"{symbol}: {json.dumps(per_symbol[symbol])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
