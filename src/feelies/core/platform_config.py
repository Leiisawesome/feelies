"""Concrete Configuration implementation for the trading platform.

Provides a YAML-loadable, validatable configuration that satisfies
the ``Configuration`` protocol.  Carries all settings needed by the
bootstrap layer to compose the system: trading universe, alpha spec
paths, operating mode, regime engine selection, and parameter
overrides.

Invariants preserved:
  - Inv 13 (provenance): every config is versioned, authored, and
    snapshotable with a SHA-256 checksum.
  - Inv 5 (deterministic replay): snapshot + event log → identical
    output.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingModuleSource]

from feelies.core.config import ConfigSnapshot
from feelies.core.errors import ConfigurationError


class OperatingMode(Enum):
    BACKTEST = auto()
    PAPER = auto()
    LIVE = auto()


@dataclass(kw_only=True)
class PlatformConfig:
    """Concrete configuration for the trading platform.

    Satisfies the ``Configuration`` protocol.  Can be constructed
    directly or loaded from a YAML file via ``PlatformConfig.from_yaml()``.
    """

    version: str = "0.1.0"
    author: str = "system"
    symbols: frozenset[str] = frozenset()
    mode: OperatingMode = OperatingMode.BACKTEST

    alpha_spec_dir: Path | None = None
    alpha_specs: list[Path] = field(default_factory=list)
    parameter_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)

    regime_engine: str | None = "hmm_3state_fractional"

    data_dir: Path | None = None
    event_log_path: Path | None = None

    risk_max_position_per_symbol: int = 1000
    risk_max_gross_exposure_pct: float = 20.0
    risk_max_drawdown_pct: float = 5.0

    account_equity: float = 1_000_000.0
    backtest_fill_latency_ns: int = 0
    signal_entry_cooldown_ticks: int = 0

    stop_loss_per_share: float = 0.0
    trail_activate_per_share: float = 0.0
    trail_pct: float = 0.5

    cost_min_spread_bps: float = 0.0
    cost_commission_per_share: float = 0.0035
    cost_exchange_per_share: float = 0.0005
    cost_min_commission: float = 0.35
    cost_max_commission_pct: float = 1.0

    # Execution mode: "market" (immediate mid-price fill, spread cost charged)
    # or "passive_limit" (limit orders at BBO, queue-position fill model).
    execution_mode: str = "market"
    # Ticks at our level before queue-drain fill triggers.
    passive_fill_delay_ticks: int = 3
    # Cancel unfilled resting orders after this many ticks.
    passive_max_resting_ticks: int = 50
    # Maker rebate per share (IB Tiered US equity adding liquidity).
    passive_rebate_per_share: float = 0.002

    cache_dir: Path | None = None

    def validate(self) -> None:
        if not self.symbols:
            raise ConfigurationError("symbols must be non-empty")

        if self.alpha_spec_dir is not None and not self.alpha_spec_dir.is_dir():
            raise ConfigurationError(
                f"alpha_spec_dir does not exist: {self.alpha_spec_dir}"
            )

        if not self.alpha_spec_dir and not self.alpha_specs:
            raise ConfigurationError(
                "at least one of alpha_spec_dir or alpha_specs must be provided"
            )

        if self.risk_max_position_per_symbol <= 0:
            raise ConfigurationError("risk_max_position_per_symbol must be positive")
        if self.risk_max_gross_exposure_pct <= 0:
            raise ConfigurationError("risk_max_gross_exposure_pct must be positive")
        if self.risk_max_drawdown_pct <= 0:
            raise ConfigurationError("risk_max_drawdown_pct must be positive")
        if self.account_equity <= 0:
            raise ConfigurationError("account_equity must be positive")

        valid_modes = ("market", "passive_limit")
        if self.execution_mode not in valid_modes:
            raise ConfigurationError(
                f"execution_mode must be one of {valid_modes}, "
                f"got '{self.execution_mode}'"
            )

    def snapshot(self) -> ConfigSnapshot:
        data = self._to_dict()
        raw = json.dumps(data, sort_keys=True, default=str)
        checksum = hashlib.sha256(raw.encode()).hexdigest()
        return ConfigSnapshot(
            version=self.version,
            timestamp_ns=time.time_ns(),
            author=self.author,
            data=data,
            checksum=checksum,
        )

    def _to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "author": self.author,
            "symbols": sorted(self.symbols),
            "mode": self.mode.name,
            "alpha_spec_dir": str(self.alpha_spec_dir) if self.alpha_spec_dir else None,
            "alpha_specs": [str(p) for p in self.alpha_specs],
            "parameter_overrides": self.parameter_overrides,
            "regime_engine": self.regime_engine,
            "data_dir": str(self.data_dir) if self.data_dir else None,
            "event_log_path": str(self.event_log_path) if self.event_log_path else None,
            "risk_max_position_per_symbol": self.risk_max_position_per_symbol,
            "risk_max_gross_exposure_pct": self.risk_max_gross_exposure_pct,
            "risk_max_drawdown_pct": self.risk_max_drawdown_pct,
            "account_equity": self.account_equity,
            "backtest_fill_latency_ns": self.backtest_fill_latency_ns,
            "signal_entry_cooldown_ticks": self.signal_entry_cooldown_ticks,
            "stop_loss_per_share": self.stop_loss_per_share,
            "trail_activate_per_share": self.trail_activate_per_share,
            "trail_pct": self.trail_pct,
            "cost_min_spread_bps": self.cost_min_spread_bps,
            "cost_commission_per_share": self.cost_commission_per_share,
            "cost_exchange_per_share": self.cost_exchange_per_share,
            "cost_min_commission": self.cost_min_commission,
            "cost_max_commission_pct": self.cost_max_commission_pct,
            "execution_mode": self.execution_mode,
            "passive_fill_delay_ticks": self.passive_fill_delay_ticks,
            "passive_max_resting_ticks": self.passive_max_resting_ticks,
            "passive_rebate_per_share": self.passive_rebate_per_share,
        }

    @classmethod
    def from_yaml(cls, path: str | Path) -> PlatformConfig:
        """Load configuration from a YAML file.

        Raises ``ConfigurationError`` if the file is unreadable or
        contains invalid structure.
        """
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
            data = yaml.safe_load(raw)
        except Exception as exc:
            raise ConfigurationError(f"Failed to read config {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigurationError(f"{path}: root must be a YAML mapping")

        symbols_raw = data.get("symbols", [])
        symbols = frozenset(symbols_raw) if symbols_raw else frozenset()

        mode_str = data.get("mode", "BACKTEST").upper()
        try:
            mode = OperatingMode[mode_str]
        except KeyError:
            raise ConfigurationError(
                f"Unknown mode '{mode_str}'. Valid: {[m.name for m in OperatingMode]}"
            )

        alpha_spec_dir_raw = data.get("alpha_spec_dir")
        alpha_spec_dir = Path(alpha_spec_dir_raw) if alpha_spec_dir_raw else None

        alpha_specs_raw = data.get("alpha_specs", [])
        alpha_specs = [Path(p) for p in alpha_specs_raw]

        data_dir_raw = data.get("data_dir")
        event_log_raw = data.get("event_log_path")
        cache_dir_raw = data.get("cache_dir")

        return cls(
            version=str(data.get("version", "0.1.0")),
            author=str(data.get("author", "system")),
            symbols=symbols,
            mode=mode,
            alpha_spec_dir=alpha_spec_dir,
            alpha_specs=alpha_specs,
            parameter_overrides=data.get("parameter_overrides", {}),
            regime_engine=data.get("regime_engine", "hmm_3state_fractional"),
            data_dir=Path(data_dir_raw) if data_dir_raw else None,
            event_log_path=Path(event_log_raw) if event_log_raw else None,
            risk_max_position_per_symbol=int(
                data.get("risk_max_position_per_symbol", 1000)
            ),
            risk_max_gross_exposure_pct=float(
                data.get("risk_max_gross_exposure_pct", 20.0)
            ),
            risk_max_drawdown_pct=float(
                data.get("risk_max_drawdown_pct", 5.0)
            ),
            account_equity=float(data.get("account_equity", 1_000_000.0)),
            backtest_fill_latency_ns=int(
                data.get("backtest_fill_latency_ns", 0)
            ),
            signal_entry_cooldown_ticks=int(
                data.get("signal_entry_cooldown_ticks", 0)
            ),
            stop_loss_per_share=float(
                data.get("stop_loss_per_share", 0.0)
            ),
            trail_activate_per_share=float(
                data.get("trail_activate_per_share", 0.0)
            ),
            trail_pct=float(
                data.get("trail_pct", 0.5)
            ),
            cost_min_spread_bps=float(
                data.get("cost_min_spread_bps", 0.0)
            ),
            cost_commission_per_share=float(
                data.get("cost_commission_per_share", 0.0035)
            ),
            cost_exchange_per_share=float(
                data.get("cost_exchange_per_share", 0.0005)
            ),
            cost_min_commission=float(
                data.get("cost_min_commission", 0.35)
            ),
            cost_max_commission_pct=float(
                data.get("cost_max_commission_pct", 1.0)
            ),
            execution_mode=str(data.get("execution_mode", "market")),
            passive_fill_delay_ticks=int(
                data.get("passive_fill_delay_ticks", 3)
            ),
            passive_max_resting_ticks=int(
                data.get("passive_max_resting_ticks", 50)
            ),
            passive_rebate_per_share=float(
                data.get("passive_rebate_per_share", 0.002)
            ),
            cache_dir=Path(cache_dir_raw) if cache_dir_raw else None,
        )
