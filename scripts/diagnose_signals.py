#!/usr/bin/env python3
"""Systematic Phase-3 signal-path diagnostic (recommended investigation order).

Replays the backtest pipeline like ``run_backtest.py``, records shadow
regime/sensor caches at each ``HorizonFeatureSnapshot``, then replays
gate + ``evaluate()`` in chronological order with counters.

Usage:
    python3 scripts/diagnose_signals.py --symbol AAPL --date 2026-04-08
    python3 scripts/diagnose_signals.py --config platform.yaml --symbol AAPL --date 2026-04-08 --horizon 300
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from feelies.bootstrap import build_platform
from feelies.core.events import (
    HorizonFeatureSnapshot,
    RegimeState,
    SensorReading,
    Signal,
    SignalDirection,
)
from feelies.core.platform_config import PlatformConfig
from feelies.signals.horizon_engine import HorizonSignalEngine
from feelies.signals.regime_gate import (
    RegimeGateError,
    UnknownIdentifierError,
)

# Keep tuple-sensor fan-out aligned with HorizonSignalEngine._TUPLE_SENSOR_COMPONENTS.
_TUPLE_SENSOR_COMPONENTS: dict[str, tuple[str, ...]] = {
    "scheduled_flow_window": (
        "scheduled_flow_window_active",
        "seconds_to_window_close",
        "scheduled_flow_window_id_hash",
        "scheduled_flow_window_direction_prior",
    ),
}


def _lookup_regime_shadow(
    symbol: str,
    gate,
    regime_cache: dict[tuple[str, str], RegimeState],
) -> RegimeState | None:
    if gate.engine_name is not None:
        return regime_cache.get((symbol, gate.engine_name))
    best: RegimeState | None = None
    for (sym, _engine), state in regime_cache.items():
        if sym != symbol:
            continue
        if best is None or state.timestamp_ns > best.timestamp_ns:
            best = state
    return best


def _shadow_update_sensor(sensor_cache: dict[tuple[str, str], float], ev: SensorReading) -> None:
    if not ev.warm:
        return
    val = ev.value
    if isinstance(val, tuple):
        comps = _TUPLE_SENSOR_COMPONENTS.get(ev.sensor_id)
        if comps is None:
            return
        for name, component_value in zip(comps, val):
            sensor_cache[(ev.symbol, name)] = float(component_value)
        return
    sensor_cache[(ev.symbol, ev.sensor_id)] = float(val)


@dataclass
class AlphaDiag:
    suppressed_not_ready: int = 0
    gate_unknown_id: int = 0
    gate_other_error: int = 0
    gate_off: int = 0
    evaluate_none: int = 0
    evaluate_flat: int = 0
    evaluate_exception: int = 0
    signal_non_flat: int = 0
    boundaries_seen: int = 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose zero-signal horizon pipeline.")
    parser.add_argument("--config", type=Path, default=_PROJECT_ROOT / "platform.yaml")
    parser.add_argument("--symbol", nargs="+", help="Override universe (uppercase symbols)")
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument(
        "--horizon",
        type=int,
        default=None,
        help="Only analyse this horizon_seconds (default: all horizons)",
    )
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("MASSIVE_API_KEY")
    if not api_key:
        print("ERROR: MASSIVE_API_KEY not set (required unless cache serves all days).", file=sys.stderr)
        return 1

    config_path = args.config
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        return 1

    config = PlatformConfig.from_yaml(config_path)
    if args.symbol:
        config = replace(config, symbols=frozenset(s.upper() for s in args.symbol))

    symbols = sorted(config.symbols)
    if not symbols:
        print("ERROR: No symbols.", file=sys.stderr)
        return 1

    rb_path = _PROJECT_ROOT / "scripts" / "run_backtest.py"
    spec = importlib.util.spec_from_file_location("feelies_run_backtest_diag", rb_path)
    if spec is None or spec.loader is None:
        print(f"ERROR: cannot load {rb_path}", file=sys.stderr)
        return 1
    rb_mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, rb_mod)
    spec.loader.exec_module(rb_mod)
    ingest_data = rb_mod.ingest_data

    event_log, _ingest, _days = ingest_data(
        api_key,
        symbols,
        args.date,
        args.date,
        cache_dir=args.cache_dir,
        no_cache=args.no_cache,
    )

    orchestrator, _cfg = build_platform(config, event_log=event_log)
    bus = orchestrator._bus
    hse = orchestrator._horizon_signal_engine

    if hse is None or hse.is_empty:
        print("HorizonSignalEngine missing or empty — no SIGNAL alphas registered.")
        return 1

    regime_cache: dict[tuple[str, str], RegimeState] = {}
    sensor_cache: dict[tuple[str, str], float] = {}
    snapshot_rows: list[dict[str, object]] = []
    signal_count = 0

    def on_all(ev: object) -> None:
        nonlocal signal_count
        if isinstance(ev, RegimeState):
            regime_cache[(ev.symbol, ev.engine_name)] = ev
        elif isinstance(ev, SensorReading):
            _shadow_update_sensor(sensor_cache, ev)
        elif isinstance(ev, HorizonFeatureSnapshot):
            snapshot_rows.append(
                {
                    "snapshot": ev,
                    "regime_cache": dict(regime_cache),
                    "sensor_cache": dict(sensor_cache),
                }
            )
        elif isinstance(ev, Signal):
            signal_count += 1

    bus.subscribe_all(on_all)

    orchestrator.boot(config)
    orchestrator.run_backtest()

    hz_arg = args.horizon
    rows = snapshot_rows
    if hz_arg is not None:
        rows = [r for r in rows if r["snapshot"].horizon_seconds == hz_arg]

    print(f"\nReplay: {len(snapshot_rows):,} horizon snapshots total")
    if hz_arg is not None:
        print(f"Filtered to horizon_seconds={hz_arg}: {len(rows):,} snapshots")
    print(f"Signal events observed on bus during replay: {signal_count}")

    # ── Step 1–2: boundary health (why HorizonSignalEngine returns early) ──
    cold_feature_counts: dict[tuple[int, str], int] = defaultdict(int)
    stale_feature_counts: dict[tuple[int, str], int] = defaultdict(int)
    snapshots_with_nonempty_warm = 0
    suppressed_by_warm_stale = 0
    for row in rows:
        snap: HorizonFeatureSnapshot = row["snapshot"]  # type: ignore[assignment]
        if not snap.warm:
            continue
        snapshots_with_nonempty_warm += 1
        not_warm = any(not v for v in snap.warm.values())
        is_stale = any(v for v in snap.stale.values())
        if not_warm:
            suppressed_by_warm_stale += 1
            for fid, is_w in snap.warm.items():
                if not is_w:
                    cold_feature_counts[(snap.horizon_seconds, fid)] += 1
        if is_stale:
            for fid, is_s in snap.stale.items():
                if is_s:
                    stale_feature_counts[(snap.horizon_seconds, fid)] += 1

    print("\n── Snapshot warm/stale (HorizonSignalEngine first gate) ──")
    print(f"  snapshots with non-empty warm map:     {snapshots_with_nonempty_warm:,}")
    print(f"  …of those, any cold OR any stale:      {suppressed_by_warm_stale:,}")
    top_cold = sorted(cold_feature_counts.items(), key=lambda kv: -kv[1])[:12]
    if top_cold:
        print("  Top cold features (horizon_seconds, feature_id) → count:")
        for (hz, fid), n in top_cold:
            print(f"    ({hz}, {fid!r}) → {n:,}")
    top_stale = sorted(stale_feature_counts.items(), key=lambda kv: -kv[1])[:8]
    if top_stale:
        print("  Top stale features:")
        for (hz, fid), n in top_stale:
            print(f"    ({hz}, {fid!r}) → {n:,}")

    # Reset gate hysteresis — engines mutated latches during replay; we replay decisions offline.
    for reg in hse.signals:
        for sym in symbols:
            reg.gate.reset(sym)

    signals_sorted = sorted(hse.signals, key=lambda s: (s.horizon_seconds, s.alpha_id))
    per_alpha: dict[str, AlphaDiag] = defaultdict(AlphaDiag)

    sort_key = lambda r: (
        r["snapshot"].timestamp_ns,
        r["snapshot"].horizon_seconds,
        r["snapshot"].boundary_index,
        r["snapshot"].symbol,
    )
    for row in sorted(rows, key=sort_key):
        snap: HorizonFeatureSnapshot = row["snapshot"]  # type: ignore[assignment]
        rc: dict[tuple[str, str], RegimeState] = row["regime_cache"]  # type: ignore[assignment]
        sc: dict[tuple[str, str], float] = row["sensor_cache"]  # type: ignore[assignment]

        for reg in signals_sorted:
            if reg.horizon_seconds != snap.horizon_seconds:
                continue
            d = per_alpha[reg.alpha_id]
            d.boundaries_seen += 1

            if snap.warm:
                if reg.required_warm_feature_ids is None:
                    keys_chk = tuple(snap.warm.keys())
                else:
                    keys_chk = tuple(reg.required_warm_feature_ids)
                not_warm = any(
                    not snap.warm[k] for k in keys_chk if k in snap.warm
                )
                is_stale = any(
                    snap.stale.get(k, False) for k in keys_chk if k in snap.stale
                )
                if not_warm or is_stale:
                    d.suppressed_not_ready += 1
                    continue

            regime = _lookup_regime_shadow(snap.symbol, reg.gate, rc)
            bindings = HorizonSignalEngine._build_bindings(snap, regime, sc)

            try:
                on = reg.gate.evaluate(symbol=snap.symbol, bindings=bindings)
            except UnknownIdentifierError:
                reg.gate.reset(snap.symbol)
                d.gate_unknown_id += 1
                continue
            except RegimeGateError:
                d.gate_other_error += 1
                continue

            if not on:
                d.gate_off += 1
                continue

            try:
                raw = reg.signal.evaluate(snap, regime, reg.params)
            except Exception:
                d.evaluate_exception += 1
                continue

            if raw is None:
                d.evaluate_none += 1
                continue
            if raw.direction == SignalDirection.FLAT:
                d.evaluate_flat += 1
                continue
            d.signal_non_flat += 1

    print("\n── Offline replay (gate + evaluate), chronological ──")
    for alpha_id in sorted(per_alpha.keys()):
        d = per_alpha[alpha_id]
        print(f"\n  alpha_id={alpha_id}")
        print(f"    boundaries_seen (matching horizon):     {d.boundaries_seen:,}")
        print(f"    suppressed (cold/stale snapshot):       {d.suppressed_not_ready:,}")
        print(f"    gate UnknownIdentifierError:             {d.gate_unknown_id:,}")
        print(f"    gate other RegimeGateError:               {d.gate_other_error:,}")
        print(f"    gate OFF (after hysteresis):              {d.gate_off:,}")
        print(f"    evaluate -> None:                         {d.evaluate_none:,}")
        print(f"    evaluate -> FLAT:                         {d.evaluate_flat:,}")
        print(f"    evaluate raised:                          {d.evaluate_exception:,}")
        print(f"    evaluate -> directional Signal:           {d.signal_non_flat:,}")

    # Sample one boundary for manual inspection (latest snapshot with most keys).
    if rows:
        best = max(rows, key=lambda r: len(r["snapshot"].values))
        s: HorizonFeatureSnapshot = best["snapshot"]  # type: ignore[assignment]
        scs: dict[tuple[str, str], float] = best["sensor_cache"]  # type: ignore[assignment]
        sym_keys = {k[1] for k in scs if k[0] == s.symbol}
        print("\n── Sample snapshot (most feature keys) ──")
        print(f"  symbol={s.symbol} horizon={s.horizon_seconds} boundary={s.boundary_index}")
        print(f"  warm keys: {sorted(s.warm.keys())}")
        print(f"  stale: {s.stale}")
        print(f"  values keys ({len(s.values)}): {sorted(s.values.keys())}")
        print(f"  shadow sensor ids for symbol ({len(sym_keys)}): {sorted(sym_keys)}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
