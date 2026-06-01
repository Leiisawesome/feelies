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


def apply_backtest_cli_overrides(
    config: PlatformConfig,
    *,
    inv12_stress: bool = False,
    stress_cost: float = 1.0,
    symbols: Sequence[str] | None = None,
) -> PlatformConfig:
    """Apply Inv-12 stress, cost multiplier, and symbol CLI overrides."""
    if inv12_stress:
        config = apply_inv12_stress(config)
    elif stress_cost != 1.0:
        config = replace(config, cost_stress_multiplier=stress_cost)
    if symbols:
        config = replace(config, symbols=frozenset(s.upper() for s in symbols))
    return config


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
