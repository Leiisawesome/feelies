"""Shared config and argparse helpers for ``scripts/run_backtest.py``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from feelies.core.inv12_stress import apply_inv12_stress
from feelies.core.platform_config import PlatformConfig


class ConfigNotFoundError(FileNotFoundError):
    """Raised when a platform YAML path does not exist."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(str(path))


def load_platform_config(path: Path | str) -> PlatformConfig:
    """Load ``PlatformConfig`` from YAML; raise if the path is missing."""
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigNotFoundError(config_path)
    return PlatformConfig.from_yaml(config_path)


def _reference_event_calendar_for_date(
    session_date: str,
    hint: Path | None,
) -> Path | None:
    """Resolve ``event_calendar/YYYY-MM-DD.yaml`` when a reference file exists."""
    candidates: list[Path] = []
    if hint is not None:
        candidates.append(hint.parent / f"{session_date}.yaml")
    candidates.append(
        Path("src/feelies/storage/reference/event_calendar") / f"{session_date}.yaml",
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def apply_backtest_session_dates_from_cli(
    config: PlatformConfig,
    *,
    start_date: str | None,
    end_date: str | None = None,
) -> PlatformConfig:
    """Align RTH/MOC session bounds (and calendar path) with a single-day CLI run.

    When ``start_date == end_date``, set ``rth_session_date`` and
    ``moc_session_date`` so BT-16 gating matches the replayed tape instead of
    a stale ``event_calendar_path`` filename (e.g. platform.yaml pinned to
    ``2026-03-26.yaml`` while ``--date 2026-04-02``).  Multi-day ranges are
    left unchanged — per-day RTH rebinding is not implemented yet.
    """
    if start_date is None:
        return config
    end = end_date or start_date
    if start_date != end:
        return config
    cal_path = _reference_event_calendar_for_date(
        start_date, config.event_calendar_path,
    )
    if cal_path is not None:
        return replace(
            config,
            rth_session_date=start_date,
            moc_session_date=start_date,
            event_calendar_path=cal_path,
        )
    return replace(
        config,
        rth_session_date=start_date,
        moc_session_date=start_date,
    )


def apply_backtest_cli_overrides(
    config: PlatformConfig,
    *,
    inv12_stress: bool = False,
    stress_cost: float = 1.0,
    symbols: Sequence[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> PlatformConfig:
    """Apply Inv-12 stress, cost multiplier, symbol, and session-date CLI overrides."""
    if inv12_stress:
        config = apply_inv12_stress(config)
    elif stress_cost != 1.0:
        config = replace(config, cost_stress_multiplier=stress_cost)
    if symbols:
        config = replace(config, symbols=frozenset(s.upper() for s in symbols))
    return apply_backtest_session_dates_from_cli(
        config, start_date=start_date, end_date=end_date,
    )


def resolve_backtest_symbols(config: PlatformConfig) -> list[str]:
    """Return sorted universe symbols (may be empty)."""
    return sorted(config.symbols)


def add_common_backtest_arguments(parser: argparse.ArgumentParser) -> None:
    """Register CLI flags shared by API and cache-replay backtest entry points."""
    parser.add_argument(
        "--symbol",
        type=str,
        nargs="+",
        default=None,
        help="Trading symbol(s), space-separated (default: from platform.yaml)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD (default: same as --date)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="platform.yaml",
        help="Path to platform.yaml (default: platform.yaml)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="Disk cache directory (default: ~/.feelies/cache/)",
    )
    parser.add_argument(
        "--stress-cost",
        type=float,
        default=1.0,
        metavar="MULT",
        help="Cost stress multiplier (e.g. 1.5 = 50%% higher fees, default: 1.0)",
    )
    parser.add_argument(
        "--inv12-stress",
        action="store_true",
        help=(
            "Apply Inv-12 joint stress: 1.5× cost_stress_multiplier and "
            "2× backtest_fill_latency_ns (BT-9). Supersedes --stress-cost."
        ),
    )
    parser.add_argument(
        "--trace-signal-orders",
        action="store_true",
        help=(
            "After the run, print a diagnostic table for standalone SIGNAL "
            "→ order handling."
        ),
    )


def add_backtest_api_arguments(parser: argparse.ArgumentParser) -> None:
    """Register flags for the Massive API backtest entry point."""
    add_common_backtest_arguments(parser)
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (required)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-download, skip disk cache",
    )
    parser.add_argument(
        "--emit-fills-jsonl",
        action="store_true",
        help="Emit one FILLED OrderAck JSON object per line (prefix FILL_JSONL).",
    )
    parser.add_argument(
        "--emit-net-divergence-jsonl",
        action="store_true",
        help=(
            "G-5 measurement: run the cross-alpha net shadow and emit one "
            "NetDivergence JSON object per divergent decision (prefix "
            "NETDIV_JSONL).  Parity-neutral (shadow-only); meaningful only "
            "with a multi-alpha config."
        ),
    )
    parser.add_argument(
        "--emit-size-divergence-jsonl",
        action="store_true",
        help=(
            "G-7 measurement: run the edge/vol/inventory size shadow and emit "
            "one SizeDivergence JSON object per sized signal whose tilted "
            "target differs from the base target (prefix SIZEDIV_JSONL).  "
            "Parity-neutral (shadow-only); meaningful only when at least one "
            "sizer tilt factor is enabled in config."
        ),
    )
    parser.add_argument(
        "--emit-sensor-readings-jsonl",
        action="store_true",
        help="Emit SensorReading rows (prefix SENSOR_JSONL).",
    )
    parser.add_argument(
        "--emit-horizon-ticks-jsonl",
        action="store_true",
        help="Emit HorizonTick rows (prefix HTICK_JSONL).",
    )
    parser.add_argument(
        "--emit-snapshots-jsonl",
        action="store_true",
        help="Emit HorizonFeatureSnapshot rows (prefix SNAP_JSONL).",
    )
    parser.add_argument(
        "--emit-signals-jsonl",
        action="store_true",
        help="Emit Signal rows (prefix SIGNAL_JSONL).",
    )
    parser.add_argument(
        "--emit-hazard-spikes-jsonl",
        action="store_true",
        help="Emit RegimeHazardSpike rows (prefix HAZARD_JSONL).",
    )
    parser.add_argument(
        "--emit-cross-sectional-jsonl",
        action="store_true",
        help="Emit CrossSectionalContext rows (prefix XSECT_JSONL).",
    )
    parser.add_argument(
        "--emit-sized-intents-jsonl",
        action="store_true",
        help="Emit SizedPositionIntent rows (prefix INTENT_JSONL).",
    )
    parser.add_argument(
        "--emit-hazard-exits-jsonl",
        action="store_true",
        help="Emit hazard exit OrderRequest rows (prefix HAZARD_EXIT_JSONL).",
    )


def disable_backtest_jsonl_emit_flags(args: argparse.Namespace) -> None:
    """Default all JSONL emit hooks off (cache-replay entry point)."""
    args.emit_fills_jsonl = False
    args.emit_sensor_readings_jsonl = False
    args.emit_horizon_ticks_jsonl = False
    args.emit_snapshots_jsonl = False
    args.emit_signals_jsonl = False
    args.emit_hazard_spikes_jsonl = False
    args.emit_cross_sectional_jsonl = False
    args.emit_sized_intents_jsonl = False
    args.emit_hazard_exits_jsonl = False
