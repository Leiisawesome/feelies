"""YAML-backed health thresholds and category weights."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from feelies.core.errors import ConfigurationError


@dataclass(frozen=True, kw_only=True)
class HealthConfig:
    """Thresholds and weights for :mod:`feelies.health`.

    All fields have conservative defaults; missing YAML keys fall back to these.
    """

    # Metadata / definition
    metadata_required_fields: tuple[str, ...] = (
        "alpha_name",
        "universe",
        "timeframe",
        "execution_assumption",
        "cost_assumption",
        "prediction_horizon",
    )

    # Predictive power
    min_observations: int = 1000
    min_trading_days: int = 20
    min_abs_ic: float = 0.005
    min_ic_t_stat: float = 2.0
    min_monotonicity_score: float = 0.6
    min_signal_coverage: float = 0.70
    sharpe_annualization_factor: float = 252.0

    # Cost / execution
    min_net_pnl: float = 0.0
    min_net_sharpe: float = 0.5
    min_gross_edge_to_cost_ratio: float = 1.5
    warn_gross_edge_to_cost_ratio: float = 2.0
    max_cost_share_of_gross_edge: float = 0.67

    # Regime robustness
    max_single_regime_pnl_contribution: float = 0.60
    min_regime_sample_size: int = 100
    max_losing_common_regime_fraction: float = 0.50

    # Robustness / overfit
    min_profitable_neighbor_fraction: float = 0.50
    max_best_to_median_sharpe_ratio: float = 3.0
    max_oos_sharpe_degradation: float = 0.50

    # Risk / drawdown
    max_drawdown_fraction_of_total_profit: float = 0.50
    max_single_day_loss_fraction_of_total_profit: float = 0.25
    max_single_day_profit_contribution: float = 0.30
    max_single_symbol_pnl_contribution: float = 0.30

    # Capacity
    max_participation_rate_liquid: float = 0.01
    max_participation_rate_illiquid: float = 0.0025
    max_order_size_fraction_of_top_of_book: float = 0.25

    # Portfolio fit
    max_corr_to_existing_alpha: float = 0.70
    min_marginal_sharpe_improvement: float = 0.05

    # Data quality
    max_missing_data_rate: float = 0.05

    # Category weights (must sum to 1.0 for applicable categories in defaults)
    category_weights: dict[str, float] = field(
        default_factory=lambda: {
            "metadata_definition": 0.10,
            "data_integrity_causality": 0.15,
            "raw_predictive_power": 0.15,
            "cost_execution_survival": 0.15,
            "regime_robustness": 0.10,
            "robustness_overfit": 0.10,
            "risk_drawdown": 0.10,
            "capacity_liquidity": 0.05,
            "portfolio_fit": 0.05,
            "production_readiness": 0.05,
        }
    )

    config_loaded_from: str | None = None
    config_missing_warned: bool = False


_COERCIONS: dict[str, type] = {
    "min_observations": int,
    "min_trading_days": int,
    "min_abs_ic": float,
    "min_ic_t_stat": float,
    "min_monotonicity_score": float,
    "min_signal_coverage": float,
    "sharpe_annualization_factor": float,
    "min_net_pnl": float,
    "min_net_sharpe": float,
    "min_gross_edge_to_cost_ratio": float,
    "warn_gross_edge_to_cost_ratio": float,
    "max_cost_share_of_gross_edge": float,
    "max_single_regime_pnl_contribution": float,
    "min_regime_sample_size": int,
    "max_losing_common_regime_fraction": float,
    "min_profitable_neighbor_fraction": float,
    "max_best_to_median_sharpe_ratio": float,
    "max_oos_sharpe_degradation": float,
    "max_drawdown_fraction_of_total_profit": float,
    "max_single_day_loss_fraction_of_total_profit": float,
    "max_single_day_profit_contribution": float,
    "max_single_symbol_pnl_contribution": float,
    "max_participation_rate_liquid": float,
    "max_participation_rate_illiquid": float,
    "max_order_size_fraction_of_top_of_book": float,
    "max_corr_to_existing_alpha": float,
    "min_marginal_sharpe_improvement": float,
    "max_missing_data_rate": float,
}


def _merge_mapping(base: HealthConfig, raw: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for f in HealthConfig.__dataclass_fields__:
        if f in ("config_loaded_from", "config_missing_warned"):
            continue
        out[f] = getattr(base, f)
    for key, val in raw.items():
        if key == "category_weights" and isinstance(val, Mapping):
            merged = dict(out["category_weights"])
            merged.update({str(k): float(v) for k, v in val.items()})
            out["category_weights"] = merged
        elif key == "metadata_required_fields" and isinstance(val, (list, tuple)):
            out["metadata_required_fields"] = tuple(str(x) for x in val)
        elif key in _COERCIONS and val is not None:
            cast = _COERCIONS[key]
            out[key] = cast(val)
        elif key in out:
            out[key] = val
    return out


def load_health_config(path: Path | None) -> HealthConfig:
    """Load YAML health config; fall back to defaults with ``config_missing_warned``."""

    base = HealthConfig()
    if path is None or not path.is_file():
        return HealthConfig(config_missing_warned=True)
    try:
        raw_txt = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"Cannot read health config {path}: {exc}") from exc
    try:
        loaded = yaml.safe_load(raw_txt)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Malformed YAML in {path}: {exc}") from exc
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, Mapping):
        raise ConfigurationError(f"Health config root must be a mapping: {path}")
    merged = _merge_mapping(base, loaded)
    return HealthConfig(
        **merged,
        config_loaded_from=str(path.resolve()),
        config_missing_warned=False,
    )


__all__ = ["HealthConfig", "load_health_config"]
