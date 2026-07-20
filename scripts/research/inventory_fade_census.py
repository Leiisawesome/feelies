#!/usr/bin/env python3
"""Build the deterministic census for ``sig_inventory_fade_v1``.

Each symbol-session cell reports eligible episodes, warm coverage,
contamination, 120-second session volatility, viability, and regime-by-stratum
counts. Events replay through production sensors and aggregation with causal
regime calibration. The census computes no forward returns, IC, or signals.

Usage
-----
    PYTHONHASHSEED=0 uv run python scripts/research/inventory_fade_census.py \
        [--cache-dir ~/.feelies/cache] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
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
from feelies.sensors.impl.inventory_pressure import InventoryPressureSensor  # noqa: E402
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor  # noqa: E402
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor  # noqa: E402
from feelies.sensors.registry import SensorRegistry  # noqa: E402
from feelies.sensors.spec import SensorSpec  # noqa: E402
from feelies.services.regime_engine import get_regime_engine  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_HORIZON = 120

# Fixed evidence set.

SYMBOLS = ("APP", "RMBS", "OLN", "ENSG", "DIOD", "PCTY", "MLI", "CROX")
DATES_ELEVATED_A = ("2025-11-25", "2025-12-04")
DATES_CALM = ("2025-12-22", "2026-01-05", "2026-01-15", "2026-01-26", "2026-01-27")
DATES_ELEVATED_B = ("2026-04-01", "2026-04-10", "2026-04-22")
DATES = DATES_ELEVATED_A + DATES_CALM + DATES_ELEVATED_B

STRATUM = (
    {d: "elevated_A" for d in DATES_ELEVATED_A}
    | {d: "calm" for d in DATES_CALM}
    | {d: "elevated_B" for d in DATES_ELEVATED_B}
)

# Fixed viable-region arithmetic.
# floor = 2.25 x (2.0 + fee_s); fee_s = $0.35 on an 80-share fill at the
# median RTH bid, in bps of notional; sigma_min = floor / 0.16.
# Kappa is fixed at 0.16. OLN has no floor and never enters D.

KAPPA = 0.16
MEDIAN_BID = {
    "APP": 615.05,
    "ENSG": 182.94,
    "PCTY": 140.80,
    "MLI": 130.62,
    "RMBS": 105.36,
    "CROX": 83.28,
    "DIOD": 57.50,
}


def fee_bps(symbol: str) -> float:
    return 0.35 / (80.0 * MEDIAN_BID[symbol]) * 1e4


def stressed_floor_bps(symbol: str) -> float:
    return 2.25 * (2.0 + fee_bps(symbol))


def sigma120_min_bps(symbol: str) -> float:
    return stressed_floor_bps(symbol) / KAPPA


# ── Frozen §1.2 gate constants ───────────────────────────────────────────

PRESSURE_GATE = 0.5
SPREAD_Z_MAX = 1.0
P_NORMAL_MIN = 0.6
ENTRY_WARM_IDS = ("inventory_pressure", "spread_z_30d", "realized_vol_30s_zscore")
NO_ENTRY_FIRST_SECONDS = 300
SESSION_CUTOFF_ET = (15, 50)  # boundary time <= 15:50:00 ET

# ── §1.5 contamination sets (03b §3.3 Class B / §4.4 netting) ────────────

CLASS_B_CONDITIONS = frozenset({2, 7, 8, 9, 10, 13, 15, 16, 17, 22, 29, 32, 35, 52, 53})
CORRECTION_RECORDS = frozenset({10, 11, 12})
CONTAM_WINDOW_NS = 60 * _NS  # the inventory_pressure trailing sensor window

# ── Reference sensor specs (platform.yaml, verbatim params) ──────────────

SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="inventory_pressure",
        sensor_version="1.0.0",
        cls=InventoryPressureSensor,
        params={"window_seconds": 60, "min_trades": 20},
        subscribes_to=(Trade,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        params={"window": 6000, "min_std": 1e-9, "max_gap_seconds": 300},
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

# ── RTH filter (mirrors harness/backtest_prep._in_rth) ───────────────────


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


# ── Cell result schema ───────────────────────────────────────────────────


@dataclass
class CellResult:
    symbol: str
    date: str
    stratum: str
    n_events: int
    n_quotes: int
    n_trades: int
    n_boundaries: int  # emitted h=120 snapshots (RTH)
    n_boundaries_in_session_window: int
    warm_fraction: dict[str, float] = field(default_factory=dict)
    sigma120_bps: float | None = None
    sigma120_n_returns: int = 0
    viable: bool | None = None  # None for OLN (no floor)
    # eligible episodes (frozen §1.2), contamination-excluded primary:
    eligible_primary: int = 0
    eligible_primary_long: int = 0
    eligible_primary_short: int = 0
    # including contamination-flagged boundaries (reported both ways):
    eligible_incl_flagged: int = 0
    eligible_flagged: int = 0
    # gate-state x stratum inputs (boundaries in session window):
    gate_on: int = 0
    gate_off: int = 0


# ── Replay of one (symbol, session) cell ─────────────────────────────────


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
    n_trades = len(events) - n_quotes

    session_open = rth_open_ns(events[0].timestamp_ns)

    # Production h=120 feature wiring (bootstrap factory; locks 6a3ac12).
    feats = [
        f
        for sid in ("inventory_pressure", "spread_z_30d", "realized_vol_30s")
        for f in _horizon_features_for(sid, _HORIZON)
    ]
    ip_ids = [f.feature_id for f in feats if "inventory_pressure" in f.input_sensor_ids]
    assert "inventory_pressure" in ip_ids, (
        "inventory_pressure passthrough NOT wired at h=120 — commit 6a3ac12 "
        "wiring pre-step missing; census precondition P0-1 violated"
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
        session_id=f"CENSUS_{symbol}_{date}",
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

    # Regime engine: reference defaults, per-session causal-prefix
    # calibration (mirrors orchestrator._calibrate_regime_engine).
    engine = get_regime_engine("hmm_3state_fractional")
    cal_quotes = [e for e in events if isinstance(e, NBBOQuote)][:REGIME_CALIBRATION_MAX_QUOTES]
    engine.calibrate(cal_quotes)
    names = tuple(engine.state_names)
    idx_normal = names.index("normal")

    # Contaminated-print timestamps (Class-B conditions or correction
    # follow-on records), for the trailing-60s boundary flag.
    contam_ts = sorted(
        t.timestamp_ns
        for t in events
        if isinstance(t, Trade)
        and (
            bool(CLASS_B_CONDITIONS.intersection(t.conditions))
            or (t.correction is not None and t.correction in CORRECTION_RECORDS)
        )
    )

    # Mid series (quote timestamps) for sigma_120.
    mid_ts: list[int] = []
    mids: list[float] = []

    # Boundary records: (asof_ns, values, warm, stale, p_normal)
    boundary_rows: list[tuple[int, dict, dict, dict, float | None]] = []

    n_seen = 0
    for ev in events:
        if isinstance(ev, NBBOQuote):
            engine.posterior(ev)  # M2: regime updates before the tick pipeline
            b, a = float(ev.bid), float(ev.ask)
            if b > 0.0 and a > 0.0:
                mid_ts.append(ev.timestamp_ns)
                mids.append((b + a) / 2.0)
        bus.publish(ev)
        for tick in scheduler.on_event(ev):
            bus.publish(tick)
        # Latch the boundary-time posterior for any snapshot just emitted.
        while n_seen < len(captured):
            s = captured[n_seen]
            n_seen += 1
            if s.horizon_seconds != _HORIZON:
                continue
            post = engine.current_state(symbol)
            p_normal = post[idx_normal] if post is not None else None
            boundary_rows.append(
                (s.boundary_ts_ns, dict(s.values), dict(s.warm), dict(s.stale), p_normal)
            )

    # sigma_120: std of non-overlapping 120 s mid log-returns over RTH
    # (bps).  Grid anchored at the 09:30 ET open; mid sampled last-at-or-
    # before each grid point; sample std (Bessel).
    grid_mids: list[float | None] = []
    for k in range(0, (6 * 3600 + 30 * 60) // _HORIZON + 1):
        t = session_open + k * _HORIZON * _NS
        i = bisect_right(mid_ts, t) - 1
        grid_mids.append(mids[i] if i >= 0 else None)
    rets = [
        math.log(b / a)
        for a, b in zip(grid_mids, grid_mids[1:])
        if a is not None and b is not None and a > 0 and b > 0
    ]
    sigma120 = statistics.stdev(rets) * 1e4 if len(rets) >= 2 else None

    res = CellResult(
        symbol=symbol,
        date=date,
        stratum=STRATUM[date],
        n_events=len(events),
        n_quotes=n_quotes,
        n_trades=n_trades,
        n_boundaries=len(boundary_rows),
        n_boundaries_in_session_window=0,
        sigma120_bps=sigma120,
        sigma120_n_returns=len(rets),
    )
    if symbol in MEDIAN_BID and sigma120 is not None:
        res.viable = sigma120 >= sigma120_min_bps(symbol)

    warm_counts = {fid: 0 for fid in ENTRY_WARM_IDS}
    cutoff_secs = SESSION_CUTOFF_ET[0] * 3600 + SESSION_CUTOFF_ET[1] * 60
    for asof_ns, values, warm, stale, p_normal in boundary_rows:
        for fid in ENTRY_WARM_IDS:
            if warm.get(fid, False):
                warm_counts[fid] += 1
        # Session-discipline window (frozen §1.2 condition 5), on the
        # nominal boundary time.
        offset_s = (asof_ns - session_open) // _NS
        dt_et = datetime.fromtimestamp(asof_ns / 1e9, tz=_TZ_ET)
        et_secs = dt_et.hour * 3600 + dt_et.minute * 60 + dt_et.second
        in_window = offset_s >= NO_ENTRY_FIRST_SECONDS and et_secs <= cutoff_secs
        if not in_window:
            continue
        res.n_boundaries_in_session_window += 1

        sz = values.get("spread_z_30d")
        sz_ok_warm = warm.get("spread_z_30d", False) and not stale.get("spread_z_30d", True)
        gate_on = (
            sz_ok_warm
            and p_normal is not None
            and p_normal > P_NORMAL_MIN
            and sz is not None
            and sz <= SPREAD_Z_MAX
        )
        if gate_on:
            res.gate_on += 1
        else:
            res.gate_off += 1

        # Frozen §1.2 eligibility (all five conditions).
        all_warm = all(warm.get(fid, False) and not stale.get(fid, True) for fid in ENTRY_WARM_IDS)
        if not all_warm:
            continue
        p = values.get("inventory_pressure")
        if p is None or sz is None or p_normal is None:
            continue
        if abs(p) < PRESSURE_GATE or sz > SPREAD_Z_MAX or p_normal <= P_NORMAL_MIN:
            continue

        # §1.5 contamination flag: any contaminated print in the trailing
        # 60 s window (asof-60s, asof].
        lo = bisect_left(contam_ts, asof_ns - CONTAM_WINDOW_NS + 1)
        hi = bisect_right(contam_ts, asof_ns)
        flagged = hi > lo

        res.eligible_incl_flagged += 1
        if flagged:
            res.eligible_flagged += 1
        else:
            res.eligible_primary += 1
            if p >= PRESSURE_GATE:
                res.eligible_primary_long += 1
            else:
                res.eligible_primary_short += 1

    nb = max(res.n_boundaries, 1)
    res.warm_fraction = {fid: warm_counts[fid] / nb for fid in ENTRY_WARM_IDS}
    return res


# ── Driver ───────────────────────────────────────────────────────────────


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

    # Per-symbol viable-region roll-up (§1.4 park conditions).
    per_symbol: dict[str, dict] = {}
    for symbol in SYMBOLS:
        sym_cells = [c for c in cells if c.symbol == symbol]
        floored = symbol in MEDIAN_BID
        viable_cells = [c for c in sym_cells if c.viable] if floored else []
        viable_primary = sum(c.eligible_primary for c in viable_cells)
        per_symbol[symbol] = {
            "fee_bps": round(fee_bps(symbol), 4) if floored else None,
            "stressed_floor_bps": round(stressed_floor_bps(symbol), 4) if floored else None,
            "sigma120_min_bps": round(sigma120_min_bps(symbol), 4) if floored else None,
            "n_cells": len(sym_cells),
            "n_viable_cells": len(viable_cells),
            "viable_dates": sorted(c.date for c in viable_cells),
            "viable_region_eligible_primary": viable_primary,
            "viable_region_eligible_incl_flagged": sum(
                c.eligible_incl_flagged for c in viable_cells
            ),
            "eligible_primary_all_cells": sum(c.eligible_primary for c in sym_cells),
            "benign_on_elevated_A_primary": sum(
                c.eligible_primary for c in sym_cells if c.stratum == "elevated_A"
            ),
            "benign_on_elevated_B_primary": sum(
                c.eligible_primary for c in sym_cells if c.stratum == "elevated_B"
            ),
            "calm_primary": sum(c.eligible_primary for c in sym_cells if c.stratum == "calm"),
            "deployable_candidate": bool(floored and viable_primary >= 100),
        }

    deployable = [s for s in SYMBOLS if s in MEDIAN_BID and per_symbol[s]["deployable_candidate"]]
    emptiness = all(per_symbol[s]["viable_region_eligible_primary"] == 0 for s in MEDIAN_BID)
    park_on_emptiness = emptiness
    park_on_power = not deployable

    verdict = "PARK" if (park_on_emptiness or park_on_power) else "PROCEED"

    out = {
        "protocol": "sig_inventory_fade_v1_validation_protocol.md step 1 (frozen)",
        "kappa_frozen": KAPPA,
        "cells": [asdict(c) for c in cells],
        "per_symbol": per_symbol,
        "park_conditions": {
            "edge_region_emptiness": park_on_emptiness,
            "power_floor_failed_all_symbols": park_on_power,
            "deployable_set_D": deployable,
        },
        "verdict": verdict,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"wrote {args.json}", file=sys.stderr)

    # Human-readable table.
    print("\n== Census cells ==")
    hdr = (
        f"{'sym':<5}{'date':<12}{'strat':<11}{'bnd':>5}{'win':>5}"
        f"{'warm_ip':>8}{'warm_sz':>8}{'warm_rv':>8}"
        f"{'sig120':>8}{'viab':>6}{'elig':>6}{'long':>6}{'short':>6}"
        f"{'flag':>6}{'gON':>5}{'gOFF':>5}"
    )
    print(hdr)
    print("-" * len(hdr))
    for c in cells:
        s = "n/a" if c.sigma120_bps is None else f"{c.sigma120_bps:.1f}"
        v = "-" if c.viable is None else ("YES" if c.viable else "no")
        print(
            f"{c.symbol:<5}{c.date:<12}{c.stratum:<11}{c.n_boundaries:>5}"
            f"{c.n_boundaries_in_session_window:>5}"
            f"{c.warm_fraction.get('inventory_pressure', 0):>8.2f}"
            f"{c.warm_fraction.get('spread_z_30d', 0):>8.2f}"
            f"{c.warm_fraction.get('realized_vol_30s_zscore', 0):>8.2f}"
            f"{s:>8}{v:>6}{c.eligible_primary:>6}{c.eligible_primary_long:>6}"
            f"{c.eligible_primary_short:>6}{c.eligible_flagged:>6}"
            f"{c.gate_on:>5}{c.gate_off:>5}"
        )
    print("\n== Per-symbol roll-up ==")
    for symbol in SYMBOLS:
        print(f"{symbol}: {json.dumps(per_symbol[symbol])}")
    print(f"\nDeployable set D = {deployable}")
    print(f"Park (emptiness) = {park_on_emptiness}; Park (power) = {park_on_power}")
    print(f"VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
