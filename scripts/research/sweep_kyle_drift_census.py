#!/usr/bin/env python3
"""Task 9-A-H10 Phase A — park-rule census instrument for
``sig_sweep_kyle_drift_h900_v1``.

Implements EXACTLY the frozen protocol step-1 predicate
(``docs/research/sig_sweep_kyle_drift_h900_v1_validation_protocol.md`` §1,
FROZEN 2026-07-15) — **no forward returns, no IC, no signal evaluation**.
The only return-like quantity is unconditional session σ₉₀₀ (Bessel-
corrected std of non-overlapping 900 s mid log-returns on the 09:30-
anchored RTH grid, bps), which conditions on nothing signal-related.

Episode = h=900 boundary satisfying §1.1 arms 1–6 (session window,
required-warm, SFI decile, breakout gate, vol-z backstop, sign
agreement). Primary count IS the filter-clean §1.1 predicate
(contamination-excluded multiplier = 1.0; JC-1 no-double-exclusion).

ISO-warm (JC-10): per (symbol, session) share of in-window boundaries
with ``sweep_flow_imbalance.warm == True``. Warm-drop: warm fraction
< 0.5 on > 2 sessions ⇒ symbol leaves D.

JC-1 REPORTS (diagnostic, never binding): residual non-A / non-id-14
co-travel share in the trailing 900 s at eligible boundaries; share
> 1 % ⇒ ``sensor_bug_investigation_trigger`` flag. Class-B intensity
(2.0× count-basis) reported alongside for Lei adjudication.

Integrity pin: on cells overlapping a prior census artifact (H8
expanded), cross-checkable quantities ``n_events`` / ``n_quotes`` /
``n_trades`` must reproduce (same RTH filter + cache load).

Determinism: PYTHONHASHSEED=0; no RNG; no wall-clock reads; events
sorted by (timestamp_ns, sequence); fresh sensor/regime state per cell.
**This module is the instrument — do not execute against the grid from
Phase A** (N = 11 must survive unchanged).

Usage
-----
    PYTHONHASHSEED=0 uv run python scripts/research/sweep_kyle_drift_census.py \\
        [--cache-dir ~/.feelies/cache] [--json out.json] \\
        [--integrity-pin docs/research/artifacts/dislocation_lambda_census_expanded_2026-07-13.json]
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
from typing import Any, Sequence
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
from feelies.features.impl.horizon_windowed import HorizonWindowedFeature  # noqa: E402
from feelies.features.impl.sensor_passthrough import SensorPassthroughFeature  # noqa: E402
from feelies.sensors.horizon_scheduler import HorizonScheduler  # noqa: E402
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor  # noqa: E402
from feelies.sensors.impl.sweep_flow_imbalance import (  # noqa: E402
    DEFAULT_DROP_CORRECTION_RECORDS,
    SweepFlowImbalanceSensor,
    is_class_a_intersect_id14,
)
from feelies.sensors.registry import SensorRegistry  # noqa: E402
from feelies.sensors.spec import SensorSpec  # noqa: E402
from feelies.services.regime_engine import get_regime_engine  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_HORIZON = 900
_TICK = 0.01
_SFI_WINDOW_NS = 900 * _NS

# ── Frozen evidence set (protocol preamble / 03c) ────────────────────────

GRID_SYMBOLS = ("APP", "RMBS")
EVIDENCE_ONLY_SYMBOLS = ("OLN",)  # §2.4 tick-artifact inputs; never in D
SYMBOLS = GRID_SYMBOLS + EVIDENCE_ONLY_SYMBOLS

DATES_ELEVATED_A = ("2025-11-25", "2025-12-04")
DATES_CALM = ("2025-12-22", "2026-01-05", "2026-01-15", "2026-01-26", "2026-01-27")
DATES_ELEVATED_B = ("2026-04-01", "2026-04-10", "2026-04-22")
DATES = DATES_ELEVATED_A + DATES_CALM + DATES_ELEVATED_B

DATES_ELEVATED_A_EXP = ("2025-12-01", "2025-12-02")
DATES_CALM_EXP = ("2025-12-26", "2025-12-30", "2026-01-12", "2026-01-20", "2026-01-22")
DATES_ELEVATED_B_EXP = ("2026-04-02", "2026-04-07", "2026-04-16")
DATES_EXPANSION = DATES_ELEVATED_A_EXP + DATES_CALM_EXP + DATES_ELEVATED_B_EXP
DATES_ALL = DATES + DATES_EXPANSION

STRATUM = (
    {d: "elevated_A" for d in DATES_ELEVATED_A + DATES_ELEVATED_A_EXP}
    | {d: "calm" for d in DATES_CALM + DATES_CALM_EXP}
    | {d: "elevated_B" for d in DATES_ELEVATED_B + DATES_ELEVATED_B_EXP}
)

# ── Frozen H10 entry constants (protocol §1.1) ───────────────────────────

SFI_PCTL_HI = 0.90
SFI_PCTL_LO = 0.10
P_VOL_BREAKOUT_MAX = 0.7
RV_Z_MAX = 3.0
ENTRY_WARM_IDS = (
    "sweep_flow_imbalance",
    "sweep_flow_imbalance_percentile",
    "realized_vol_30s_zscore",
)
NO_ENTRY_FIRST_SECONDS = 300
SESSION_CUTOFF_ET = (15, 50)

KAPPA_FROZEN = 0.158
FLOOR_LONG_BPS = {"APP": 4.68, "RMBS": 5.51}
FLOOR_SHORT_BPS = {"APP": 5.82, "RMBS": 6.60}
POWER_FLOOR = 100
WARM_DROP_FRACTION = 0.5
WARM_DROP_SESSION_MAX = 2
RESIDUAL_BUG_SHARE = 0.01  # JC-1 >1% investigation trigger
INTENSITY_RATIO = 2.0  # Class-B intensity REPORT (H8 JC-1 precedent)

CLASS_B_CONDITIONS = frozenset({2, 7, 8, 9, 10, 13, 15, 16, 17, 22, 29, 32, 35, 52, 53})
CORRECTION_RECORDS = DEFAULT_DROP_CORRECTION_RECORDS

SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="sweep_flow_imbalance",
        sensor_version="1.0.0",
        cls=SweepFlowImbalanceSensor,
        params={
            "window_seconds": 900,
            "min_eligible_prints": 20,
            "max_gap_seconds": 60,
            "drop_correction_records": (10, 11, 12),
        },
        subscribes_to=(Trade,),
    ),
    SensorSpec(
        sensor_id="realized_vol_30s",
        sensor_version="1.3.0",
        cls=RealizedVol30sSensor,
        params={"window_seconds": 30, "warm_after": 16},
        subscribes_to=(NBBOQuote,),
    ),
)

REGIME_CALIBRATION_MAX_QUOTES = 100_000


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


def _sfi_features() -> list[Any]:
    """Phase-A local wiring (bootstrap factories land in Phase B)."""
    h = _HORIZON
    return [
        SensorPassthroughFeature("sweep_flow_imbalance", h),
        HorizonWindowedFeature(
            "sweep_flow_imbalance",
            h,
            reducer="percentile",
            feature_id="sweep_flow_imbalance_percentile",
        ),
        *_horizon_features_for("realized_vol_30s", h),
    ]


def trade_fails_sfi_filter(t: Trade) -> bool:
    """True if the print would NOT enter SFI state (residual / Class-B path)."""
    if t.correction is not None and t.correction in CORRECTION_RECORDS:
        return True
    return not is_class_a_intersect_id14(t.conditions)


def is_entry_eligible(
    *,
    sfi: float | None,
    pctl: float | None,
    rvz: float | None,
    p_breakout: float | None,
) -> tuple[bool, str | None]:
    """§1.1 arms 3–6 (warm/session handled by caller). Returns (ok, side)."""
    if sfi is None or pctl is None or rvz is None or p_breakout is None:
        return False, None
    if p_breakout >= P_VOL_BREAKOUT_MAX or rvz > RV_Z_MAX:
        return False, None
    if pctl >= SFI_PCTL_HI:
        if sfi <= 0.0:
            return False, None
        return True, "LONG"
    if pctl <= SFI_PCTL_LO:
        if sfi >= 0.0:
            return False, None
        return True, "SHORT"
    return False, None


def apply_warm_drop_rule(
    per_symbol_session_warm: dict[str, list[float]],
    *,
    threshold: float = WARM_DROP_FRACTION,
    max_bad: int = WARM_DROP_SESSION_MAX,
) -> set[str]:
    """Symbols with warm fraction < threshold on > max_bad sessions."""
    dropped: set[str] = set()
    for sym, fracs in per_symbol_session_warm.items():
        n_bad = sum(1 for f in fracs if f < threshold)
        if n_bad > max_bad:
            dropped.add(sym)
    return dropped


def integrity_pin_check(
    cells: Sequence[dict[str, Any]],
    prior_cells: Sequence[dict[str, Any]],
    *,
    fields: tuple[str, ...] = ("n_events", "n_quotes", "n_trades"),
) -> list[str]:
    """Return mismatch messages for overlapping (symbol, date) cells."""
    prior = {(c["symbol"], c["date"]): c for c in prior_cells}
    mismatches: list[str] = []
    for c in cells:
        key = (c["symbol"], c["date"])
        if key not in prior:
            continue
        p = prior[key]
        for f in fields:
            if c.get(f) != p.get(f):
                mismatches.append(f"{key[0]}/{key[1]} {f}: census={c.get(f)} prior={p.get(f)}")
    return mismatches


@dataclass
class CellResult:
    symbol: str
    date: str
    stratum: str
    n_events: int
    n_quotes: int
    n_trades: int
    n_boundaries: int
    n_in_window: int
    n_warm_eligible: int
    warm_fraction: dict[str, float] = field(default_factory=dict)
    sfi_warm_fraction_in_window: float | None = None  # JC-10 ISO-warm
    sigma900_bps: float | None = None
    sigma900_n_returns: int = 0
    viable_long: bool | None = None
    viable_short: bool | None = None
    # Primary = §1.1 filter-clean episodes (JC-1):
    episodes: int = 0
    episodes_long: int = 0
    episodes_short: int = 0
    # JC-1 REPORTS:
    residual_non_a_share_mean: float | None = None
    residual_bug_flag: bool = False
    class_b_intensity_excluded: int = 0  # diagnostic only
    tape_prints: int = 0
    tape_flagged_class_b: int = 0
    gate_on: int = 0
    gate_off: int = 0
    spread_ticks_eligible: list[int] = field(default_factory=list)
    spread_ticks_warm: list[int] = field(default_factory=list)


def run_cell_from_events(
    events: Sequence[NBBOQuote | Trade],
    symbol: str,
    date: str,
) -> CellResult | None:
    """Replay a pre-loaded RTH event list through the §1.1 census path.

    Used by the cache-backed ``run_cell`` and by the synthetic-fixture
    golden (hand-computable episode / warm / filter pin).  Callers must
    supply events already sorted and RTH-filtered, or pass raw lists —
    this function re-sorts and re-filters defensively.
    """
    events = [
        ev
        for ev in sorted(events, key=lambda e: (e.timestamp_ns, e.sequence))
        if _in_rth(ev.exchange_timestamp_ns)
    ]
    if not events:
        return None
    n_quotes = sum(1 for e in events if isinstance(e, NBBOQuote))
    session_open = rth_open_ns(events[0].timestamp_ns)

    feats = _sfi_features()
    fids = {f.feature_id for f in feats}
    assert set(ENTRY_WARM_IDS) <= fids, f"required h={_HORIZON} features missing: {sorted(fids)}"

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
        session_id=f"H10CENSUS_{symbol}_{date}",
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

    trade_ts: list[int] = []
    trade_fail_filter: list[bool] = []
    trade_class_b: list[bool] = []
    for t in events:
        if not isinstance(t, Trade):
            continue
        trade_ts.append(t.timestamp_ns)
        trade_fail_filter.append(trade_fails_sfi_filter(t))
        trade_class_b.append(
            bool(CLASS_B_CONDITIONS.intersection(t.conditions))
            or (t.correction is not None and t.correction in CORRECTION_RECORDS)
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

    grid_mids: list[float | None] = []
    for k in range(0, (6 * 3600 + 30 * 60) // _HORIZON + 1):
        t = session_open + k * _HORIZON * _NS
        i = bisect_right(quote_ts, t) - 1
        grid_mids.append(quote_mid[i] if i >= 0 else None)
    rets = [
        math.log(b2 / a2)
        for a2, b2 in zip(grid_mids, grid_mids[1:])
        if a2 is not None and b2 is not None and a2 > 0 and b2 > 0
    ]
    sigma900 = statistics.stdev(rets) * 1e4 if len(rets) >= 2 else None

    res = CellResult(
        symbol=symbol,
        date=date,
        stratum=STRATUM[date],
        n_events=len(events),
        n_quotes=n_quotes,
        n_trades=len(trade_ts),
        n_boundaries=len(boundary_rows),
        n_in_window=0,
        n_warm_eligible=0,
        sigma900_bps=sigma900,
        sigma900_n_returns=len(rets),
        tape_prints=len(trade_ts),
        tape_flagged_class_b=sum(trade_class_b),
    )
    is_grid = symbol in GRID_SYMBOLS
    if is_grid and sigma900 is not None:
        res.viable_long = sigma900 >= FLOOR_LONG_BPS[symbol] / KAPPA_FROZEN
        res.viable_short = sigma900 >= FLOOR_SHORT_BPS[symbol] / KAPPA_FROZEN

    tape_b_base = res.tape_flagged_class_b / res.tape_prints if res.tape_prints else 0.0
    warm_counts = {fid: 0 for fid in ENTRY_WARM_IDS}
    sfi_warm_in_window = 0
    residual_shares: list[float] = []
    cutoff_secs = SESSION_CUTOFF_ET[0] * 3600 + SESSION_CUTOFF_ET[1] * 60

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
        if warm.get("sweep_flow_imbalance", False):
            sfi_warm_in_window += 1

        qi = bisect_right(quote_ts, asof_ns) - 1
        spread_ticks = round(quote_spread[qi] / _TICK) if qi >= 0 else None

        all_warm = all(warm.get(fid, False) and not stale.get(fid, True) for fid in ENTRY_WARM_IDS)
        if not all_warm:
            if is_grid:
                res.gate_off += 1
            continue
        res.n_warm_eligible += 1
        if spread_ticks is not None:
            res.spread_ticks_warm.append(spread_ticks)

        if not is_grid:
            continue  # OLN: evidence-only — no episode predicate

        sfi = values.get("sweep_flow_imbalance")
        pctl = values.get("sweep_flow_imbalance_percentile")
        rvz = values.get("realized_vol_30s_zscore")
        ok, side = is_entry_eligible(sfi=sfi, pctl=pctl, rvz=rvz, p_breakout=p_breakout)
        if not ok:
            res.gate_off += 1
            continue

        res.gate_on += 1
        res.episodes += 1
        if side == "LONG":
            res.episodes_long += 1
        else:
            res.episodes_short += 1
        if spread_ticks is not None:
            res.spread_ticks_eligible.append(spread_ticks)

        lo = bisect_left(trade_ts, asof_ns - _SFI_WINDOW_NS + 1)
        hi = bisect_right(trade_ts, asof_ns)
        n_win = hi - lo
        n_fail = sum(trade_fail_filter[lo:hi])
        share = n_fail / n_win if n_win else 0.0
        residual_shares.append(share)

        n_b = sum(trade_class_b[lo:hi])
        b_share = n_b / n_win if n_win else 0.0
        if n_b > 0 and b_share >= INTENSITY_RATIO * tape_b_base:
            res.class_b_intensity_excluded += 1

    nb = max(res.n_boundaries, 1)
    res.warm_fraction = {fid: warm_counts[fid] / nb for fid in ENTRY_WARM_IDS}
    res.sfi_warm_fraction_in_window = (
        sfi_warm_in_window / res.n_in_window if res.n_in_window else None
    )
    if residual_shares:
        res.residual_non_a_share_mean = sum(residual_shares) / len(residual_shares)
        res.residual_bug_flag = any(s > RESIDUAL_BUG_SHARE for s in residual_shares)
    return res


def run_cell(cache: DiskEventCache, symbol: str, date: str) -> CellResult | None:
    events = cache.load(symbol, date)
    if not events:
        return None
    return run_cell_from_events(events, symbol, date)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path.home() / ".feelies" / "cache")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument(
        "--integrity-pin",
        type=Path,
        default=None,
        help="Prior census JSON; overlapping cells must match n_events/n_quotes/n_trades",
    )
    ap.add_argument(
        "--preamble-only",
        action="store_true",
        help="Restrict to the 10 preamble dates (OLN evidence set); default = full 20",
    )
    args = ap.parse_args(argv)

    dates = DATES if args.preamble_only else DATES_ALL
    cache = DiskEventCache(args.cache_dir)
    cells: list[CellResult] = []
    for sym in SYMBOLS:
        use_dates = dates if sym in GRID_SYMBOLS else DATES  # OLN: preamble only
        for d in use_dates:
            cell = run_cell(cache, sym, d)
            if cell is not None:
                cells.append(cell)

    # Warm-drop + deployable set D
    warm_by_sym: dict[str, list[float]] = {s: [] for s in GRID_SYMBOLS}
    for c in cells:
        if c.symbol in GRID_SYMBOLS and c.sfi_warm_fraction_in_window is not None:
            warm_by_sym[c.symbol].append(c.sfi_warm_fraction_in_window)
    dropped = apply_warm_drop_rule(warm_by_sym)

    per_symbol: dict[str, Any] = {}
    for sym in GRID_SYMBOLS:
        sym_cells = [c for c in cells if c.symbol == sym]
        eps_all = sum(c.episodes for c in sym_cells)
        eps_viable = sum(c.episodes for c in sym_cells if c.viable_long)
        eps_viable_long = sum(c.episodes_long for c in sym_cells if c.viable_long)
        edge_empty = all((c.episodes if c.viable_long else 0) == 0 for c in sym_cells)
        per_symbol[sym] = {
            "episodes_all": eps_all,
            "episodes_viable_region": eps_viable,
            "episodes_viable_long_only": eps_viable_long,
            "edge_region_empty": edge_empty,
            "warm_drop": sym in dropped,
            "sfi_warm_fractions": warm_by_sym[sym],
            "residual_bug_any": any(c.residual_bug_flag for c in sym_cells),
        }

    deployable = [
        s
        for s in GRID_SYMBOLS
        if not per_symbol[s]["edge_region_empty"] and not per_symbol[s]["warm_drop"]
    ]
    pooled = sum(per_symbol[s]["episodes_viable_region"] for s in deployable)
    emptiness = all(per_symbol[s]["edge_region_empty"] for s in GRID_SYMBOLS)
    park_power = pooled < POWER_FLOOR
    if emptiness:
        verdict = "PARKED_EDGE_EMPTINESS"
    elif park_power:
        verdict = "PARKED_POWER"
    else:
        verdict = "PROCEED_CENSUS"

    integrity_mismatches: list[str] = []
    if args.integrity_pin is not None:
        prior = json.loads(args.integrity_pin.read_text(encoding="utf-8"))
        integrity_mismatches = integrity_pin_check(
            [asdict(c) for c in cells], prior.get("cells", [])
        )
        if integrity_mismatches:
            print("INTEGRITY PIN FAILED:", file=sys.stderr)
            for m in integrity_mismatches:
                print(f"  {m}", file=sys.stderr)
            return 2

    out = {
        "protocol": "sig_sweep_kyle_drift_h900_v1_validation_protocol.md step 1 (frozen)",
        "instrument": "sweep_kyle_drift_census.py (Phase-A; §1.1 predicate exact)",
        "run_parameters": {
            "kappa": KAPPA_FROZEN,
            "power_floor": POWER_FLOOR,
            "sfi_pctl_hi": SFI_PCTL_HI,
            "sfi_pctl_lo": SFI_PCTL_LO,
            "horizon": _HORIZON,
            "preamble_only": bool(args.preamble_only),
            "n_ledger_at_instrument_build": 11,
            "outcome_contact": False,
        },
        "cells": [asdict(c) for c in cells],
        "per_symbol": per_symbol,
        "park_conditions": {
            "edge_region_emptiness": emptiness,
            "power_floor_failed": park_power,
            "pooled_viable_episodes": pooled,
            "deployable_set_D": deployable,
            "warm_dropped": sorted(dropped),
        },
        "jc1_reports": {
            "residual_bug_share_threshold": RESIDUAL_BUG_SHARE,
            "any_residual_bug_flag": any(c.residual_bug_flag for c in cells),
            "note": "diagnostic only — never park / never power deflator",
        },
        "integrity_pin": {
            "path": str(args.integrity_pin) if args.integrity_pin else None,
            "mismatches": integrity_mismatches,
            "ok": not integrity_mismatches,
        },
        "verdict": verdict,
    }

    text = json.dumps(out, indent=2, sort_keys=True)
    if args.json is not None:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(
        f"# verdict={verdict} pooled_viable={pooled} D={deployable} "
        f"warm_dropped={sorted(dropped)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
