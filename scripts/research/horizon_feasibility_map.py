#!/usr/bin/env python3
"""Build a deterministic horizon-feasibility map over the operative grid.

For each symbol and horizon, the script reports RTH mid-price volatility
quantiles, passive and taker stressed-cost floors, the required capture ratio,
and mechanism-family horizon legality. It computes no forward returns, IC, or
signals. Sorted inputs and fixed rounding make reruns identical.

Usage
-----
    PYTHONHASHSEED=0 uv run python scripts/research/horizon_feasibility_map.py \
        [--cache-dir ~/.feelies/cache] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from bisect import bisect_right
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from feelies.alpha.layer_validator import (  # noqa: E402
    _FAMILY_HALF_LIFE_RANGES_SECONDS,
    _HORIZON_RATIO_CEILING,
    _HORIZON_RATIO_FLOOR,
)
from feelies.core.events import EXIT_ONLY_MECHANISMS, NBBOQuote  # noqa: E402
from feelies.core.session_clock import rth_open_ns  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_RTH_SECONDS = 6 * 3600 + 30 * 60  # 09:30-16:00 ET

# Registered horizons (platform.yaml horizons_seconds; G7 set).
HORIZONS = (30, 120, 300, 900, 1800)

# Evidence dates: ten shared dates plus ten APP/RMBS-only dates.

SYMBOLS = ("APP", "RMBS", "OLN", "ENSG", "DIOD", "PCTY", "MLI", "CROX")
EXPANDED_SYMBOLS = frozenset({"APP", "RMBS"})

DATES_ELEVATED_A = ("2025-11-25", "2025-12-04")
DATES_CALM = ("2025-12-22", "2026-01-05", "2026-01-15", "2026-01-26", "2026-01-27")
DATES_ELEVATED_B = ("2026-04-01", "2026-04-10", "2026-04-22")
DATES = DATES_ELEVATED_A + DATES_CALM + DATES_ELEVATED_B

# Expansion dates.
DATES_ELEVATED_A_EXP = ("2025-12-01", "2025-12-02")
DATES_CALM_EXP = ("2025-12-26", "2025-12-30", "2026-01-12", "2026-01-20", "2026-01-22")
DATES_ELEVATED_B_EXP = ("2026-04-02", "2026-04-07", "2026-04-16")
DATES_EXPANSION = DATES_ELEVATED_A_EXP + DATES_CALM_EXP + DATES_ELEVATED_B_EXP

STRATUM = (
    {d: "elevated_A" for d in DATES_ELEVATED_A + DATES_ELEVATED_A_EXP}
    | {d: "calm" for d in DATES_CALM + DATES_CALM_EXP}
    | {d: "elevated_B" for d in DATES_ELEVATED_B + DATES_ELEVATED_B_EXP}
)


def dates_for(symbol: str) -> tuple[str, ...]:
    """Operative sessions for ``symbol`` (20 for APP/RMBS, else 10)."""
    if symbol in EXPANDED_SYMBOLS:
        return tuple(sorted(DATES + DATES_EXPANSION))
    return DATES

# ── Cost constants (00c pinned profile; spec §4.2 / adjudication D.1-D.2)

FILL_SHARES = 80  # top-of-book reference fill (spec §4.2)
COMMISSION = max(0.0035 * FILL_SHARES, 0.35)  # $0.35 min-commission floor
TAKER_EXCHANGE = 0.003 * FILL_SHARES  # $0.24 (cost_taker_exchange_per_share)
PASSIVE_ADVERSE_BPS = 2.0  # cost_passive_adverse_selection_bps (LEVEL/drain)
IMPACT_THIN_BPS = 1.0  # D.1: within-L1 participation, half-spread < 8 bps
IMPACT_WIDE_BPS = 2.0  # D.1: half-spread >= 8 bps
STRESS = 1.5  # cost_stress_multiplier under --inv12-stress
INV12_MARGIN = 1.5  # Inv-12: edge >= 1.5 x C_ow,stressed
KAPPA_CEILING = 0.30  # H2 spec §4.1 honest-band ceiling (derivation ceiling)

QUANTILES = (0.50, 0.75, 0.90)


def quantile(sorted_vals: list[float], q: float) -> float:
    """Hyndman-Fan type 7 (linear interpolation; numpy default)."""
    pos = (len(sorted_vals) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


# ── RTH filter (mirrors harness/backtest_prep._in_rth; census parity) ────


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


# ── Per-cell replay: mid series -> sigma_H at every horizon ──────────────


def run_cell(cache: DiskEventCache, symbol: str, date: str) -> dict | None:
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
    session_open = rth_open_ns(events[0].timestamp_ns)

    mid_ts: list[int] = []
    mids: list[float] = []
    bids: list[float] = []
    spreads: list[float] = []
    for ev in events:
        if not isinstance(ev, NBBOQuote):
            continue
        b, a = float(ev.bid), float(ev.ask)
        if b > 0.0 and a > 0.0:
            mid_ts.append(ev.timestamp_ns)
            mids.append((b + a) / 2.0)
            bids.append(b)
            spreads.append(a - b)

    if not mids:
        return None

    # sigma_H per horizon: identical estimator to the census, H-general.
    sigma: dict[str, float | None] = {}
    n_returns: dict[str, int] = {}
    for h in HORIZONS:
        grid_mids: list[float | None] = []
        for k in range(0, _RTH_SECONDS // h + 1):
            t = session_open + k * h * _NS
            i = bisect_right(mid_ts, t) - 1
            grid_mids.append(mids[i] if i >= 0 else None)
        rets = [
            math.log(b / a)
            for a, b in zip(grid_mids, grid_mids[1:])
            if a is not None and b is not None and a > 0 and b > 0
        ]
        sigma[str(h)] = round(statistics.stdev(rets) * 1e4, 6) if len(rets) >= 2 else None
        n_returns[str(h)] = len(rets)

    return {
        "symbol": symbol,
        "date": date,
        "stratum": STRATUM[date],
        "n_quotes_two_sided": len(mids),
        "median_bid": round(statistics.median(bids), 6),
        "median_spread": round(statistics.median(spreads), 6),
        "sigma_bps": sigma,
        "n_returns": n_returns,
    }


# ── Cost floors (recomputed fee-in-bps; spec §4.2 / D.1 arithmetic) ──────


def cost_block(median_bid: float, median_spread: float) -> dict:
    notional = FILL_SHARES * median_bid
    fee_passive_bps = COMMISSION / notional * 1e4
    fee_taker_bps = (COMMISSION + TAKER_EXCHANGE) / notional * 1e4
    half_spread_bps = (median_spread / 2.0) / median_bid * 1e4
    impact_bps = IMPACT_THIN_BPS if half_spread_bps < 8.0 else IMPACT_WIDE_BPS

    c_ow_passive = PASSIVE_ADVERSE_BPS + fee_passive_bps
    c_ow_taker = half_spread_bps + impact_bps + fee_taker_bps
    return {
        "median_bid": round(median_bid, 4),
        "median_spread": round(median_spread, 4),
        "half_spread_bps": round(half_spread_bps, 4),
        "impact_bps": impact_bps,
        "fee_passive_bps": round(fee_passive_bps, 4),
        "fee_taker_bps": round(fee_taker_bps, 4),
        "c_ow_passive_bps": round(c_ow_passive, 4),
        "c_ow_taker_bps": round(c_ow_taker, 4),
        "floor_passive_bps": round(INV12_MARGIN * STRESS * c_ow_passive, 4),
        "floor_taker_bps": round(INV12_MARGIN * STRESS * c_ow_taker, 4),
    }


# ── Mechanism-class x horizon legality (G16 envelopes) ───────────────────


def mechanism_horizon_map() -> dict:
    out: dict[str, dict] = {}
    for family, (lo, hi) in sorted(_FAMILY_HALF_LIFE_RANGES_SECONDS.items()):
        h_lo = _HORIZON_RATIO_FLOOR * lo
        h_hi = _HORIZON_RATIO_CEILING * hi
        out[family] = {
            "half_life_envelope_s": [lo, hi],
            "legal_horizon_bounds_s": [h_lo, h_hi],
            "legal_registered_horizons": [h for h in HORIZONS if h_lo <= h <= h_hi],
            "exit_only": family in {m.name for m in EXIT_ONLY_MECHANISMS},
        }
    return out


# ── Driver ───────────────────────────────────────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path.home() / ".feelies" / "cache")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    cache = DiskEventCache(args.cache_dir)
    cells: list[dict] = []
    for symbol in SYMBOLS:
        for date in dates_for(symbol):
            print(f"# {symbol} {date} ...", file=sys.stderr, flush=True)
            cell = run_cell(cache, symbol, date)
            if cell is None:
                print(f"  ! MISSING cache for {symbol}/{date}", file=sys.stderr)
                continue
            cells.append(cell)

    per_symbol: dict[str, dict] = {}
    for symbol in SYMBOLS:
        sym_cells = [c for c in cells if c["symbol"] == symbol]
        # Grid-session median-of-per-session-medians (03c §7 convention).
        med_bid = statistics.median([c["median_bid"] for c in sym_cells])
        med_spread = statistics.median([c["median_spread"] for c in sym_cells])
        costs = cost_block(med_bid, med_spread)

        horizons_out: dict[str, dict] = {}
        for h in HORIZONS:
            vals = sorted(
                c["sigma_bps"][str(h)] for c in sym_cells if c["sigma_bps"][str(h)] is not None
            )
            qs = {f"p{int(q * 100)}": round(quantile(vals, q), 4) for q in QUANTILES}
            entry: dict = {
                "n_sessions": len(vals),
                "sigma_bps": qs,
            }
            for variant in ("passive", "taker"):
                floor = costs[f"floor_{variant}_bps"]
                kreq = {k: round(floor / v, 4) for k, v in qs.items()}
                entry[f"kappa_req_{variant}"] = kreq
                entry[f"feasible_{variant}"] = {k: v <= KAPPA_CEILING for k, v in kreq.items()}
            horizons_out[str(h)] = entry

        per_symbol[symbol] = {
            "n_sessions": len(sym_cells),
            "dates": [c["date"] for c in sorted(sym_cells, key=lambda c: c["date"])],
            "costs": costs,
            "horizons": horizons_out,
        }

    out = {
        "task": (
            "FQ-9 OPERATIVE-grid horizon-feasibility map "
            "(census legality; no forward returns/IC)"
        ),
        "grid": {
            "name": "operative",
            "n_cells": len(cells),
            "expanded_symbols": sorted(EXPANDED_SYMBOLS),
            "dates_original": list(DATES),
            "dates_expansion": list(DATES_EXPANSION),
            "sessions_per_symbol": {s: len(dates_for(s)) for s in SYMBOLS},
        },
        "kappa_ceiling": KAPPA_CEILING,
        "floor_formula": "2.25 x C_ow (= 1.5 Inv-12 margin x 1.5 stress x C_ow)",
        "quantile_method": "Hyndman-Fan type 7 (linear interpolation)",
        "horizons": list(HORIZONS),
        "mechanism_horizon_map": mechanism_horizon_map(),
        "per_symbol": per_symbol,
        "cells": cells,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        # newline="\n" — platform-stable artifact bytes (Windows text-mode
        # write_text would otherwise emit CRLF and diverge from eol=lf blobs).
        args.json.write_text(
            json.dumps(out, indent=2, sort_keys=True),
            encoding="utf-8",
            newline="\n",
        )
        print(f"wrote {args.json}", file=sys.stderr)

    # Human-readable tables.
    print("\n== Cost floors (recomputed fee-in-bps; 2.25 x C_ow) ==")
    hdr = (
        f"{'sym':<6}{'bid':>9}{'sprd':>8}{'hs_bps':>8}{'imp':>5}"
        f"{'feeP':>7}{'feeT':>7}{'CowP':>7}{'CowT':>7}{'flrP':>7}{'flrT':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for symbol in SYMBOLS:
        c = per_symbol[symbol]["costs"]
        print(
            f"{symbol:<6}{c['median_bid']:>9.2f}{c['median_spread']:>8.4f}"
            f"{c['half_spread_bps']:>8.2f}{c['impact_bps']:>5.1f}"
            f"{c['fee_passive_bps']:>7.2f}{c['fee_taker_bps']:>7.2f}"
            f"{c['c_ow_passive_bps']:>7.2f}{c['c_ow_taker_bps']:>7.2f}"
            f"{c['floor_passive_bps']:>7.2f}{c['floor_taker_bps']:>7.2f}"
        )

    print("\n== sigma_H (bps) and kappa_req (P=passive, T=taker floors) ==")
    hdr = (
        f"{'sym':<6}{'H':>5}{'med':>8}{'p75':>8}{'p90':>8}"
        f"{'kP_med':>8}{'kP_p90':>8}{'kT_med':>8}{'kT_p90':>8}{'feasible(k<=0.30)':>20}"
    )
    print(hdr)
    print("-" * len(hdr))
    for symbol in SYMBOLS:
        for h in HORIZONS:
            e = per_symbol[symbol]["horizons"][str(h)]
            s = e["sigma_bps"]
            kp, kt = e["kappa_req_passive"], e["kappa_req_taker"]
            fp, ft = e["feasible_passive"], e["feasible_taker"]
            flags = []
            for name, f in (("P", fp), ("T", ft)):
                best = [k for k in ("p50", "p75", "p90") if f[k]]
                flags.append(f"{name}:{','.join(best) if best else '-'}")
            print(
                f"{symbol:<6}{h:>5}{s['p50']:>8.1f}{s['p75']:>8.1f}{s['p90']:>8.1f}"
                f"{kp['p50']:>8.2f}{kp['p90']:>8.2f}{kt['p50']:>8.2f}{kt['p90']:>8.2f}"
                f"{' '.join(flags):>20}"
            )

    print("\n== Mechanism-class x horizon legality (G16) ==")
    for family, m in out["mechanism_horizon_map"].items():
        tag = " [EXIT-ONLY]" if m["exit_only"] else ""
        print(
            f"{family:<20} hl {m['half_life_envelope_s']} -> legal horizons "
            f"{m['legal_registered_horizons']}{tag}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
