#!/usr/bin/env python3
"""Task 8 step 1 — park-rule census for ``sig_dislocation_lambda_drift_v1``.

Executes EXACTLY the frozen protocol step 1
(``docs/research/sig_dislocation_lambda_drift_v1_validation_protocol.md``
§1, frozen at commit 2079f50).  Offline deterministic scan of the
20-cell {APP, RMBS} x 10-date grid; OLN x 10 replayed alongside
EVIDENCE-ONLY (no ``disloc_min`` gate — boundary/spread/warm reporting
only, never episode counts toward D).  **NO forward returns, NO IC, NO
signal evaluation** — the only return-like quantity is the
unconditional session sigma_300 (Bessel-corrected std of
non-overlapping 300 s mid log-returns on the 09:30-anchored RTH grid,
bps), which conditions on nothing signal-related (protocol §1.2).

Episode instrument (protocol §1.1 / task Amendment B): the Appendix-A
contamination read (``scripts/research/h8_contamination_read.py`` at
git 8c69d49), pipeline and entry predicate transplanted VERBATIM —
same gate arms, same thresholds, same warm handling, same regime
machinery.  A runtime assertion pins the primary entry constants to
the Appendix-A values.

Contamination instrument (§1.3, JC-1 RULED — three counts per cell):
  (a) including-flagged — the instrument's own count (reproduces the
      read's pooled 81/77 by construction);
  (b) intensity-excluded PRIMARY — a boundary is excluded iff its own
      trailing-60 s window flagged-print share >= 2.0 x the session
      tape base rate on the COUNT basis (volume-basis exclusion
      reported alongside, never binding).  A window with zero prints
      carries no intensity evidence and is not excluded (disclosed);
  (c) binary-excluded — the H2 any-flag convention, disclosed for
      continuity (saturates on H8).

Variant mode (§1.7): ``--disloc-multiple`` and ``--kappa`` override
the frozen constants for the single pre-authorized occupancy-based
re-threshold re-census; instruments and park conditions identical.
The occupancy block (curve + the pinned JC-10 derivation arithmetic)
is emitted on every run; it is CONSUMED only under the §1.7 post-park
path.

Determinism: run under PYTHONHASHSEED=0; no RNG, no wall-clock reads;
events sorted by (timestamp_ns, sequence); fresh sensor/regime state
per (symbol, session) cell.

Usage
-----
    PYTHONHASHSEED=0 uv run python scripts/research/dislocation_lambda_census.py \
        [--cache-dir ~/.feelies/cache] [--json out.json] \
        [--disloc-multiple 0.75] [--kappa 0.190]
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
_TICK = 0.01

# ── Frozen evidence set (protocol preamble / 03c §5.1) ───────────────────

GRID_SYMBOLS = ("APP", "RMBS")  # deployable-candidate grid; OLN evidence-only
EVIDENCE_ONLY_SYMBOLS = ("OLN",)
SYMBOLS = GRID_SYMBOLS + EVIDENCE_ONLY_SYMBOLS
DATES_ELEVATED_A = ("2025-11-25", "2025-12-04")
DATES_CALM = ("2025-12-22", "2026-01-05", "2026-01-15", "2026-01-26", "2026-01-27")
DATES_ELEVATED_B = ("2026-04-01", "2026-04-10", "2026-04-22")
DATES = DATES_ELEVATED_A + DATES_CALM + DATES_ELEVATED_B

STRATUM = (
    {d: "elevated_A" for d in DATES_ELEVATED_A}
    | {d: "calm" for d in DATES_CALM}
    | {d: "elevated_B" for d in DATES_ELEVATED_B}
)

# ── Frozen H8 entry constants (Appendix-A instrument, pinned) ────────────

LAMBDA_PCTL_MIN = 0.5  # the median split under resolution
DISLOC_MULTIPLE_FROZEN = 0.75
# pack-05 map p50 sigma_300 (bps): APP 33.8084, RMBS 31.622.
SIGMA300_MED_BPS = {"APP": 33.8084, "RMBS": 31.622}
# 0.75 x median sigma_300 as a FRACTION of the micro-price level —
# the Appendix-A constants, verbatim.
DISLOC_FRAC_MIN_FROZEN = {"APP": 25.3563e-4, "RMBS": 23.7165e-4}
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

# ── Frozen viable-region arithmetic (protocol §1.2; 8-F §11.1 anchor) ────
# floor = 2.25 x (2.0 + fee); fees at the 80-share reference fill against
# pack-05 median RTH bids (APP $544.075, RMBS $102.06).  Short floors are
# rider-inclusive (+0.5 bps regulatory + TAF).  kappa = 0.190 FROZEN.

KAPPA_FROZEN = 0.190
FLOOR_LONG_BPS = {"APP": 4.6809, "RMBS": 5.4645}
FLOOR_SHORT_BPS = {"APP": 5.82, "RMBS": 6.60}
POWER_FLOOR = 100

# ── §1.3 contamination sets (03b §3.3 Class B / §4.4 corrections) ────────

CLASS_B_CONDITIONS = frozenset({2, 7, 8, 9, 10, 13, 15, 16, 17, 22, 29, 32, 35, 52, 53})
CORRECTION_RECORDS = frozenset({10, 11, 12})
CONTAM_WINDOW_NS = 60 * _NS  # the kyle_lambda_60s trailing sensor window
INTENSITY_RATIO = 2.0  # frozen §2 materiality bar, boundary granularity

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

# ── JC-10 mechanical kappa adjustment (§1.7, pinned) ─────────────────────


def _phi(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _upper_tail(x: float) -> float:
    return 0.5 * math.erfc(x / math.sqrt(2.0))  # 1 - Phi(x)


def c_d(m: float) -> float:
    """Inverse Mills ratio E[|z| : |z| >= m] under the card's near-Gaussian identity."""
    return _phi(m) / _upper_tail(m)


# Card block-2 design occupancy for the dislocation arm: P(|z| >= 0.75)
# near-Gaussian = 2 x (1 - Phi(0.75)) ~ 0.4533; x the pinned lambda arm
# 0.5 => joint ~ 0.2266 ~ the card's 0.226.
P_STAR_DISLOC = 2.0 * _upper_tail(DISLOC_MULTIPLE_FROZEN)


def _in_rth(exchange_timestamp_ns: int) -> bool:
    dt = datetime.fromtimestamp(exchange_timestamp_ns / 1e9, tz=_TZ_ET)
    secs = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (9 * 3600 + 30 * 60) <= secs < (16 * 3600)


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
    # unconditional session sigma_300 (protocol §1.2 estimator):
    sigma300_bps: float | None = None
    sigma300_n_returns: int = 0
    viable_long: bool | None = None  # sigma300 >= floor_long / kappa
    viable_short: bool | None = None  # sigma300 >= floor_short / kappa (rider-incl.)
    # §1.3 three counts (long = micro_price_drift > 0, short = < 0):
    cond_incl: int = 0  # (a) including-flagged (Appendix-A count)
    cond_incl_long: int = 0
    cond_incl_short: int = 0
    cond_primary: int = 0  # (b) intensity-excluded, COUNT basis (PRIMARY)
    cond_primary_long: int = 0
    cond_primary_short: int = 0
    cond_excluded_volume_basis: int = 0  # volume-basis exclusions (reported, never binding)
    cond_binary: int = 0  # (c) binary any-flag excluded (H2 convention)
    cond_binary_long: int = 0
    cond_binary_short: int = 0
    # session tape base rates (intensity denominator):
    tape_prints: int = 0
    tape_flagged_prints: int = 0
    tape_volume: float = 0.0
    tape_flagged_volume: float = 0.0
    # (gate state x daily stratum) inputs — gate ON = §1.1 arms 3-6 on
    # warm in-window boundaries:
    gate_on: int = 0
    gate_off: int = 0
    # spread-in-ticks samples (protocol §1.4 / §4.1 tercile input):
    spread_ticks_eligible: list[int] = field(default_factory=list)
    spread_ticks_warm: list[int] = field(default_factory=list)
    # §1.7 occupancy input: |micro_price_drift| / micro_price at warm
    # in-window boundaries (grid symbols only; return-free):
    disloc_fracs_warm: list[float] = field(default_factory=list)


def run_cell(
    cache: DiskEventCache,
    symbol: str,
    date: str,
    disloc_frac_min: dict[str, float],
    kappa: float,
) -> CellResult | None:
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
    assert set(ENTRY_WARM_IDS) <= fids, f"required h={_HORIZON} features not wired: {sorted(fids)}"

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
        session_id=f"H8CENSUS_{symbol}_{date}",
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

    # Print tape: (ts, size, flagged) for every RTH trade — Appendix-A
    # instrument, verbatim.
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

    # Valid-quote series for sigma_300 mid sampling and boundary-time
    # prevailing spread (additive outputs; predicate untouched).
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

    # sigma_300 (protocol §1.2, recorded not tuned): Bessel-corrected
    # sample std of non-overlapping 300 s mid log-returns on the
    # 09:30-anchored grid, last-mid-at-or-before sampling, bps.
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
    sigma300 = statistics.stdev(rets) * 1e4 if len(rets) >= 2 else None

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
        sigma300_bps=sigma300,
        sigma300_n_returns=len(rets),
        tape_prints=len(trade_ts),
        tape_flagged_prints=sum(trade_flagged),
        tape_volume=sum(trade_size),
        tape_flagged_volume=sum(sz for sz, fl in zip(trade_size, trade_flagged) if fl),
    )
    is_grid = symbol in disloc_frac_min
    if is_grid and sigma300 is not None:
        res.viable_long = sigma300 >= FLOOR_LONG_BPS[symbol] / kappa
        res.viable_short = sigma300 >= FLOOR_SHORT_BPS[symbol] / kappa

    # Session tape base rates (intensity-exclusion denominators, §1.3(b)).
    tape_count_base = res.tape_flagged_prints / res.tape_prints if res.tape_prints else 0.0
    tape_volume_base = res.tape_flagged_volume / res.tape_volume if res.tape_volume else 0.0

    warm_counts = {fid: 0 for fid in ENTRY_WARM_IDS}
    cutoff_secs = SESSION_CUTOFF_ET[0] * 3600 + SESSION_CUTOFF_ET[1] * 60
    disloc_min = disloc_frac_min.get(symbol)
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

        pctl = values.get("kyle_lambda_60s_percentile")
        drift = values.get("micro_price_drift")
        mp = values.get("micro_price")
        rvz = values.get("realized_vol_30s_zscore")
        if is_grid and drift is not None and mp is not None and mp > 0.0:
            res.disloc_fracs_warm.append(abs(drift) / mp)
        if not is_grid:
            continue  # OLN: evidence-only — no episode predicate, ever
        if pctl is None or drift is None or mp is None or rvz is None or mp <= 0.0:
            res.gate_off += 1
            continue
        if p_breakout is None:
            res.gate_off += 1
            continue
        assert disloc_min is not None
        if (
            pctl < LAMBDA_PCTL_MIN
            or abs(drift) / mp < disloc_min
            or p_breakout >= P_VOL_BREAKOUT_MAX
            or rvz > RV_Z_MAX
        ):
            res.gate_off += 1
            continue

        # Eligible boundary (= one episode) under the pinned instrument.
        res.gate_on += 1
        is_long = drift > 0.0

        lo = bisect_left(trade_ts, asof_ns - CONTAM_WINDOW_NS + 1)
        hi = bisect_right(trade_ts, asof_ns)
        window_prints = hi - lo
        window_flagged = sum(trade_flagged[lo:hi])
        window_volume = sum(trade_size[lo:hi])
        window_flagged_volume = sum(
            sz for sz, fl in zip(trade_size[lo:hi], trade_flagged[lo:hi]) if fl
        )
        window_any_flag = window_flagged > 0
        count_share = window_flagged / window_prints if window_prints else 0.0
        volume_share = window_flagged_volume / window_volume if window_volume else 0.0
        # A window with zero flagged prints is never intensity-excluded
        # (guards the degenerate base-rate-0 session; disclosed).
        excluded_count_basis = (
            window_flagged > 0 and count_share >= INTENSITY_RATIO * tape_count_base
        )
        excluded_volume_basis = (
            window_flagged_volume > 0 and volume_share >= INTENSITY_RATIO * tape_volume_base
        )

        res.cond_incl += 1
        if is_long:
            res.cond_incl_long += 1
        else:
            res.cond_incl_short += 1
        if spread_ticks is not None:
            res.spread_ticks_eligible.append(spread_ticks)
        if not excluded_count_basis:
            res.cond_primary += 1
            if is_long:
                res.cond_primary_long += 1
            else:
                res.cond_primary_short += 1
        if excluded_volume_basis:
            res.cond_excluded_volume_basis += 1
        if not window_any_flag:
            res.cond_binary += 1
            if is_long:
                res.cond_binary_long += 1
            else:
                res.cond_binary_short += 1

    nb = max(res.n_boundaries, 1)
    res.warm_fraction = {fid: warm_counts[fid] / nb for fid in ENTRY_WARM_IDS}
    return res


def _quantiles_or_none(data: list[int] | list[float], n: int) -> list[float] | None:
    if len(data) < 2:
        return None
    return [round(q, 6) for q in statistics.quantiles(data, n=n, method="inclusive")]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache-dir", type=Path, default=Path.home() / ".feelies" / "cache")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument(
        "--disloc-multiple",
        type=float,
        default=DISLOC_MULTIPLE_FROZEN,
        help="dislocation multiple m (0.75 frozen primary; §1.7 variant only)",
    )
    ap.add_argument(
        "--kappa",
        type=float,
        default=KAPPA_FROZEN,
        help="kappa for viability floors (0.190 frozen primary; §1.7 variant only)",
    )
    args = ap.parse_args(argv)

    m = args.disloc_multiple
    kappa = args.kappa
    if m == DISLOC_MULTIPLE_FROZEN:
        # Runtime pin of the Appendix-A instrument constants (§1.1 dev row 3).
        disloc_frac_min = dict(DISLOC_FRAC_MIN_FROZEN)
        for sym in GRID_SYMBOLS:
            derived = m * SIGMA300_MED_BPS[sym] * 1e-4
            assert abs(derived - disloc_frac_min[sym]) < 1e-12, (
                f"{sym}: derived disloc_min {derived!r} != pinned {disloc_frac_min[sym]!r}"
            )
    else:
        disloc_frac_min = {sym: m * SIGMA300_MED_BPS[sym] * 1e-4 for sym in GRID_SYMBOLS}
    assert kappa <= KAPPA_FROZEN, "one-way kappa ratchet: kappa_variant <= 0.190 (JC-10)"

    cache = DiskEventCache(args.cache_dir)
    cells: list[CellResult] = []
    for symbol in SYMBOLS:
        for date in DATES:
            print(f"# {symbol} {date} ...", file=sys.stderr, flush=True)
            cell = run_cell(cache, symbol, date, disloc_frac_min, kappa)
            if cell is None:
                print(f"  ! MISSING cache for {symbol}/{date}", file=sys.stderr)
                continue
            cells.append(cell)

    # ── Per-symbol roll-up and §1.5 park scoring ─────────────────────────
    per_symbol: dict[str, dict] = {}
    for symbol in SYMBOLS:
        sc = [c for c in cells if c.symbol == symbol]
        is_grid = symbol in GRID_SYMBOLS
        spread_warm_all = [t for c in sc for t in c.spread_ticks_warm]
        spread_elig_all = [t for c in sc for t in c.spread_ticks_eligible]
        entry = {
            "n_cells": len(sc),
            "n_in_window": sum(c.n_in_window for c in sc),
            "n_warm_eligible": sum(c.n_warm_eligible for c in sc),
            "warm_fraction_mean": {
                fid: round(sum(c.warm_fraction[fid] for c in sc) / max(len(sc), 1), 6)
                for fid in ENTRY_WARM_IDS
            },
            "spread_ticks_warm_n": len(spread_warm_all),
            "spread_ticks_warm_quartiles": _quantiles_or_none(spread_warm_all, 4),
            "spread_ticks_warm_terciles": _quantiles_or_none(spread_warm_all, 3),
            "spread_ticks_eligible_n": len(spread_elig_all),
            "spread_ticks_eligible_quartiles": _quantiles_or_none(spread_elig_all, 4),
        }
        if is_grid:
            viable_long = [c for c in sc if c.viable_long]
            viable_short = [c for c in sc if c.viable_short]
            in_viable = lambda c: bool(c.viable_long)  # noqa: E731
            entry.update(
                {
                    "floor_long_bps": FLOOR_LONG_BPS[symbol],
                    "floor_short_bps": FLOOR_SHORT_BPS[symbol],
                    "sigma300_min_long_bps": round(FLOOR_LONG_BPS[symbol] / kappa, 4),
                    "sigma300_min_short_bps": round(FLOOR_SHORT_BPS[symbol] / kappa, 4),
                    "disloc_frac_min": disloc_frac_min[symbol],
                    "n_viable_cells_long": len(viable_long),
                    "viable_dates_long": sorted(c.date for c in viable_long),
                    "n_viable_cells_short": len(viable_short),
                    "viable_dates_short": sorted(c.date for c in viable_short),
                    # §1.3 three counts, all cells:
                    "cond_incl_all": sum(c.cond_incl for c in sc),
                    "cond_primary_all": sum(c.cond_primary for c in sc),
                    "cond_binary_all": sum(c.cond_binary for c in sc),
                    "cond_excluded_volume_basis_all": sum(
                        c.cond_excluded_volume_basis for c in sc
                    ),
                    # viable-region counts (the §1.5 power axis binds on primary):
                    "viable_region_primary": sum(c.cond_primary for c in sc if in_viable(c)),
                    "viable_region_primary_long": sum(
                        c.cond_primary_long for c in sc if in_viable(c)
                    ),
                    "viable_region_primary_short": sum(
                        c.cond_primary_short for c in sc if in_viable(c)
                    ),
                    "viable_region_incl": sum(c.cond_incl for c in sc if in_viable(c)),
                    "viable_region_binary": sum(c.cond_binary for c in sc if in_viable(c)),
                    # per-stratum primary counts (L4: A/B never pooled):
                    "primary_elevated_A": sum(
                        c.cond_primary for c in sc if c.stratum == "elevated_A"
                    ),
                    "primary_elevated_B": sum(
                        c.cond_primary for c in sc if c.stratum == "elevated_B"
                    ),
                    "primary_calm": sum(c.cond_primary for c in sc if c.stratum == "calm"),
                }
            )
            # §1.5/§1.6 deployability: >= 100 viable-region primary
            # episodes.  The long-only restatement rule is pre-registered
            # for RMBS ONLY: if any long-viable RMBS cell fails the
            # rider-inclusive SELL-leg axis, RMBS restates long-only and
            # power re-checks on the continuation-long count alone.  APP
            # binds on the full viable-region primary count (its short
            # side clears rider-inclusive at the median, spec §5.2).
            sell_leg_ok = len(viable_long) > 0 and all(c.viable_short for c in viable_long)
            entry["sell_leg_axis_ok"] = sell_leg_ok
            if symbol == "RMBS" and not sell_leg_ok:
                entry["restated_long_only"] = True
                power_count = entry["viable_region_primary_long"]
            else:
                entry["restated_long_only"] = False
                power_count = entry["viable_region_primary"]
            entry["power_count_after_restatement"] = power_count
            entry["deployable_candidate"] = bool(power_count >= POWER_FLOOR)
        per_symbol[symbol] = entry

    deployable = [s for s in GRID_SYMBOLS if per_symbol[s]["deployable_candidate"]]
    emptiness = all(per_symbol[s]["viable_region_primary"] == 0 for s in GRID_SYMBOLS)
    park_on_power = not deployable
    # §1.6: APP fails power => card PARKS regardless of RMBS.
    app_parks_card = not per_symbol["APP"]["deployable_candidate"]
    verdict = "PARK" if (emptiness or park_on_power or app_parks_card) else "PROCEED"

    # ── §1.7 occupancy block (census-legal, return-free; consumed only
    # under the post-park path) ──────────────────────────────────────────
    z_pooled: list[float] = []
    z_per_symbol: dict[str, list[float]] = {}
    for symbol in GRID_SYMBOLS:
        med_frac = SIGMA300_MED_BPS[symbol] * 1e-4
        zs = [d / med_frac for c in cells if c.symbol == symbol for d in c.disloc_fracs_warm]
        z_per_symbol[symbol] = zs
        z_pooled.extend(zs)
    m_grid = [round(0.05 * i, 2) for i in range(1, 31)]
    occupancy_curve = {
        "m_grid": m_grid,
        "pooled": [
            round(sum(1 for z in z_pooled if z >= mg) / max(len(z_pooled), 1), 6) for mg in m_grid
        ],
        **{
            sym: [
                round(
                    sum(1 for z in z_per_symbol[sym] if z >= mg) / max(len(z_per_symbol[sym]), 1),
                    6,
                )
                for mg in m_grid
            ]
            for sym in GRID_SYMBOLS
        },
    }
    # Pinned JC-10 derivation arithmetic: m_v = the k-th largest pooled z
    # with k = ceil(p* x n), p* = 2(1 - Phi(0.75)) — the smallest multiple
    # whose realized dislocation-arm occupancy >= p*; kappa_variant =
    # min(0.190, 0.190 x c_D(m_v) / c_D(0.75)).
    derivation: dict[str, object] = {"p_star_disloc": round(P_STAR_DISLOC, 6)}
    if z_pooled:
        z_desc = sorted(z_pooled, reverse=True)
        n_z = len(z_desc)
        k_target = math.ceil(P_STAR_DISLOC * n_z)
        m_v = z_desc[k_target - 1]
        occ_at_m_v = sum(1 for z in z_pooled if z >= m_v) / n_z
        kappa_variant = min(KAPPA_FROZEN, KAPPA_FROZEN * c_d(m_v) / c_d(0.75))
        derivation.update(
            {
                "n_warm_boundaries_pooled": n_z,
                "k_target": k_target,
                "m_v": round(m_v, 6),
                "occupancy_at_m_v_pooled": round(occ_at_m_v, 6),
                "occupancy_at_frozen_0p75_pooled": round(
                    sum(1 for z in z_pooled if z >= DISLOC_MULTIPLE_FROZEN) / n_z, 6
                ),
                "c_d_m_v": round(c_d(m_v), 6),
                "c_d_0p75": round(c_d(0.75), 6),
                "kappa_variant": round(kappa_variant, 6),
                "sigma300_min_long_at_kappa_variant": {
                    s: round(FLOOR_LONG_BPS[s] / kappa_variant, 4) for s in GRID_SYMBOLS
                },
                "sigma300_min_short_at_kappa_variant": {
                    s: round(FLOOR_SHORT_BPS[s] / kappa_variant, 4) for s in GRID_SYMBOLS
                },
            }
        )

    out = {
        "protocol": "sig_dislocation_lambda_drift_v1_validation_protocol.md step 1 (frozen)",
        "instrument": "Appendix-A read (h8_contamination_read.py @ 8c69d49), verbatim predicate",
        "run_parameters": {
            "disloc_multiple": m,
            "kappa": kappa,
            "disloc_frac_min": disloc_frac_min,
            "intensity_ratio": INTENSITY_RATIO,
            "power_floor": POWER_FLOOR,
            "is_primary_run": m == DISLOC_MULTIPLE_FROZEN and kappa == KAPPA_FROZEN,
        },
        "cells": [asdict(c) for c in cells],
        "per_symbol": per_symbol,
        "park_conditions": {
            "edge_region_emptiness": emptiness,
            "power_floor_failed_all_symbols": park_on_power,
            "app_primary_fails_power": app_parks_card,
            "deployable_set_D": deployable,
        },
        "verdict": verdict,
        "occupancy_curve": occupancy_curve,
        "occupancy_derivation_jc10": derivation,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"wrote {args.json}", file=sys.stderr)

    # Human-readable table.
    print("\n== Census cells ==")
    hdr = (
        f"{'sym':<5}{'date':<12}{'strat':<11}{'bnd':>5}{'win':>5}{'warm':>6}"
        f"{'sig300':>8}{'viaL':>6}{'viaS':>6}"
        f"{'incl':>6}{'prim':>6}{'pLng':>6}{'pSht':>6}{'bin':>5}"
        f"{'gON':>5}{'gOFF':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for c in cells:
        s = "n/a" if c.sigma300_bps is None else f"{c.sigma300_bps:.1f}"
        vl = "-" if c.viable_long is None else ("YES" if c.viable_long else "no")
        vs = "-" if c.viable_short is None else ("YES" if c.viable_short else "no")
        print(
            f"{c.symbol:<5}{c.date:<12}{c.stratum:<11}{c.n_boundaries:>5}{c.n_in_window:>5}"
            f"{c.n_warm_eligible:>6}{s:>8}{vl:>6}{vs:>6}"
            f"{c.cond_incl:>6}{c.cond_primary:>6}{c.cond_primary_long:>6}"
            f"{c.cond_primary_short:>6}{c.cond_binary:>5}{c.gate_on:>5}{c.gate_off:>6}"
        )
    print("\n== Per-symbol roll-up ==")
    for symbol in SYMBOLS:
        print(f"{symbol}: {json.dumps(per_symbol[symbol])}")
    print(f"\nDeployable set D = {deployable}")
    print(
        f"Park (emptiness) = {emptiness}; Park (power) = {park_on_power}; "
        f"APP-primary-parks = {app_parks_card}"
    )
    print(f"VERDICT: {verdict}")
    print(f"Occupancy derivation (JC-10, consumed only under §1.7): {json.dumps(derivation)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
