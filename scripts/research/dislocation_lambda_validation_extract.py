#!/usr/bin/env python3
"""Task 11 (Task 8 steps 2-6) — boundary-level extraction for
``sig_dislocation_lambda_drift_v1`` statistical validation.

ONE deterministic replay per (symbol, session) cell over the frozen
20-session grid ({APP, RMBS} x 20; OLN x 10 original cells
evidence-only), producing the boundary-level dataset every step-2..6
statistic is computed from (``dislocation_lambda_validation_stats.py``).

Instrument integrity: the replay pipeline, episode predicate, sensor
specs, regime machinery, RTH filter, session anchor, warm handling,
sigma_300 estimator, and JC-1 contamination instrument are transplanted
from the committed census script
(``scripts/research/dislocation_lambda_census.py`` — itself verbatim
from the Appendix-A read @ 8c69d49); the census module is IMPORTED so
the constants are shared, not copied.  The stats script asserts that
the per-cell eligible counts (incl/primary/binary) reproduce the
committed EXPANDED CENSUS artifact exactly before any statistic is
scored.

Additive outputs beyond the census (reporting extensions; the episode
predicate is untouched — count-direction neutral, protocol §1.1
deviation-table convention):

- per-boundary forward mid log-returns at t in {60, 120, 300, 600} s
  (the FIRST forward-return contact for this candidate — protocol
  step 2; +1 N on the primary trial per FQ-6B-R);
- forward returns keep zero-move boundaries (log(m1/m0) = 0.0 is a
  valid pair) so the A-2.1 ruled evidence-set counts (657/574/1,231)
  are preserved; the sensor_feature_ic harness's ``m1 == m0 -> None``
  convention would silently deflate them;
- per-boundary regime dominant state + P(vol_breakout) (step 4 vol
  axis, step 6 screen bounds), boundary-time prevailing spread ticks
  (step 4 spread axis), trailing 300 s mid drift (L5), trailing-60 s
  window trade-classification agreement (L6), episode-window
  contra-side volume via quote-position-of-print with tick-rule
  fallback (I-1 funding pool), ofi_ewma boundary sign (§6.2 flow
  agreement — sensor added alongside; independent state, cannot
  perturb the census sensors);
- per-session regime diagnostics (discriminability, occupancy,
  screen-OFF fraction, screen-ON dwell runs) for the §6.1 JC-5 bounds.

OLN cells skip the regime engine (no OLN output consumes it —
count-direction neutral, disclosed).

Determinism: PYTHONHASHSEED=0; no RNG, no wall-clock reads; events
sorted by (timestamp_ns, sequence); fresh sensor/regime state per cell;
bit-identical re-run required (P0-4).

Usage
-----
    PYTHONHASHSEED=0 uv run python \
        scripts/research/dislocation_lambda_validation_extract.py \
        --json docs/research/artifacts/sig_dislocation_lambda_drift_v1/\
boundaries_extract_2026-07-14.json
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

import dislocation_lambda_census as census  # noqa: E402  (pinned instrument)

from feelies.bootstrap import _horizon_features_for  # noqa: E402
from feelies.bus.event_bus import EventBus  # noqa: E402
from feelies.core.events import HorizonFeatureSnapshot, NBBOQuote, Trade  # noqa: E402
from feelies.core.identifiers import SequenceGenerator  # noqa: E402
from feelies.core.session_clock import rth_open_ns  # noqa: E402
from feelies.features.aggregator import HorizonAggregator  # noqa: E402
from feelies.sensors.horizon_scheduler import HorizonScheduler  # noqa: E402
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor  # noqa: E402
from feelies.sensors.registry import SensorRegistry  # noqa: E402
from feelies.sensors.spec import SensorSpec  # noqa: E402
from feelies.services.regime_engine import get_regime_engine  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402

_NS = census._NS
_TZ_ET = census._TZ_ET
_HORIZON = census._HORIZON
_TICK = census._TICK
FWD_HORIZONS_S = (60, 120, 300, 600)  # protocol §4.4 IC(t) grid (JC-7)

# ofi_ewma spec mirrors scripts/sensor_feature_ic.py (reference params);
# offline diagnostic only (spec §16 row 5) — never in the entry predicate.
_OFI_SPEC = SensorSpec(
    sensor_id="ofi_ewma",
    sensor_version="1.1.0",
    cls=OFIEwmaSensor,
    params={"alpha": 0.1, "warm_after": 50, "warm_window_seconds": 300},
    subscribes_to=(NBBOQuote,),
)


def _fwd_log_return(
    quote_ts: list[int], quote_mid: list[float], t0: int, horizon_s: int
) -> float | None:
    """Forward mid log-return (last-mid-at-or-before endpoints, causal).

    Unlike sensor_feature_ic._forward_return, a zero move returns 0.0
    (a valid pair) — dropping ties would deflate the A-2.1 ruled ns.
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


def _classify_trades(
    trade_ts: list[int],
    trade_px: list[float],
    quote_ts: list[int],
    quote_mid: list[float],
) -> tuple[list[int], list[int]]:
    """(quote-position side, tick-rule side) per trade; +1 buy / -1 sell /
    0 unresolved.  Quote-position: price vs prevailing mid (at-or-before).
    Tick rule: vs last different trade price, zero-tick carries."""
    qp: list[int] = []
    tick: list[int] = []
    last_px: float | None = None
    last_tick = 0
    for ts, px in zip(trade_ts, trade_px):
        qi = bisect_right(quote_ts, ts) - 1
        if qi >= 0:
            mid = quote_mid[qi]
            qp.append(1 if px > mid else (-1 if px < mid else 0))
        else:
            qp.append(0)
        if last_px is None or px == last_px:
            tick.append(last_tick)
        else:
            last_tick = 1 if px > last_px else -1
            tick.append(last_tick)
        last_px = px
    return qp, tick


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

    feats = [
        f
        for sid in ("kyle_lambda_60s", "micro_price", "realized_vol_30s", "ofi_ewma")
        for f in _horizon_features_for(sid, _HORIZON)
    ]
    fids = {f.feature_id for f in feats}
    assert set(census.ENTRY_WARM_IDS) <= fids, f"h={_HORIZON} wiring missing: {sorted(fids)}"

    bus = EventBus()
    captured: list[HorizonFeatureSnapshot] = []
    bus.subscribe(HorizonFeatureSnapshot, captured.append)  # type: ignore[arg-type]
    registry = SensorRegistry(
        bus=bus, sequence_generator=SequenceGenerator(), symbols=frozenset({symbol})
    )
    for spec in census.SENSOR_SPECS + (_OFI_SPEC,):
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_HORIZON}),
        session_id=f"H8VAL_{symbol}_{date}",
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

    engine = None
    idx_breakout = -1
    state_names: tuple[str, ...] = ()
    if is_grid:
        engine = get_regime_engine("hmm_3state_fractional")
        cal_quotes = [e for e in events if isinstance(e, NBBOQuote)][
            : census.REGIME_CALIBRATION_MAX_QUOTES
        ]
        engine.calibrate(cal_quotes)
        state_names = tuple(engine.state_names)
        idx_breakout = state_names.index("vol_breakout")

    # Print tape (contamination + side classification inputs).
    trade_ts: list[int] = []
    trade_px: list[float] = []
    trade_size: list[float] = []
    trade_flagged: list[bool] = []
    for t in events:
        if not isinstance(t, Trade):
            continue
        trade_ts.append(t.timestamp_ns)
        trade_px.append(float(t.price))
        trade_size.append(float(t.size))
        trade_flagged.append(
            bool(census.CLASS_B_CONDITIONS.intersection(t.conditions))
            or (t.correction is not None and t.correction in census.CORRECTION_RECORDS)
        )

    quote_ts: list[int] = []
    quote_mid: list[float] = []
    quote_spread: list[float] = []

    # Regime + screen-dwell tracking (per-quote; §6.1 JC-5 bounds).
    occ = [0] * max(len(state_names), 1)
    n_rth_quotes = 0
    latched_rvz: float | None = None
    screen_state: bool | None = None
    run_start_ns = 0
    on_runs_s: list[float] = []
    last_quote_ns = 0

    boundary_rows: list[tuple[int, dict, dict, dict, float | None, str | None]] = []
    n_seen = 0
    for ev in events:
        if isinstance(ev, NBBOQuote):
            n_rth_quotes += 1
            b, a = float(ev.bid), float(ev.ask)
            if b > 0.0 and a > 0.0:
                quote_ts.append(ev.timestamp_ns)
                quote_mid.append((b + a) / 2.0)
                quote_spread.append(a - b)
            if engine is not None:
                p = engine.posterior(ev)
                occ[max(range(len(p)), key=lambda i: p[i])] += 1
                on_now = (
                    p[idx_breakout] < census.P_VOL_BREAKOUT_MAX
                    and latched_rvz is not None
                    and latched_rvz <= census.RV_Z_MAX
                )
                if screen_state is None:
                    screen_state = on_now
                    run_start_ns = ev.timestamp_ns
                elif on_now != screen_state:
                    if screen_state:
                        on_runs_s.append((ev.timestamp_ns - run_start_ns) / 1e9)
                    screen_state = on_now
                    run_start_ns = ev.timestamp_ns
                last_quote_ns = ev.timestamp_ns
        bus.publish(ev)
        for tick_ev in scheduler.on_event(ev):
            bus.publish(tick_ev)
        while n_seen < len(captured):
            s = captured[n_seen]
            n_seen += 1
            if s.horizon_seconds != _HORIZON:
                continue
            p_breakout: float | None = None
            dominant: str | None = None
            if engine is not None:
                post = engine.current_state(symbol)
                if post is not None:
                    p_breakout = post[idx_breakout]
                    dominant = state_names[max(range(len(post)), key=lambda i: post[i])]
            if s.warm.get("realized_vol_30s_zscore", False) and not s.stale.get(
                "realized_vol_30s_zscore", True
            ):
                latched_rvz = s.values.get("realized_vol_30s_zscore")
            boundary_rows.append(
                (
                    s.boundary_ts_ns,
                    dict(s.values),
                    dict(s.warm),
                    dict(s.stale),
                    p_breakout,
                    dominant,
                )
            )
    if screen_state is True and last_quote_ns > run_start_ns:
        on_runs_s.append((last_quote_ns - run_start_ns) / 1e9)

    # sigma_300 (census §1.2 estimator, verbatim).
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
    sigma300 = statistics.stdev(rets) * 1e4 if len(rets) >= 2 else None

    tape_prints = len(trade_ts)
    tape_flagged = sum(trade_flagged)
    tape_volume = sum(trade_size)
    tape_flagged_volume = sum(sz for sz, fl in zip(trade_size, trade_flagged) if fl)
    count_base = tape_flagged / tape_prints if tape_prints else 0.0
    volume_base = tape_flagged_volume / tape_volume if tape_volume else 0.0

    side_qp, side_tick = _classify_trades(trade_ts, trade_px, quote_ts, quote_mid)

    disloc_min = census.DISLOC_FRAC_MIN_FROZEN.get(symbol)
    cutoff_secs = census.SESSION_CUTOFF_ET[0] * 3600 + census.SESSION_CUTOFF_ET[1] * 60
    warm_counts = {fid: 0 for fid in census.ENTRY_WARM_IDS}

    out_rows: list[dict[str, object]] = []
    for asof_ns, values, warm, stale, p_breakout, dominant in boundary_rows:
        for fid in census.ENTRY_WARM_IDS:
            if warm.get(fid, False):
                warm_counts[fid] += 1
        offset_s = (asof_ns - session_open) // _NS
        dt_et = datetime.fromtimestamp(asof_ns / 1e9, tz=_TZ_ET)
        et_secs = dt_et.hour * 3600 + dt_et.minute * 60 + dt_et.second
        in_window = offset_s >= census.NO_ENTRY_FIRST_SECONDS and et_secs <= cutoff_secs
        all_warm = all(
            warm.get(fid, False) and not stale.get(fid, True) for fid in census.ENTRY_WARM_IDS
        )
        qi = bisect_right(quote_ts, asof_ns) - 1
        spread_ticks = round(quote_spread[qi] / _TICK) if qi >= 0 else None
        mid0 = quote_mid[qi] if qi >= 0 else None
        i_back = bisect_right(quote_ts, asof_ns - _HORIZON * _NS) - 1
        mid_back = quote_mid[i_back] if i_back >= 0 else None

        pctl = values.get("kyle_lambda_60s_percentile")
        drift = values.get("micro_price_drift")
        mp = values.get("micro_price")
        rvz = values.get("realized_vol_30s_zscore")
        ofi = values.get("ofi_ewma")
        x = None
        if drift is not None and mp is not None and mp > 0.0:
            x = drift / mp

        fwd = {str(h): _fwd_log_return(quote_ts, quote_mid, asof_ns, h) for h in FWD_HORIZONS_S}

        # §1.3 contamination on the trailing 60 s window (JC-1 instrument).
        lo = bisect_left(trade_ts, asof_ns - census.CONTAM_WINDOW_NS + 1)
        hi = bisect_right(trade_ts, asof_ns)
        w_prints = hi - lo
        w_flagged = sum(trade_flagged[lo:hi])
        w_volume = sum(trade_size[lo:hi])
        w_flagged_volume = sum(sz for sz, fl in zip(trade_size[lo:hi], trade_flagged[lo:hi]) if fl)
        count_share = w_flagged / w_prints if w_prints else 0.0
        volume_share = w_flagged_volume / w_volume if w_volume else 0.0
        excluded_primary = w_flagged > 0 and count_share >= census.INTENSITY_RATIO * count_base
        excluded_volume = (
            w_flagged_volume > 0 and volume_share >= census.INTENSITY_RATIO * volume_base
        )
        any_flag = w_flagged > 0

        # L6: trailing-window trade-classification agreement.
        n_both = n_agree = 0
        for j in range(lo, hi):
            if side_qp[j] != 0 and side_tick[j] != 0:
                n_both += 1
                if side_qp[j] == side_tick[j]:
                    n_agree += 1

        # Census §1.1 eligible predicate (grid symbols only).
        eligible = False
        if (
            is_grid
            and in_window
            and all_warm
            and pctl is not None
            and x is not None
            and rvz is not None
            and p_breakout is not None
            and disloc_min is not None
        ):
            eligible = (
                pctl >= census.LAMBDA_PCTL_MIN
                and abs(x) >= disloc_min
                and p_breakout < census.P_VOL_BREAKOUT_MAX
                and rvz <= census.RV_Z_MAX
            )

        episode: dict[str, object] | None = None
        if eligible and drift is not None:
            e_lo = bisect_right(trade_ts, asof_ns)
            e_hi = bisect_right(trade_ts, asof_ns + _HORIZON * _NS)
            contra_vol = with_vol = uncls_vol = 0.0
            want_contra = -1 if drift > 0.0 else 1
            for j in range(e_lo, e_hi):
                side = side_qp[j] if side_qp[j] != 0 else side_tick[j]
                if side == 0:
                    uncls_vol += trade_size[j]
                elif side == want_contra:
                    contra_vol += trade_size[j]
                else:
                    with_vol += trade_size[j]
            episode = {
                "contra_vol": contra_vol,
                "with_vol": with_vol,
                "unclassified_vol": uncls_vol,
            }

        out_rows.append(
            {
                "ts": asof_ns,
                "in_window": in_window,
                "all_warm": all_warm,
                "pctl": pctl,
                "drift": drift,
                "mp": mp,
                "rvz": rvz,
                "p_vb": p_breakout,
                "dominant": dominant,
                "spread_ticks": spread_ticks,
                "mid0": mid0,
                "mid_back": mid_back,
                "x": x,
                "fwd": fwd,
                "ofi": ofi,
                "contam": {
                    "prints": w_prints,
                    "flagged": w_flagged,
                    "volume": w_volume,
                    "flagged_volume": w_flagged_volume,
                },
                "excluded_primary": excluded_primary,
                "excluded_volume": excluded_volume,
                "any_flag": any_flag,
                "eligible_incl": eligible,
                "episode": episode,
                "l6": {"n_both": n_both, "n_agree": n_agree},
            }
        )

    nb = max(len(boundary_rows), 1)
    viable_long = viable_short = None
    if is_grid and sigma300 is not None:
        viable_long = sigma300 >= census.FLOOR_LONG_BPS[symbol] / census.KAPPA_FROZEN
        viable_short = sigma300 >= census.FLOOR_SHORT_BPS[symbol] / census.KAPPA_FROZEN

    regime_block: dict[str, object] | None = None
    if engine is not None:
        denom = max(n_rth_quotes, 1)
        regime_block = {
            "discriminability": float(getattr(engine, "discriminability", float("nan"))),
            "occupancy": {state_names[i]: occ[i] / denom for i in range(len(state_names))},
            "screen_on_runs_seconds": [round(r, 3) for r in on_runs_s],
        }

    return {
        "symbol": symbol,
        "date": date,
        "stratum": census.STRATUM[date],
        "org": "EXP" if date in census.DATES_EXPANSION else "ORIG",
        "n_events": len(events),
        "n_trades": tape_prints,
        "n_boundaries": len(boundary_rows),
        "sigma300_bps": sigma300,
        "sigma300_n_returns": len(rets),
        "viable_long": viable_long,
        "viable_short": viable_short,
        "warm_fraction": {fid: warm_counts[fid] / nb for fid in census.ENTRY_WARM_IDS},
        "tape": {
            "prints": tape_prints,
            "flagged_prints": tape_flagged,
            "volume": tape_volume,
            "flagged_volume": tape_flagged_volume,
            "count_base": count_base,
            "volume_base": volume_base,
        },
        "regime": regime_block,
        "boundaries": out_rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path.home() / ".feelies" / "cache")
    ap.add_argument("--json", type=Path, required=True)
    args = ap.parse_args(argv)

    cache = DiskEventCache(args.cache_dir)
    cells: list[dict[str, object]] = []
    for symbol in census.SYMBOLS:
        dates = census.DATES
        if symbol in census.GRID_SYMBOLS:
            dates = tuple(sorted(census.DATES + census.DATES_EXPANSION))
        for date in dates:
            print(f"# {symbol} {date} ...", file=sys.stderr, flush=True)
            cell = extract_cell(cache, symbol, date)
            if cell is None:
                print(f"  ! MISSING cache for {symbol}/{date}", file=sys.stderr)
                return 1
            cells.append(cell)

    out = {
        "protocol": (
            "sig_dislocation_lambda_drift_v1_validation_protocol.md steps 2-6 extraction"
        ),
        "instrument": (
            "dislocation_lambda_census.py replay transplant (constants imported); "
            "additive outputs only — forward returns, regime dominant, side volumes, L5/L6"
        ),
        "grid": "expanded 20-session (AMENDMENT A-1); OLN x 10 original evidence-only",
        "cells": cells,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {args.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
