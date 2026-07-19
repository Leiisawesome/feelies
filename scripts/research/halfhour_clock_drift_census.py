#!/usr/bin/env python3
"""Task 9-A-H12 Phase A — park-rule census instrument for
``sig_halfhour_clock_drift_h900_v1``.

Implements EXACTLY the frozen protocol step-1 predicate
(``docs/research/sig_halfhour_clock_drift_h900_v1_validation_protocol.md`` §1,
FROZEN 2026-07-17) — **no forward returns, no IC, no signal evaluation**.
The only return-like quantity is unconditional session σ₉₀₀ (Bessel-
corrected std of non-overlapping 900 s mid log-returns on the 09:30-
anchored RTH grid, bps), which conditions on nothing signal-related.

Episode = h=900 boundary satisfying §1.1 (session window, required-warm,
``W_hh`` clock predicate for in-window primary OR inverted for F2 off-
clock contrast, OFI quintile, breakout gate, vol-z backstop, sign
agreement). Counts both ``episodes_in_window`` (``W_hh=1``) and
``episodes_out_window`` (matched OFI quintile, ``W_hh=0``).

Calendar-warm (JC-10): per (symbol, session) share of in-window
boundaries with ``scheduled_flow_window_active`` warm (sensor warm
propagated via ``TupleComponentFeature``). Warm-drop: warm fraction
< 0.5 on > 2 sessions ⇒ symbol leaves D.

JC-1 REPORTS (diagnostic, never binding): leakage share on primary
in-window eligible boundaries (degenerate/crossed quotes on trailing-
900 s OFI path); ``off_clock_cotravel_rate`` among quintile-OFI
eligible-class boundaries ignoring clock (design ≈ 0.52).

Determinism: PYTHONHASHSEED=0; no RNG; no wall-clock reads; events
sorted by (timestamp_ns, sequence); fresh sensor/regime state per cell.
**This module is the instrument — do not execute against the grid from
Phase A** (N = 12 must survive unchanged).

Usage
-----
    PYTHONHASHSEED=0 uv run python scripts/research/halfhour_clock_drift_census.py \\
        [--cache-dir ~/.feelies/cache] [--json out.json] [--preamble-only]
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
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
from feelies.sensors.horizon_scheduler import HorizonScheduler  # noqa: E402
from feelies.sensors.impl.ofi_raw import OFIRawSensor  # noqa: E402
from feelies.sensors.impl.realized_vol_30s import RealizedVol30sSensor  # noqa: E402
from feelies.sensors.impl.scheduled_flow_window import ScheduledFlowWindowSensor  # noqa: E402
from feelies.sensors.registry import SensorRegistry  # noqa: E402
from feelies.sensors.spec import SensorSpec  # noqa: E402
from feelies.services.regime_engine import get_regime_engine  # noqa: E402
from feelies.storage.disk_event_cache import DiskEventCache  # noqa: E402
from feelies.storage.reference.event_calendar import EventCalendar, load_event_calendar  # noqa: E402
from feelies.storage.reference.paths import EVENT_CALENDAR_DIR  # noqa: E402

_NS = 1_000_000_000
_TZ_ET = ZoneInfo("America/New_York")
_HORIZON = 900
_TICK = 0.01
_OFI_WINDOW_NS = 900 * _NS

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

# ── Frozen H12 entry constants (protocol §1.1) ───────────────────────────

OFI_PCTL_HI = 0.80
OFI_PCTL_LO = 0.20
P_VOL_BREAKOUT_MAX = 0.7
RV_Z_MAX = 3.0
ENTRY_WARM_IDS = (
    "scheduled_flow_window_active",
    "ofi_integrated_percentile",
    "ofi_integrated",
    "realized_vol_30s_zscore",
)
NO_ENTRY_FIRST_SECONDS = 300
SESSION_CUTOFF_ET = (15, 50)

KAPPA_FROZEN = 0.146
FLOOR_LONG_BPS = {"APP": 4.68, "RMBS": 5.51}
FLOOR_SHORT_BPS = {"APP": 5.82, "RMBS": 6.60}
POWER_FLOOR = 100
WARM_DROP_FRACTION = 0.5
WARM_DROP_SESSION_MAX = 2
LEAKAGE_BUG_SHARE = 0.01  # JC-1 >1% investigation trigger

REGIME_CALIBRATION_MAX_QUOTES = 100_000


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


def _hh_features() -> list[Any]:
    """h=900 features from production factories (Phase-A wiring)."""
    h = _HORIZON
    feats: list[Any] = []
    for sid in ("scheduled_flow_window", "ofi_raw", "realized_vol_30s"):
        feats.extend(_horizon_features_for(sid, h))
    return feats


def _sensor_specs(calendar: EventCalendar) -> tuple[SensorSpec, ...]:
    return (
        SensorSpec(
            sensor_id="scheduled_flow_window",
            sensor_version="1.2.0",
            cls=ScheduledFlowWindowSensor,
            params={"calendar": calendar},
            subscribes_to=(NBBOQuote, Trade),
        ),
        SensorSpec(
            sensor_id="ofi_raw",
            sensor_version="1.0.0",
            cls=OFIRawSensor,
            params={"warm_after": 50, "warm_window_seconds": 300},
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


def quote_dropped_by_ofi(bid: float, ask: float) -> bool:
    """True if production ``ofi_raw`` would drop this quote (degenerate/crossed)."""
    return bid <= 0.0 or ask <= 0.0 or bid > ask


def ofi_quintile_side(
    *,
    ofi: float | None,
    pctl: float | None,
    rvz: float | None,
    p_breakout: float | None,
) -> tuple[bool, str | None]:
    """§1.1 arms 4–7 (warm/session/clock handled by caller). Returns (ok, side)."""
    if ofi is None or pctl is None or rvz is None or p_breakout is None:
        return False, None
    if p_breakout >= P_VOL_BREAKOUT_MAX or rvz > RV_Z_MAX:
        return False, None
    if pctl >= OFI_PCTL_HI:
        if ofi <= 0.0:
            return False, None
        return True, "LONG"
    if pctl <= OFI_PCTL_LO:
        if ofi >= 0.0:
            return False, None
        return True, "SHORT"
    return False, None


def is_entry_eligible(
    *,
    ofi: float | None,
    pctl: float | None,
    rvz: float | None,
    p_breakout: float | None,
    w_hh: float | None,
    require_clock: bool,
) -> tuple[bool, str | None]:
    """§1.1 full predicate arms 3–7. ``require_clock=True`` ⇒ ``W_hh≥0.5``."""
    ok, side = ofi_quintile_side(ofi=ofi, pctl=pctl, rvz=rvz, p_breakout=p_breakout)
    if not ok:
        return False, None
    if w_hh is None:
        return False, None
    if require_clock:
        if w_hh < 0.5:
            return False, None
    elif w_hh >= 0.5:
        return False, None
    return True, side


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


def _load_calendar(date_str: str) -> EventCalendar | None:
    path = EVENT_CALENDAR_DIR / f"{date_str}.yaml"
    if not path.is_file():
        return None
    return load_event_calendar(path, expected_session_date=date.fromisoformat(date_str))


def _calendar_missing_cell(
    events: Sequence[NBBOQuote | Trade],
    symbol: str,
    date_str: str,
) -> CellResult:
    n_quotes = sum(1 for e in events if isinstance(e, NBBOQuote))
    n_trades = sum(1 for e in events if isinstance(e, Trade))
    return CellResult(
        symbol=symbol,
        date=date_str,
        stratum=STRATUM[date_str],
        n_events=len(events),
        n_quotes=n_quotes,
        n_trades=n_trades,
        n_boundaries=0,
        n_in_window=0,
        n_warm_eligible=0,
        calendar_warm_fraction_in_window=None,
        calendar_missing_rate=1.0,
        calendar_hash=None,
    )


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
    calendar_warm_fraction_in_window: float | None = None
    calendar_missing_rate: float = 0.0
    calendar_hash: str | None = None
    warm_fraction: dict[str, float] = field(default_factory=dict)
    sigma900_bps: float | None = None
    sigma900_n_returns: int = 0
    viable_long: bool | None = None
    viable_short: bool | None = None
    episodes_in_window: int = 0
    episodes_in_window_long: int = 0
    episodes_in_window_short: int = 0
    episodes_out_window: int = 0
    episodes_out_window_long: int = 0
    episodes_out_window_short: int = 0
    leakage_share_mean: float | None = None
    leakage_bug_flag: bool = False
    off_clock_cotravel_rate: float | None = None
    gate_on: int = 0
    gate_off: int = 0
    spread_ticks_eligible: list[int] = field(default_factory=list)
    spread_ticks_warm: list[int] = field(default_factory=list)


def run_cell_from_events(
    events: Sequence[NBBOQuote | Trade],
    symbol: str,
    date_str: str,
    calendar: EventCalendar | None = None,
) -> CellResult | None:
    """Replay a pre-loaded RTH event list through the §1.1 census path."""
    events = [
        ev
        for ev in sorted(events, key=lambda e: (e.timestamp_ns, e.sequence))
        if _in_rth(ev.exchange_timestamp_ns)
    ]
    if not events:
        return None

    if calendar is None:
        calendar = _load_calendar(date_str)
    if calendar is None:
        return _calendar_missing_cell(events, symbol, date_str)

    calendar_hash = calendar.hash()
    calendar_empty = len(calendar.windows) == 0

    n_quotes = sum(1 for e in events if isinstance(e, NBBOQuote))
    session_open = rth_open_ns(events[0].timestamp_ns)

    feats = _hh_features()
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
    for spec in _sensor_specs(calendar):
        registry.register(spec)
    scheduler = HorizonScheduler(
        horizons=frozenset({_HORIZON}),
        session_id=f"H12CENSUS_{symbol}_{date_str}",
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

    quote_ts: list[int] = []
    quote_mid: list[float] = []
    quote_spread: list[float] = []
    quote_bad: list[bool] = []
    boundary_rows: list[tuple[int, dict, dict, dict, float | None]] = []

    n_seen = 0
    for ev in events:
        if isinstance(ev, NBBOQuote):
            engine.posterior(ev)
            b, a = float(ev.bid), float(ev.ask)
            quote_ts.append(ev.timestamp_ns)
            quote_bad.append(quote_dropped_by_ofi(b, a))
            if b > 0.0 and a > 0.0:
                quote_mid.append((b + a) / 2.0)
                quote_spread.append(a - b)
            else:
                quote_mid.append(0.0)
                quote_spread.append(0.0)
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
        grid_mids.append(quote_mid[i] if i >= 0 and quote_mid[i] > 0 else None)
    rets = [
        math.log(b2 / a2)
        for a2, b2 in zip(grid_mids, grid_mids[1:])
        if a2 is not None and b2 is not None and a2 > 0 and b2 > 0
    ]
    sigma900 = statistics.stdev(rets) * 1e4 if len(rets) >= 2 else None

    res = CellResult(
        symbol=symbol,
        date=date_str,
        stratum=STRATUM[date_str],
        n_events=len(events),
        n_quotes=n_quotes,
        n_trades=sum(1 for e in events if isinstance(e, Trade)),
        n_boundaries=len(boundary_rows),
        n_in_window=0,
        n_warm_eligible=0,
        calendar_hash=calendar_hash,
        sigma900_bps=sigma900,
        sigma900_n_returns=len(rets),
    )
    is_grid = symbol in GRID_SYMBOLS
    if is_grid and sigma900 is not None:
        res.viable_long = sigma900 >= FLOOR_LONG_BPS[symbol] / KAPPA_FROZEN
        res.viable_short = sigma900 >= FLOOR_SHORT_BPS[symbol] / KAPPA_FROZEN

    warm_counts = {fid: 0 for fid in ENTRY_WARM_IDS}
    cal_warm_in_window = 0
    cal_missing_in_window = 0
    leakage_shares: list[float] = []
    cotravel_eligible = 0
    cotravel_off_clock = 0
    cutoff_secs = SESSION_CUTOFF_ET[0] * 3600 + SESSION_CUTOFF_ET[1] * 60

    for asof_ns, values, warm, stale, p_breakout in boundary_rows:
        for fid in ENTRY_WARM_IDS:
            if warm.get(fid, False):
                warm_counts[fid] += 1

        offset_s = (asof_ns - session_open) // _NS
        dt_et = datetime.fromtimestamp(asof_ns / 1e9, tz=_TZ_ET)
        et_secs = dt_et.hour * 3600 + dt_et.minute * 60 + dt_et.second
        in_session_window = (
            offset_s >= NO_ENTRY_FIRST_SECONDS and et_secs <= cutoff_secs
        )
        if not in_session_window:
            continue

        res.n_in_window += 1
        sfw_warm = warm.get("scheduled_flow_window_active", False)
        if sfw_warm:
            cal_warm_in_window += 1
        elif calendar_empty:
            cal_missing_in_window += 1

        qi = bisect_right(quote_ts, asof_ns) - 1
        spread_ticks = round(quote_spread[qi] / _TICK) if qi >= 0 and quote_spread else None

        all_warm = all(warm.get(fid, False) and not stale.get(fid, True) for fid in ENTRY_WARM_IDS)
        if not all_warm:
            if is_grid:
                res.gate_off += 1
            continue
        res.n_warm_eligible += 1
        if spread_ticks is not None:
            res.spread_ticks_warm.append(spread_ticks)

        if not is_grid:
            continue

        ofi = values.get("ofi_integrated")
        pctl = values.get("ofi_integrated_percentile")
        rvz = values.get("realized_vol_30s_zscore")
        w_hh = values.get("scheduled_flow_window_active")

        quintile_ok, _ = ofi_quintile_side(
            ofi=ofi, pctl=pctl, rvz=rvz, p_breakout=p_breakout
        )
        if quintile_ok:
            cotravel_eligible += 1
            if w_hh is not None and w_hh < 0.5:
                cotravel_off_clock += 1

        ok_in, side_in = is_entry_eligible(
            ofi=ofi,
            pctl=pctl,
            rvz=rvz,
            p_breakout=p_breakout,
            w_hh=w_hh,
            require_clock=True,
        )
        ok_out, side_out = is_entry_eligible(
            ofi=ofi,
            pctl=pctl,
            rvz=rvz,
            p_breakout=p_breakout,
            w_hh=w_hh,
            require_clock=False,
        )

        if ok_in or ok_out:
            res.gate_on += 1
        else:
            res.gate_off += 1
            continue

        if spread_ticks is not None:
            res.spread_ticks_eligible.append(spread_ticks)

        if ok_in:
            res.episodes_in_window += 1
            if side_in == "LONG":
                res.episodes_in_window_long += 1
            else:
                res.episodes_in_window_short += 1
            lo = bisect_left(quote_ts, asof_ns - _OFI_WINDOW_NS)
            hi = bisect_right(quote_ts, asof_ns)
            n_win = hi - lo
            n_bad = sum(quote_bad[lo:hi])
            leakage_shares.append(n_bad / n_win if n_win else 0.0)

        if ok_out:
            res.episodes_out_window += 1
            if side_out == "LONG":
                res.episodes_out_window_long += 1
            else:
                res.episodes_out_window_short += 1

    nb = max(res.n_boundaries, 1)
    res.warm_fraction = {fid: warm_counts[fid] / nb for fid in ENTRY_WARM_IDS}
    res.calendar_warm_fraction_in_window = (
        cal_warm_in_window / res.n_in_window if res.n_in_window else None
    )
    res.calendar_missing_rate = (
        cal_missing_in_window / res.n_in_window if res.n_in_window else 0.0
    )
    if leakage_shares:
        res.leakage_share_mean = sum(leakage_shares) / len(leakage_shares)
        res.leakage_bug_flag = any(s > LEAKAGE_BUG_SHARE for s in leakage_shares)
    if cotravel_eligible:
        res.off_clock_cotravel_rate = cotravel_off_clock / cotravel_eligible
    return res


def run_cell(cache: DiskEventCache, symbol: str, date_str: str) -> CellResult | None:
    events = cache.load(symbol, date_str)
    if not events:
        return None
    return run_cell_from_events(events, symbol, date_str)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path.home() / ".feelies" / "cache")
    ap.add_argument("--json", type=Path, default=None)
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
        use_dates = dates if sym in GRID_SYMBOLS else DATES
        for d in use_dates:
            cell = run_cell(cache, sym, d)
            if cell is not None:
                cells.append(cell)

    warm_by_sym: dict[str, list[float]] = {s: [] for s in GRID_SYMBOLS}
    for c in cells:
        if c.symbol in GRID_SYMBOLS and c.calendar_warm_fraction_in_window is not None:
            warm_by_sym[c.symbol].append(c.calendar_warm_fraction_in_window)
    dropped = apply_warm_drop_rule(warm_by_sym)

    grid_cells = [c for c in cells if c.symbol in GRID_SYMBOLS]
    infra_calendar = any(c.calendar_missing_rate > 0 for c in grid_cells)

    per_symbol: dict[str, Any] = {}
    for sym in GRID_SYMBOLS:
        sym_cells = [c for c in cells if c.symbol == sym]
        eps_all = sum(c.episodes_in_window for c in sym_cells)
        eps_viable = sum(
            c.episodes_in_window for c in sym_cells if c.viable_long
        )
        eps_viable_long = sum(
            c.episodes_in_window_long for c in sym_cells if c.viable_long
        )
        edge_empty = all(
            (c.episodes_in_window if c.viable_long else 0) == 0 for c in sym_cells
        )
        per_symbol[sym] = {
            "episodes_in_window_all": eps_all,
            "episodes_in_window_viable_region": eps_viable,
            "episodes_in_window_viable_long_only": eps_viable_long,
            "episodes_out_window_all": sum(c.episodes_out_window for c in sym_cells),
            "edge_region_empty": edge_empty,
            "warm_drop": sym in dropped,
            "calendar_warm_fractions": warm_by_sym[sym],
            "calendar_missing_any": any(c.calendar_missing_rate > 0 for c in sym_cells),
            "leakage_bug_any": any(c.leakage_bug_flag for c in sym_cells),
        }

    deployable = [
        s
        for s in GRID_SYMBOLS
        if not per_symbol[s]["edge_region_empty"] and not per_symbol[s]["warm_drop"]
    ]
    pooled = sum(
        per_symbol[s]["episodes_in_window_viable_region"] for s in deployable
    )
    emptiness = all(per_symbol[s]["edge_region_empty"] for s in GRID_SYMBOLS)
    park_power = pooled < POWER_FLOOR

    if infra_calendar:
        verdict = "INFRA_CALENDAR_MISSING"
    elif emptiness:
        verdict = "PARKED_EDGE_EMPTINESS"
    elif park_power:
        verdict = "PARKED_POWER"
    else:
        verdict = "PROCEED_CENSUS"

    out = {
        "protocol": (
            "sig_halfhour_clock_drift_h900_v1_validation_protocol.md step 1 (frozen)"
        ),
        "instrument": "halfhour_clock_drift_census.py (Phase-A; §1.1 predicate exact)",
        "run_parameters": {
            "kappa": KAPPA_FROZEN,
            "power_floor": POWER_FLOOR,
            "ofi_pctl_hi": OFI_PCTL_HI,
            "ofi_pctl_lo": OFI_PCTL_LO,
            "horizon": _HORIZON,
            "preamble_only": bool(args.preamble_only),
            "n_ledger_at_instrument_build": 12,
            "outcome_contact": False,
        },
        "cells": [asdict(c) for c in cells],
        "per_symbol": per_symbol,
        "park_conditions": {
            "edge_region_emptiness": emptiness,
            "power_floor_failed": park_power,
            "pooled_viable_episodes_in_window": pooled,
            "deployable_set_D": deployable,
            "warm_dropped": sorted(dropped),
            "infra_calendar_missing": infra_calendar,
        },
        "jc1_reports": {
            "leakage_bug_share_threshold": LEAKAGE_BUG_SHARE,
            "any_leakage_bug_flag": any(c.leakage_bug_flag for c in cells),
            "note": "diagnostic only — never park / never power deflator",
        },
        "verdict": verdict,
    }

    text = json.dumps(out, indent=2, sort_keys=True)
    if args.json is not None:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    print(
        f"# verdict={verdict} pooled_viable={pooled} D={deployable} "
        f"warm_dropped={sorted(dropped)} infra_cal={infra_calendar}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
