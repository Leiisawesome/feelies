#!/usr/bin/env python3
"""Extract boundary data for ``sig_sweep_kyle_drift_h900_v1`` validation.

Each symbol-session cell receives one deterministic replay. The script reuses
the census constants, filters, entry predicate, and estimators, then adds causal
Kyle-lambda features and forward mid returns at 120, 300, 900, and 1800 seconds.
Events are sorted and each cell starts with fresh sensor and regime state.

Usage
-----
    $env:PYTHONHASHSEED=0; uv run python `
        scripts/research/sweep_kyle_drift_validation_extract.py `
        --json docs/research/artifacts/sig_sweep_kyle_drift_h900_v1/`
boundaries_extract_YYYY-MM-DD.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from bisect import bisect_left, bisect_right
from datetime import datetime
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
if str(_REPO_ROOT / "scripts" / "research") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts" / "research"))

import sweep_kyle_drift_census as census  # noqa: E402  (pinned instrument)

from feelies.bootstrap import _horizon_features_for  # noqa: E402
from feelies.bus.event_bus import EventBus  # noqa: E402
from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote, Trade  # noqa: E402
from feelies.core.identifiers import SequenceGenerator  # noqa: E402
from feelies.core.session_clock import rth_open_ns  # noqa: E402
from feelies.features.aggregator import HorizonAggregator  # noqa: E402
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature  # noqa: E402
from feelies.sensors.horizon_scheduler import HorizonScheduler  # noqa: E402
from feelies.sensors.impl.kyle_lambda_60s import KyleLambda60sSensor  # noqa: E402
from feelies.sensors.registry import SensorRegistry  # noqa: E402
from feelies.sensors.spec import SensorSpec  # noqa: E402
from feelies.services.regime_engine import get_regime_engine  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402

_NS = census._NS
_TZ_ET = census._TZ_ET
_HORIZON = census._HORIZON
_TICK = census._TICK
_SFI_WINDOW_NS = census._SFI_WINDOW_NS
FWD_HORIZONS_S = (120, 300, 900, 1800)

# Offline diagnostic only; never part of the entry predicate.
_KYLE_SPEC = SensorSpec(
    sensor_id="kyle_lambda_60s",
    sensor_version="2.0.0",
    cls=KyleLambda60sSensor,
    params={
        "min_samples": 30,
        "alignment": "causal",
        "sensor_version": "2.0.0",
    },
    subscribes_to=(NBBOQuote, Trade),
)


def _fwd_log_return(
    quote_ts: list[int], quote_mid: list[float], t0: int, horizon_s: int
) -> float | None:
    """Forward mid log-return (last-mid-at-or-before endpoints, causal).

    Zero move returns 0.0 (a valid pair) — H8 convention; dropping ties
    would deflate the census-pinned episode n.
    """
    t1 = t0 + horizon_s * _NS
    if not quote_ts or t1 > quote_ts[-1]:
        return None
    i0 = bisect_right(quote_ts, t0) - 1
    i1 = bisect_right(quote_ts, t1) - 1
    if i0 < 0 or i1 < 0:
        return None
    m0, m1 = quote_mid[i0], quote_mid[i1]
    if m0 <= 0.0 or m1 <= 0.0:
        return None
    return math.log(m1 / m0)


def _validation_features() -> list[object]:
    """Census SFI wiring + kyle horizon features (passthrough for raw λ)."""
    return [
        *census._sfi_features(),
        SensorPassthroughFeature("kyle_lambda_60s", _HORIZON),
        *_horizon_features_for("kyle_lambda_60s", _HORIZON),
    ]


def extract_cell(cache: DiskEventCache, symbol: str, date: str) -> dict[str, object] | None:
    events = cache.load(symbol, date)
    if not events:
        return None
    events = [
        ev
        for ev in sorted(events, key=lambda e: (e.timestamp_ns, e.sequence))
        if census._in_rth(ev.exchange_timestamp_ns)
    ]
    if not events:
        return None
    session_open = rth_open_ns(events[0].timestamp_ns)
    is_grid = symbol in census.GRID_SYMBOLS
    n_quotes = sum(1 for e in events if isinstance(e, NBBOQuote))

    feats = _validation_features()
    fids = {f.feature_id for f in feats}  # type: ignore[attr-defined]
    assert set(census.ENTRY_WARM_IDS) <= fids, f"h={_HORIZON} wiring missing: {sorted(fids)}"

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus, sequence_generator=SequenceGenerator(), symbols=frozenset({symbol})
    )
    for spec in census.SENSOR_SPECS + (_KYLE_SPEC,):
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_HORIZON}),
        session_id=f"H10VAL_{symbol}_{date}",
        symbols=frozenset({symbol}),
        session_open_ns=session_open,
        sequence_generator=SequenceGenerator(),
    )
    aggregator = HorizonAggregator(
        bus=bus,
        symbols=frozenset({symbol}),
        sensor_buffer_seconds=2 * _HORIZON,
        sequence_generator=SequenceGenerator(),
        horizon_features=feats,  # type: ignore[arg-type]
    )
    aggregator.attach()

    engine = get_regime_engine("hmm_3state_fractional")
    cal_quotes = [e for e in events if isinstance(e, NBBOQuote)][
        : census.REGIME_CALIBRATION_MAX_QUOTES
    ]
    engine.calibrate(cal_quotes)
    state_names = tuple(engine.state_names)
    idx_breakout = state_names.index("vol_breakout")

    trade_ts: list[int] = []
    trade_size: list[float] = []
    trade_fail_filter: list[bool] = []
    trade_class_b: list[bool] = []
    for t in events:
        if not isinstance(t, Trade):
            continue
        trade_ts.append(t.timestamp_ns)
        trade_size.append(float(t.size))
        trade_fail_filter.append(census.trade_fails_sfi_filter(t))
        trade_class_b.append(
            bool(census.CLASS_B_CONDITIONS.intersection(t.conditions))
            or (t.correction is not None and t.correction in census.CORRECTION_RECORDS)
        )

    quote_ts: list[int] = []
    quote_mid: list[float] = []
    quote_spread: list[float] = []
    boundary_rows: list[tuple[int, dict, dict, dict, float | None]] = []
    n_seen = 0
    for ev in events:
        if isinstance(ev, NBBOQuote):
            engine.posterior(ev)
            b, a = float(ev.bid), float(ev.ask)
            if b > 0.0 and a > 0.0:
                quote_ts.append(ev.timestamp_ns)
                quote_mid.append((b + a) / 2.0)
                quote_spread.append(a - b)
        bus.publish(ev)
        for tick_ev in scheduler.on_event(ev):
            bus.publish(tick_ev)
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

    # σ₉₀₀ — census §1.2 estimator, verbatim.
    grid_mids: list[float | None] = []
    for k in range(0, (6 * 3600 + 30 * 60) // _HORIZON + 1):
        t0 = session_open + k * _HORIZON * _NS
        i = bisect_right(quote_ts, t0) - 1
        grid_mids.append(quote_mid[i] if i >= 0 else None)
    rets = [
        math.log(b2 / a2)
        for a2, b2 in zip(grid_mids, grid_mids[1:])
        if a2 is not None and b2 is not None and a2 > 0 and b2 > 0
    ]
    sigma900 = statistics.stdev(rets) * 1e4 if len(rets) >= 2 else None

    tape_prints = len(trade_ts)
    tape_flagged_class_b = sum(trade_class_b)
    tape_b_base = tape_flagged_class_b / tape_prints if tape_prints else 0.0
    cutoff_secs = census.SESSION_CUTOFF_ET[0] * 3600 + census.SESSION_CUTOFF_ET[1] * 60
    warm_counts = {fid: 0 for fid in census.ENTRY_WARM_IDS}

    n_in_window = 0
    n_warm_eligible = 0
    sfi_warm_in_window = 0
    episodes = 0
    episodes_long = 0
    episodes_short = 0
    residual_shares: list[float] = []

    out_rows: list[dict[str, object]] = []
    for asof_ns, values, warm, stale, p_breakout in boundary_rows:
        for fid in census.ENTRY_WARM_IDS:
            if warm.get(fid, False):
                warm_counts[fid] += 1
        offset_s = (asof_ns - session_open) // _NS
        dt_et = datetime.fromtimestamp(asof_ns / 1e9, tz=_TZ_ET)
        et_secs = dt_et.hour * 3600 + dt_et.minute * 60 + dt_et.second
        in_window = offset_s >= census.NO_ENTRY_FIRST_SECONDS and et_secs <= cutoff_secs
        if in_window:
            n_in_window += 1
            if warm.get("sweep_flow_imbalance", False):
                sfi_warm_in_window += 1

        all_warm = all(
            warm.get(fid, False) and not stale.get(fid, True) for fid in census.ENTRY_WARM_IDS
        )
        if in_window and all_warm:
            n_warm_eligible += 1

        qi = bisect_right(quote_ts, asof_ns) - 1
        spread_ticks = round(quote_spread[qi] / _TICK) if qi >= 0 else None

        sfi = values.get("sweep_flow_imbalance")
        pctl = values.get("sweep_flow_imbalance_percentile")
        rvz = values.get("realized_vol_30s_zscore")
        kyle = values.get("kyle_lambda_60s")
        kyle_pctl = values.get("kyle_lambda_60s_percentile")

        fwd = {str(h): _fwd_log_return(quote_ts, quote_mid, asof_ns, h) for h in FWD_HORIZONS_S}

        lo = bisect_left(trade_ts, asof_ns - _SFI_WINDOW_NS + 1)
        hi = bisect_right(trade_ts, asof_ns)
        n_win = hi - lo
        n_fail = sum(trade_fail_filter[lo:hi])
        residual_share = n_fail / n_win if n_win else 0.0
        n_b = sum(trade_class_b[lo:hi])
        b_share = n_b / n_win if n_win else 0.0
        class_b_intensity = bool(n_b > 0 and b_share >= census.INTENSITY_RATIO * tape_b_base)
        print_volume_900s = sum(trade_size[lo:hi])

        eligible = False
        side: str | None = None
        if is_grid and in_window and all_warm:
            ok, side = census.is_entry_eligible(
                sfi=sfi, pctl=pctl, rvz=rvz, p_breakout=p_breakout
            )
            if ok:
                eligible = True
                episodes += 1
                if side == "LONG":
                    episodes_long += 1
                else:
                    episodes_short += 1
                residual_shares.append(residual_share)

        out_rows.append(
            {
                "ts": asof_ns,
                "in_window": in_window,
                "all_warm": all_warm,
                "sfi": sfi,
                "sfi_pctl": pctl,
                "rvz": rvz,
                "p_breakout": p_breakout,
                "kyle_lambda_60s": kyle,
                "kyle_lambda_60s_percentile": kyle_pctl,
                "spread_ticks": spread_ticks,
                "print_volume_900s": print_volume_900s,
                "residual_non_a_share": residual_share,
                "class_b_intensity": class_b_intensity,
                "eligible": eligible,
                "side": side,
                "fwd": fwd,
            }
        )

    nb = max(len(boundary_rows), 1)
    viable_long = viable_short = None
    if is_grid and sigma900 is not None:
        viable_long = sigma900 >= census.FLOOR_LONG_BPS[symbol] / census.KAPPA_FROZEN
        viable_short = sigma900 >= census.FLOOR_SHORT_BPS[symbol] / census.KAPPA_FROZEN

    residual_mean = sum(residual_shares) / len(residual_shares) if residual_shares else None
    residual_bug = any(s > census.RESIDUAL_BUG_SHARE for s in residual_shares)

    return {
        "symbol": symbol,
        "date": date,
        "stratum": census.STRATUM[date],
        "n_events": len(events),
        "n_quotes": n_quotes,
        "n_trades": tape_prints,
        "n_boundaries": len(boundary_rows),
        "n_in_window": n_in_window,
        "n_warm_eligible": n_warm_eligible,
        "sfi_warm_fraction_in_window": (
            sfi_warm_in_window / n_in_window if n_in_window else None
        ),
        "sigma900_bps": sigma900,
        "sigma900_n_returns": len(rets),
        "viable_long": viable_long,
        "viable_short": viable_short,
        "episodes": episodes,
        "episodes_long": episodes_long,
        "episodes_short": episodes_short,
        "residual_non_a_share_mean": residual_mean,
        "residual_bug_flag": residual_bug,
        "warm_fraction": {fid: warm_counts[fid] / nb for fid in census.ENTRY_WARM_IDS},
        "boundaries": out_rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path.home() / ".feelies" / "cache")
    ap.add_argument("--json", type=Path, required=True)
    ap.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated symbol smoke filter (default: full SYMBOLS)",
    )
    ap.add_argument(
        "--dates",
        type=str,
        default=None,
        help="Comma-separated date smoke filter (default: full grid dates)",
    )
    args = ap.parse_args(argv)

    symbols = tuple(s.strip() for s in args.symbols.split(",")) if args.symbols else census.SYMBOLS
    date_filter = (
        frozenset(d.strip() for d in args.dates.split(",")) if args.dates else None
    )

    cache = DiskEventCache(args.cache_dir)
    cells: list[dict[str, object]] = []
    for symbol in symbols:
        if symbol not in census.SYMBOLS:
            print(f"unknown symbol {symbol!r}", file=sys.stderr)
            return 1
        dates = census.DATES_ALL if symbol in census.GRID_SYMBOLS else census.DATES
        if date_filter is not None:
            dates = tuple(d for d in dates if d in date_filter)
        for date in dates:
            print(f"# {symbol} {date} ...", file=sys.stderr, flush=True)
            cell = extract_cell(cache, symbol, date)
            if cell is None:
                print(f"  ! MISSING cache for {symbol}/{date}", file=sys.stderr)
                return 1
            cells.append(cell)

    out = {
        "protocol": (
            "sig_sweep_kyle_drift_h900_v1_validation_protocol.md step 2 extraction"
        ),
        "instrument": (
            "sweep_kyle_drift_census.py constants imported; additive kyle_lambda_60s "
            "v2.0.0 + forward returns — episode predicate untouched"
        ),
        "grid": "{APP,RMBS} x 20 + OLN x 10 preamble (evidence-only)",
        "fwd_horizons_s": list(FWD_HORIZONS_S),
        "cells": cells,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, indent=2, sort_keys=True)
    args.json.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
