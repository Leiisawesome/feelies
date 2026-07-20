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

import copy
import hashlib
import importlib
import logging
import json
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any


from feelies.core.clock import WallClock
from feelies.core.config import ConfigSnapshot
from feelies.core.errors import ConfigurationError
from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.spec import SensorSpec

# Conservative defaults until measured broker and feed latency is available.
DEFAULT_BACKTEST_FILL_LATENCY_NS: int = 50_000_000  # 50 ms order-submission leg
DEFAULT_MARKET_DATA_LATENCY_NS: int = 20_000_000  # 20 ms feed-propagation leg


def latency_stress_ns(
    fill_latency_ns: int,
    market_data_latency_ns: int,
    *,
    multiplier: int = 2,
) -> tuple[int, int]:
    """Scale both latency legs for invariant-12 stress."""
    return fill_latency_ns * multiplier, market_data_latency_ns * multiplier


logger = logging.getLogger(__name__)


class OperatingMode(Enum):
    BACKTEST = auto()
    PAPER = auto()
    LIVE = auto()


@dataclass(frozen=True, kw_only=True)
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
    # Optional kwargs forwarded to ``get_regime_engine(..., **options)`` at
    # bootstrap (e.g. ``transition_time_scaling_enabled: true``).
    regime_engine_options: dict[str, object] = field(default_factory=dict)
    data_dir: Path | None = None
    event_log_path: Path | None = None

    risk_max_position_per_symbol: int = 1000
    risk_max_gross_exposure_pct: float = 20.0
    risk_max_drawdown_pct: float = 5.0

    # Position-limit scales for the built-in HMM states.
    risk_regime_vol_breakout_scale: float = 0.5
    risk_regime_compression_scale: float = 0.75
    risk_regime_normal_scale: float = 1.0

    # Require every cached replay manifest to report HEALTHY ingestion.
    require_healthy_disk_cache_manifests: bool = False
    disk_cache_ingestion_health_rows: tuple[tuple[str, str, str], ...] = ()
    # Treat a detected gap like corruption and stop processing that symbol.
    degrade_on_data_gap: bool = True
    # Warn about unhealthy cache rows when strict manifest checks are disabled.
    warn_on_unhealthy_disk_cache: bool = True
    # Worst DataHealth state observed per symbol during ingest or cache loading.
    ingest_terminal_symbol_health: tuple[tuple[str, str], ...] = ()
    # Require a terminal HEALTHY state for every backtest symbol.
    backtest_enforce_ingest_terminal_health: bool = False
    # BACKTEST ingest path: refuse runs with zero events when True.
    backtest_reject_zero_ingest_events: bool = False
    # Require every universe symbol to appear in the normalizer health map.
    strict_normalizer_symbol_coverage: bool = False
    # Enable only for full-tick REST data; ordinary REST rows have sequence gaps.
    enable_rest_sequence_gap_detection: bool = False

    # Trade condition codes that start and end a regulatory halt. Entries remain
    # blocked during the post-resume blackout; exits remain allowed.
    halt_on_condition_codes: tuple[int, ...] = ()
    halt_off_condition_codes: tuple[int, ...] = ()
    halt_resolution_blackout_seconds: int = 60

    # Daily and intraday SSR inputs. Once active, SSR remains set for the session.
    ssr_active_symbols: tuple[str, ...] = ()
    ssr_trigger_condition_codes: tuple[int, ...] = ()
    ssr_mode: str = "refuse_short"

    # Per-symbol locate tier: available, hard, or unavailable.
    borrow_availability: dict[str, str] = field(default_factory=dict)

    # MOC and closing-auction fill modeling.
    moc_strategy_ids: tuple[str, ...] = ("sig_moc_imbalance_v1",)
    moc_session_date: str | None = None
    moc_cutoff_et: str = "15:50"
    official_close_et: str = "16:00"
    early_close_dates: tuple[str, ...] = ()
    early_close_moc_cutoff_et: str = "12:50"
    early_close_official_close_et: str = "13:00"

    # RTH gating uses 09:30–16:00 ET, or 13:00 on early-close days.
    rth_session_gating_enabled: bool = True
    rth_session_date: str | None = None
    rth_open_et: str = "09:30"
    rth_close_et: str = "16:00"
    early_close_rth_close_et: str = "13:00"
    market_holiday_dates: tuple[str, ...] = ()
    no_entry_first_seconds: int = 0

    # Deployed capital in the supported account bracket.
    account_equity: float = 50_000.0
    # Order-submission latency before exchange-time fill eligibility.
    backtest_fill_latency_ns: int = DEFAULT_BACKTEST_FILL_LATENCY_NS
    # Feed delay before quotes and trades reach the pipeline.
    market_data_latency_ns: int = DEFAULT_MARKET_DATA_LATENCY_NS

    # Only margin_25k is supported; bootstrap rejects other account types.
    account_type: str = "margin_25k"
    account_id: str = "default"
    # Maintenance floor below which a PDT-flagged account is barred from
    # opening new day trades (entries suppressed, exits always permitted).
    pdt_min_equity_usd: float = 25_000.0

    # Reg-T buying-power multipliers for margin_25k accounts.
    risk_margin_intraday_buying_power_multiplier: float = 4.0
    risk_margin_overnight_buying_power_multiplier: float = 2.0

    stop_loss_per_share: float = 0.0
    trail_activate_per_share: float = 0.0
    trail_pct: float = 0.5
    # Percentage-based stops (fraction of entry price, e.g. 0.01 = 1%).
    # When non-zero, these override stop_loss_per_share / trail_activate_per_share.
    stop_loss_pct: float = 0.0
    trail_activate_pct: float = 0.0

    # Conservative IBKR retail defaults, including blended SmartRouter fees.
    cost_min_spread_bps: float = 0.3
    cost_commission_per_share: float = 0.0035
    cost_exchange_per_share: float = 0.0005  # Deprecated: use taker/maker fields.
    cost_taker_exchange_per_share: float = 0.003
    cost_maker_exchange_per_share: float = 0.0
    # Through-fills are more adverse than queue-drain fills.
    cost_passive_adverse_selection_bps: float = 2.0
    cost_through_fill_adverse_selection_bps: float = 5.0
    # Compatibility aliases; new configs should use the fields above.
    cost_adverse_selection_through_bps: float = 5.0
    cost_adverse_selection_drain_bps: float = 2.0
    cost_sell_regulatory_bps: float = 0.5
    cost_stress_multiplier: float = 1.0
    cost_min_commission: float = 0.35
    cost_max_commission_pct: float = 1.0
    # Cost-model fields exposed for operator overrides and complete snapshots.
    cost_finra_taf_per_share: float = 0.000166
    cost_finra_taf_max_per_order: float = 8.30
    cost_min_commission_applies_to_per_share_only: bool = True
    cost_spread_floor_taker_only: bool = True
    # Half-spreads charged to stop, hazard, and forced-exit fills.
    cost_stop_slippage_half_spreads: float = 2.0

    # Routing mode: always market, passive at the near BBO, or per-order minimum cost.
    execution_mode: str = "market"
    # Minimum-cost policy knobs (only consumed when
    # ``execution_mode == "minimum_cost"``; ignored otherwise).
    cost_min_passive_bias_bps: float = 0.0
    cost_min_small_order_threshold_shares: int = 0
    cost_min_half_spread_threshold: float = 0.0
    cost_min_allow_passive_short_entry: bool = True
    # Minimum-cost policy prices a passive non-fill as probability × edge.
    cost_min_passive_non_fill_probability: float = 0.30
    # Alert when realized fill cost exceeds disclosed cost by this ratio.
    realized_cost_alert_ratio: float = 1.5
    # Ticks at our level before a queue-drain fill in tick-based mode.
    passive_fill_delay_ticks: int = 3
    # Cancel unfilled resting orders after this many ticks.
    passive_max_resting_ticks: int = 50
    # Maker rebate per share — deprecated; maker fee now in cost model.
    passive_rebate_per_share: float = 0.002
    # Shares traded at our level before a queue-drain fill.
    # 0 = disabled, use tick-based fill_delay_ticks instead.
    passive_queue_position_shares: int = 0
    # Cap the per-tick seeded-Bernoulli level-fill hazard. This bounds
    # the residual queue-position uncertainty so no single quote tick is a
    # near-certain fill (1.0 = no cap, deterministic fill once at the front).
    passive_fill_hazard_max: float = 0.5
    # Cancel fee charged per share when a resting order times out (default 0).
    passive_cancel_fee_per_share: float = 0.0

    # Minimum order size gate: orders below this number of shares are suppressed.
    platform_min_order_shares: int = 1

    # Suppress orders whose calibrated edge does not cover this multiple of
    # modeled round-trip cost. A ratio of 0 disables the gate.
    signal_min_edge_cost_ratio: float = 1.0
    signal_edge_cost_basis: str = "round_trip"

    # Require reversal entry edge to cover combined exit and entry cost.
    reversal_min_edge_cost_multiplier: float = 1.5

    # The planner may drive live intents and trim same-direction positions.
    # trim_min_fraction suppresses small, churn-prone reductions.
    position_manager_drive: bool = True
    position_manager_enable_trim: bool = True
    position_manager_trim_min_fraction: float = 0.10
    # Suppress trims while forward edge clears this cost multiple; 0 disables.
    position_manager_trim_edge_gate_multiplier: float = 1.0
    # Post discretionary trims passively, then cross unfilled residuals at MARKET.
    position_manager_urgency_exec: bool = True

    # Block entries and flatten positions near the RTH close.
    session_flatten_enabled: bool = True
    session_flatten_seconds_before_close: int = 0

    # Net standing alpha targets instead of trading only the arbitrated winner.
    # Targets expire after net_staleness_k × their horizon.
    enable_portfolio_netting: bool = False
    net_staleness_k: float = 1.0

    # Optional edge, volatility, and inventory tilts multiply the base size.
    # sizer_tilt_drive applies them live; otherwise they remain shadow-only.
    sizer_tilt_drive: bool = False
    sizer_edge_weighting_enabled: bool = False
    sizer_edge_ref_bps: float = 20.0
    sizer_edge_floor: float = 0.25
    sizer_edge_cap: float = 2.0
    sizer_vol_targeting_enabled: bool = False
    sizer_vol_target_bps: float = 100.0
    sizer_vol_floor: float = 0.25
    sizer_vol_cap: float = 2.0
    sizer_inventory_penalty_enabled: bool = False
    sizer_inventory_floor: float = 0.0
    sizer_tilt_floor: float = 0.10
    sizer_tilt_cap: float = 3.0

    # Regime engine boot-time calibration (lookahead avoidance).  ``None``
    # skips feeding the trading event log into ``calibrate()`` entirely
    # (cold emission defaults + per-run warning).  A positive integer uses
    # only the first N NBBO quotes in replay sequence order as calibration
    # input — causal prefix, never the full session.
    regime_calibration_max_quotes: int | None = None

    # Disable regime gates when calibrated states are insufficiently distinct.
    # A floor of 0 disables this guard.
    regime_min_discriminability: float = 0.0

    # When True, bootstrap refuses to start if ``RegimeEngine.state_names``
    # contains any name missing from the risk engine's regime scale map
    # (fail-closed vs silent ``min(scale)`` fallback for unknown states).
    enforce_regime_state_scale_alignment: bool = False

    # 2d: market-impact factor for walk-the-book slippage on large orders.
    # Excess beyond L1 available depth is priced at
    #   fill_price ± impact_factor × (excess / depth) × half_spread.
    # Default 0.5 (half a spread per full-depth multiple of excess).
    cost_market_impact_factor: float = 0.5

    # Cap on the walk-the-book market-impact premium, expressed in multiples
    # of the half-spread.  Threaded into the backtest routers (which otherwise
    # default to 10).  Default 10.0 preserves prior router behaviour for
    # callers that do not set it; platform.yaml tightens this to 4.0 for an
    # L1-only retail book.
    cost_max_impact_half_spreads: float = 10.0

    # Annualized hard-to-borrow fee in basis points for short-side fills.
    # Applied as a daily cost (annual_bps / 252) on SELL fills flagged as_short.
    # Default 0 = disabled.  Set for short-selling strategies only.
    cost_htb_borrow_annual_bps: float = 0.0

    # Apply participation impact to the within-L1 portion; 0 disables it.
    cost_within_l1_impact_factor: float = 0.0
    # Add square-root permanent impact to taker fills; 0 disables it.
    cost_permanent_impact_coefficient: float = 0.0
    # Charge MOC fills for closing-auction imbalance; 0 disables it.
    cost_moc_penalty_bps: float = 0.0
    # Divide usable L1 depth for forced exits by this factor.
    cost_stop_depth_depletion_factor: float = 1.0
    # Cap passive through-fills at the crossing quote's opposite-side size.
    passive_through_fill_size_cap_enabled: bool = False
    # Require traded volume before a quote-imbalance drain fill.
    passive_require_trade_for_level_fill: bool = False
    # Default locate tier for symbols absent from borrow_availability.
    borrow_default_tier: str = "available"
    # Escalate risk after this many consecutive realized-cost overruns.
    realized_cost_escalation_enabled: bool = False
    realized_cost_escalation_streak: int = 3

    cache_dir: Path | None = None

    # Optional sensor and horizon scheduling configuration.
    # A missing session anchor binds the scheduler to its first event.
    session_open_ns: int | None = None
    horizons_seconds: frozenset[int] = field(
        default_factory=lambda: frozenset({30, 120, 300, 900, 1800})
    )
    sensor_specs: tuple[SensorSpec, ...] = ()
    # Register only sensors required by loaded SIGNAL alphas.
    prune_unused_sensors: bool = False
    event_calendar_path: Path | None = None
    # Split and dividend ex-date calendar for replay integrity (see
    # docs/data_adjustment_policy.md). None ⇒ ex-date guard is inert.
    ex_date_calendar_path: Path | None = None
    backtest_enforce_ex_date_guard: bool = True
    market_id: str = "US_EQUITY"
    session_kind: str = "RTH"

    # Require schema-1.1 SIGNAL and PORTFOLIO alphas to declare a complete
    # trend mechanism. Disable only for manifests that predate the taxonomy.
    enforce_trend_mechanism: bool = True

    # PORTFOLIO composition settings are inert unless a PORTFOLIO alpha is loaded.
    # ECOS alone uses the turnover and risk penalties; closed_form ignores them.
    # Gross and per-name caps shape desired weights before downstream risk checks.
    composition_completeness_threshold: float = 0.80
    factor_model: str = "FF5_momentum_STR"
    factor_loadings_refresh_seconds: int = 0
    factor_loadings_max_age_seconds: int = 7 * 24 * 3600
    factor_loadings_dir: Path | None = None
    sector_map_path: Path | None = None
    composition_lambda_tc: float = 1.0
    composition_lambda_risk: float = 0.1
    composition_max_universe_size: int = 50
    composition_gross_cap_pct: float = 2.0
    composition_per_name_cap_pct: float = 0.05
    # Drop stale feeder signals before computing portfolio completeness.
    # None uses the portfolio decision horizon as the age limit.
    composition_signal_max_age_seconds: int | None = None
    composition_optimizer_mode: str = "closed_form"
    enforce_layer_gates: bool = True

    # Enforce each alpha's risk_budget in addition to platform-wide caps.
    enforce_per_alpha_risk_budget: bool = True

    # Optional append-only lifecycle ledger. It is observational and must not
    # influence trading decisions; backtests do not write transitions.
    promotion_ledger_path: Path | None = None

    # ── PAPER/LIVE connections ───────────────────────────────────────
    # Defaults target a local IB paper account; LIVE must set port 4001.
    ib_host: str = "127.0.0.1"
    ib_port: int = 4002  # 4002 = paper, 4001 = live
    ib_client_id: int = 1
    massive_ws_url: str = "wss://socket.massive.com/stocks"

    # Gate thresholds resolve from defaults, then platform overrides, then alpha
    # overrides. Bootstrap validates keys and reports one configuration error.
    gate_thresholds_overrides: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.symbols:
            raise ConfigurationError("symbols must be non-empty")

        if self.alpha_spec_dir is not None and not self.alpha_spec_dir.is_dir():
            raise ConfigurationError(f"alpha_spec_dir does not exist: {self.alpha_spec_dir}")

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
        _valid_account_types = {"margin_25k", "margin_under_25k", "cash"}
        if self.account_type not in _valid_account_types:
            raise ConfigurationError(
                f"account_type must be one of {sorted(_valid_account_types)}, "
                f"got {self.account_type!r}"
            )
        if self.pdt_min_equity_usd <= 0:
            raise ConfigurationError("pdt_min_equity_usd must be positive")
        if self.backtest_fill_latency_ns < 0:
            raise ConfigurationError(
                f"backtest_fill_latency_ns must be non-negative, "
                f"got {self.backtest_fill_latency_ns}"
            )
        if self.market_data_latency_ns < 0:
            raise ConfigurationError(
                f"market_data_latency_ns must be non-negative, got {self.market_data_latency_ns}"
            )
        if self.halt_resolution_blackout_seconds < 0:
            raise ConfigurationError("halt_resolution_blackout_seconds must be non-negative")
        if set(self.halt_on_condition_codes) & set(self.halt_off_condition_codes):
            raise ConfigurationError(
                "halt_on_condition_codes and halt_off_condition_codes must be "
                "disjoint (a code cannot mean both halt and resume)"
            )
        if self.ssr_mode != "refuse_short":
            # Only the conservative refuse-short mode is supported.
            raise ConfigurationError(
                f"ssr_mode={self.ssr_mode!r} is not implemented; only "
                "'refuse_short' is supported (the uptick-routed variant is "
                "deferred)"
            )
        for sym, tier in self.borrow_availability.items():
            sym_u = str(sym).strip().upper()
            if not sym_u:
                raise ConfigurationError("borrow_availability keys must be non-empty symbols")
            label = str(tier).strip().lower()
            if label not in ("available", "hard", "unavailable"):
                raise ConfigurationError(
                    f"borrow_availability[{sym!r}]={tier!r} is invalid; "
                    "expected available, hard, or unavailable"
                )
        if str(self.borrow_default_tier).strip().lower() not in (
            "available",
            "hard",
            "unavailable",
        ):
            raise ConfigurationError(
                f"borrow_default_tier={self.borrow_default_tier!r} is invalid; "
                "expected available, hard, or unavailable"
            )

        if not isinstance(self.regime_engine_options, dict):
            raise ConfigurationError("regime_engine_options must be a dict[str, object] mapping")
        for opt_key in self.regime_engine_options:
            if not isinstance(opt_key, str):
                raise ConfigurationError(
                    f"regime_engine_options keys must be strings, got {type(opt_key).__name__}"
                )

        for scale_name, scale_val in (
            ("risk_regime_vol_breakout_scale", self.risk_regime_vol_breakout_scale),
            ("risk_regime_compression_scale", self.risk_regime_compression_scale),
            ("risk_regime_normal_scale", self.risk_regime_normal_scale),
        ):
            if not (0.0 < scale_val <= 2.0):
                raise ConfigurationError(f"{scale_name} must lie in (0, 2], got {scale_val}")

        if self.require_healthy_disk_cache_manifests:
            if not self.disk_cache_ingestion_health_rows:
                raise ConfigurationError(
                    "require_healthy_disk_cache_manifests=True requires "
                    "non-empty disk_cache_ingestion_health_rows "
                    "(populate after ingest / cache replay)"
                )
            for sym, day, health_status in self.disk_cache_ingestion_health_rows:
                if health_status != "HEALTHY":
                    raise ConfigurationError(
                        f"disk cache manifest not HEALTHY for {sym}/{day}: {health_status!r}"
                    )

        if self.backtest_enforce_ingest_terminal_health:
            if self.mode != OperatingMode.BACKTEST:
                raise ConfigurationError(
                    "backtest_enforce_ingest_terminal_health is only valid in BACKTEST mode",
                )
            if self.ingest_terminal_symbol_health:
                terminal_map = {k.upper(): v for k, v in self.ingest_terminal_symbol_health}
                for sym in self.symbols:
                    key = sym.upper()
                    state = terminal_map.get(key)
                    if state is None:
                        raise ConfigurationError(
                            "backtest_enforce_ingest_terminal_health: "
                            f"missing ingest_terminal_symbol_health row for {sym!r}",
                        )
                    if state != "HEALTHY":
                        raise ConfigurationError(
                            "backtest_enforce_ingest_terminal_health: "
                            f"symbol {sym!r} terminal health is {state!r}, expected HEALTHY",
                        )

        valid_modes = ("market", "passive_limit", "minimum_cost")
        if self.execution_mode not in valid_modes:
            raise ConfigurationError(
                f"execution_mode must be one of {valid_modes}, got '{self.execution_mode}'"
            )
        if self.cost_min_small_order_threshold_shares < 0:
            raise ConfigurationError("cost_min_small_order_threshold_shares must be >= 0")
        if self.cost_min_half_spread_threshold < 0.0:
            raise ConfigurationError("cost_min_half_spread_threshold must be >= 0")
        if self.cost_finra_taf_per_share < 0.0:
            raise ConfigurationError("cost_finra_taf_per_share must be >= 0")
        if self.cost_finra_taf_max_per_order < 0.0:
            raise ConfigurationError("cost_finra_taf_max_per_order must be >= 0")
        if self.cost_within_l1_impact_factor < 0.0:
            raise ConfigurationError("cost_within_l1_impact_factor must be >= 0")
        if self.cost_permanent_impact_coefficient < 0.0:
            raise ConfigurationError("cost_permanent_impact_coefficient must be >= 0")
        if self.cost_moc_penalty_bps < 0.0:
            raise ConfigurationError("cost_moc_penalty_bps must be >= 0")
        if self.cost_stop_depth_depletion_factor < 1.0:
            raise ConfigurationError("cost_stop_depth_depletion_factor must be >= 1")
        if self.realized_cost_escalation_streak < 1:
            raise ConfigurationError("realized_cost_escalation_streak must be >= 1")
        if self.cost_max_impact_half_spreads < 1.0:
            raise ConfigurationError(
                "cost_max_impact_half_spreads must be >= 1 "
                "(< 1 caps impact below one half-spread on excess legs)"
            )
        if not 0.0 <= self.cost_min_passive_non_fill_probability <= 1.0:
            raise ConfigurationError("cost_min_passive_non_fill_probability must be in [0, 1]")
        if self.realized_cost_alert_ratio < 1.0:
            raise ConfigurationError(
                "realized_cost_alert_ratio must be >= 1 (< 1 would fire on every realized cost)"
            )
        if self.cost_stop_slippage_half_spreads < 1.0:
            raise ConfigurationError("cost_stop_slippage_half_spreads must be >= 1")
        if self.signal_edge_cost_basis not in ("one_way", "round_trip"):
            raise ConfigurationError(
                f"signal_edge_cost_basis must be 'one_way' or "
                f"'round_trip', got {self.signal_edge_cost_basis!r}"
            )
        if self.signal_min_edge_cost_ratio < 0.0:
            raise ConfigurationError("signal_min_edge_cost_ratio must be >= 0")
        if self.reversal_min_edge_cost_multiplier < 0.0:
            raise ConfigurationError("reversal_min_edge_cost_multiplier must be >= 0")
        if not (0.0 <= self.position_manager_trim_min_fraction <= 1.0):
            raise ConfigurationError("position_manager_trim_min_fraction must be in [0, 1]")
        if self.position_manager_trim_edge_gate_multiplier < 0.0:
            raise ConfigurationError("position_manager_trim_edge_gate_multiplier must be >= 0")
        if self.session_flatten_seconds_before_close < 0:
            raise ConfigurationError("session_flatten_seconds_before_close must be >= 0")
        if self.net_staleness_k < 0.0:
            raise ConfigurationError("net_staleness_k must be >= 0")
        if self.sizer_edge_ref_bps <= 0.0:
            raise ConfigurationError("sizer_edge_ref_bps must be > 0")
        if self.sizer_vol_target_bps <= 0.0:
            raise ConfigurationError("sizer_vol_target_bps must be > 0")
        for _name, _lo, _hi in (
            ("sizer_edge", self.sizer_edge_floor, self.sizer_edge_cap),
            ("sizer_vol", self.sizer_vol_floor, self.sizer_vol_cap),
            ("sizer_tilt", self.sizer_tilt_floor, self.sizer_tilt_cap),
        ):
            if _lo < 0.0 or _hi < _lo:
                raise ConfigurationError(f"{_name}_floor/_cap must satisfy 0 <= floor <= cap")
        if not 0.0 <= self.sizer_inventory_floor <= 1.0:
            raise ConfigurationError("sizer_inventory_floor must be in [0, 1]")
        if self.cost_passive_adverse_selection_bps < 0.0:
            raise ConfigurationError("cost_passive_adverse_selection_bps must be >= 0")
        if self.cost_through_fill_adverse_selection_bps < 0.0:
            raise ConfigurationError("cost_through_fill_adverse_selection_bps must be >= 0")
        if self.cost_sell_regulatory_bps < 0.0:
            raise ConfigurationError("cost_sell_regulatory_bps must be >= 0")
        if self.cost_max_commission_pct <= 0.0:
            raise ConfigurationError("cost_max_commission_pct must be > 0")

        # Sensor and horizon validation.
        for h in self.horizons_seconds:
            if h <= 0:
                raise ConfigurationError(
                    f"horizons_seconds must contain positive integers, got {h}"
                )
        if self.session_open_ns is not None and self.session_open_ns < 0:
            raise ConfigurationError(
                f"session_open_ns must be non-negative or None, got {self.session_open_ns}"
            )
        if not self.market_id:
            raise ConfigurationError("market_id must be non-empty")
        if not self.session_kind:
            raise ConfigurationError("session_kind must be non-empty")

        if self.regime_calibration_max_quotes is not None:
            if self.regime_calibration_max_quotes < 1:
                raise ConfigurationError("regime_calibration_max_quotes must be >= 1 when set")

        if self.regime_min_discriminability < 0.0:
            raise ConfigurationError(
                "regime_min_discriminability must be >= 0.0 "
                f"(got {self.regime_min_discriminability})"
            )

        # Sensor specs: detect duplicate (sensor_id, sensor_version)
        # pairs early so registration-time errors at boot are reserved
        # for genuinely missing dependencies.
        seen: set[tuple[str, str]] = set()
        spec_ids: set[str] = set()
        for spec in self.sensor_specs:
            if spec.key in seen:
                raise ConfigurationError(
                    f"duplicate sensor spec: {spec.sensor_id!r} version {spec.sensor_version!r}"
                )
            seen.add(spec.key)
            spec_ids.add(spec.sensor_id)
        # Topological hint: every input_sensor_id must appear earlier
        # in the spec tuple than its consumer.
        seen_ids: set[str] = set()
        for spec in self.sensor_specs:
            for upstream in spec.input_sensor_ids:
                if upstream not in spec_ids:
                    raise ConfigurationError(
                        f"sensor {spec.sensor_id!r} declares unknown input sensor {upstream!r}"
                    )
                if upstream not in seen_ids:
                    raise ConfigurationError(
                        f"sensor {spec.sensor_id!r} depends on "
                        f"{upstream!r} which appears later in "
                        f"sensor_specs; reorder so producers precede "
                        f"consumers (topological order)"
                    )
            seen_ids.add(spec.sensor_id)

        if self.event_calendar_path is not None and not self.event_calendar_path.is_file():
            # Surface a missing boot-time calendar as a configuration error.
            raise ConfigurationError(
                f"event_calendar_path does not exist: {self.event_calendar_path}"
            )

        if self.ex_date_calendar_path is not None and not self.ex_date_calendar_path.is_file():
            raise ConfigurationError(
                f"ex_date_calendar_path does not exist: {self.ex_date_calendar_path}"
            )

        # Portfolio composition validation.
        if not 0.0 <= self.composition_completeness_threshold <= 1.0:
            raise ConfigurationError(
                f"composition_completeness_threshold must be in [0,1], "
                f"got {self.composition_completeness_threshold}"
            )
        if self.factor_loadings_refresh_seconds < 0:
            raise ConfigurationError("factor_loadings_refresh_seconds must be non-negative")
        if self.factor_loadings_max_age_seconds <= 0:
            raise ConfigurationError("factor_loadings_max_age_seconds must be positive")
        if self.composition_lambda_tc < 0.0:
            raise ConfigurationError("composition_lambda_tc must be non-negative")
        if self.composition_lambda_risk < 0.0:
            raise ConfigurationError("composition_lambda_risk must be non-negative")
        if self.composition_max_universe_size <= 0:
            raise ConfigurationError("composition_max_universe_size must be positive")
        if self.composition_gross_cap_pct <= 0.0:
            raise ConfigurationError("composition_gross_cap_pct must be positive")
        if not 0.0 < self.composition_per_name_cap_pct <= 1.0:
            raise ConfigurationError("composition_per_name_cap_pct must be in (0, 1]")
        if (
            self.composition_signal_max_age_seconds is not None
            and self.composition_signal_max_age_seconds <= 0
        ):
            raise ConfigurationError(
                "composition_signal_max_age_seconds must be positive when set"
            )
        if self.composition_optimizer_mode not in ("closed_form", "ecos"):
            raise ConfigurationError(
                "composition_optimizer_mode must be 'closed_form' or 'ecos', "
                f"got {self.composition_optimizer_mode!r}"
            )
        if self.factor_loadings_dir is not None and not self.factor_loadings_dir.is_dir():
            raise ConfigurationError(
                f"factor_loadings_dir does not exist: {self.factor_loadings_dir}"
            )
        if self.sector_map_path is not None and not self.sector_map_path.is_file():
            raise ConfigurationError(f"sector_map_path does not exist: {self.sector_map_path}")

    def snapshot(self, *, ts_ns: int | None = None) -> ConfigSnapshot:
        """Create an immutable provenance snapshot.

        ``ts_ns`` stamps the snapshot's wall-time provenance.  Pass a
        clock-derived value (``clock.now_ns()``) for a deterministic record
        — bootstrap does exactly this with the injected ``Clock`` so a
        backtest's snapshot is reproducible (Inv-10).  When omitted it falls
        back to the ``WallClock`` primitive rather than a raw ``time``
        read, keeping core free of direct wall-clock calls.  ``timestamp_ns``
        is never folded into ``checksum`` (see ``_to_dict``), so it cannot
        affect replay determinism (Inv-5) regardless of its source.
        """
        data = self._to_dict()
        raw = json.dumps(data, sort_keys=True, default=str)
        checksum = hashlib.sha256(raw.encode()).hexdigest()
        return ConfigSnapshot(
            version=self.version,
            timestamp_ns=ts_ns if ts_ns is not None else WallClock().now_ns(),
            author=self.author,
            data=data,
            checksum=checksum,
        )

    def _to_dict(self) -> dict[str, Any]:
        # Hash path basenames, not machine-specific absolute locations.
        return {
            "version": self.version,
            "author": self.author,
            "symbols": sorted(self.symbols),
            "mode": self.mode.name,
            "alpha_spec_dir": self.alpha_spec_dir.name if self.alpha_spec_dir else None,
            # Basename-only, like every other Path field above: two distinct
            # alpha_specs entries that share a basename across directories
            # collide in the checksum. Accepted tradeoff, not a bug — see the
            # Path-normalisation rationale above.
            "alpha_specs": sorted(p.name for p in self.alpha_specs),
            "parameter_overrides": copy.deepcopy(self.parameter_overrides),
            "regime_engine": self.regime_engine,
            "regime_engine_options": dict(self.regime_engine_options),
            "data_dir": self.data_dir.name if self.data_dir else None,
            "event_log_path": self.event_log_path.name if self.event_log_path else None,
            "risk_max_position_per_symbol": self.risk_max_position_per_symbol,
            "risk_max_gross_exposure_pct": self.risk_max_gross_exposure_pct,
            "risk_max_drawdown_pct": self.risk_max_drawdown_pct,
            "risk_regime_vol_breakout_scale": self.risk_regime_vol_breakout_scale,
            "risk_regime_compression_scale": self.risk_regime_compression_scale,
            "risk_regime_normal_scale": self.risk_regime_normal_scale,
            "require_healthy_disk_cache_manifests": (self.require_healthy_disk_cache_manifests),
            "disk_cache_ingestion_health_rows": list(
                self.disk_cache_ingestion_health_rows,
            ),
            "degrade_on_data_gap": self.degrade_on_data_gap,
            "warn_on_unhealthy_disk_cache": self.warn_on_unhealthy_disk_cache,
            "ingest_terminal_symbol_health": list(
                self.ingest_terminal_symbol_health,
            ),
            "backtest_enforce_ingest_terminal_health": (
                self.backtest_enforce_ingest_terminal_health
            ),
            "backtest_reject_zero_ingest_events": (self.backtest_reject_zero_ingest_events),
            "strict_normalizer_symbol_coverage": (self.strict_normalizer_symbol_coverage),
            "enable_rest_sequence_gap_detection": (self.enable_rest_sequence_gap_detection),
            "halt_on_condition_codes": list(self.halt_on_condition_codes),
            "halt_off_condition_codes": list(self.halt_off_condition_codes),
            "halt_resolution_blackout_seconds": (self.halt_resolution_blackout_seconds),
            "ssr_active_symbols": list(self.ssr_active_symbols),
            "ssr_trigger_condition_codes": list(self.ssr_trigger_condition_codes),
            "ssr_mode": self.ssr_mode,
            "borrow_availability": dict(self.borrow_availability),
            "moc_strategy_ids": list(self.moc_strategy_ids),
            "moc_session_date": self.moc_session_date,
            "moc_cutoff_et": self.moc_cutoff_et,
            "official_close_et": self.official_close_et,
            "early_close_dates": list(self.early_close_dates),
            "early_close_moc_cutoff_et": self.early_close_moc_cutoff_et,
            "early_close_official_close_et": self.early_close_official_close_et,
            "rth_session_gating_enabled": self.rth_session_gating_enabled,
            "rth_session_date": self.rth_session_date,
            "rth_open_et": self.rth_open_et,
            "rth_close_et": self.rth_close_et,
            "early_close_rth_close_et": self.early_close_rth_close_et,
            "market_holiday_dates": list(self.market_holiday_dates),
            "no_entry_first_seconds": self.no_entry_first_seconds,
            "account_equity": self.account_equity,
            "account_type": self.account_type,
            "account_id": self.account_id,
            "pdt_min_equity_usd": self.pdt_min_equity_usd,
            "risk_margin_intraday_buying_power_multiplier": (
                self.risk_margin_intraday_buying_power_multiplier
            ),
            "risk_margin_overnight_buying_power_multiplier": (
                self.risk_margin_overnight_buying_power_multiplier
            ),
            "backtest_fill_latency_ns": self.backtest_fill_latency_ns,
            "market_data_latency_ns": self.market_data_latency_ns,
            "stop_loss_per_share": self.stop_loss_per_share,
            "trail_activate_per_share": self.trail_activate_per_share,
            "trail_pct": self.trail_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "trail_activate_pct": self.trail_activate_pct,
            "cost_min_spread_bps": self.cost_min_spread_bps,
            "cost_commission_per_share": self.cost_commission_per_share,
            "cost_taker_exchange_per_share": self.cost_taker_exchange_per_share,
            "cost_maker_exchange_per_share": self.cost_maker_exchange_per_share,
            "cost_passive_adverse_selection_bps": (self.cost_passive_adverse_selection_bps),
            "cost_through_fill_adverse_selection_bps": (
                self.cost_through_fill_adverse_selection_bps
            ),
            "cost_adverse_selection_through_bps": (self.cost_adverse_selection_through_bps),
            "cost_adverse_selection_drain_bps": (self.cost_adverse_selection_drain_bps),
            "cost_sell_regulatory_bps": self.cost_sell_regulatory_bps,
            "cost_stress_multiplier": self.cost_stress_multiplier,
            "cost_min_commission": self.cost_min_commission,
            "cost_max_commission_pct": self.cost_max_commission_pct,
            "cost_finra_taf_per_share": self.cost_finra_taf_per_share,
            "cost_finra_taf_max_per_order": self.cost_finra_taf_max_per_order,
            "cost_min_commission_applies_to_per_share_only": (
                self.cost_min_commission_applies_to_per_share_only
            ),
            "cost_spread_floor_taker_only": self.cost_spread_floor_taker_only,
            "cost_stop_slippage_half_spreads": (self.cost_stop_slippage_half_spreads),
            "execution_mode": self.execution_mode,
            "cost_min_passive_bias_bps": self.cost_min_passive_bias_bps,
            "cost_min_small_order_threshold_shares": (self.cost_min_small_order_threshold_shares),
            "cost_min_half_spread_threshold": (self.cost_min_half_spread_threshold),
            "cost_min_allow_passive_short_entry": (self.cost_min_allow_passive_short_entry),
            "cost_min_passive_non_fill_probability": (self.cost_min_passive_non_fill_probability),
            "realized_cost_alert_ratio": self.realized_cost_alert_ratio,
            "passive_fill_delay_ticks": self.passive_fill_delay_ticks,
            "passive_max_resting_ticks": self.passive_max_resting_ticks,
            "passive_queue_position_shares": self.passive_queue_position_shares,
            "passive_fill_hazard_max": self.passive_fill_hazard_max,
            "passive_cancel_fee_per_share": self.passive_cancel_fee_per_share,
            "platform_min_order_shares": self.platform_min_order_shares,
            "signal_min_edge_cost_ratio": self.signal_min_edge_cost_ratio,
            "reversal_min_edge_cost_multiplier": (self.reversal_min_edge_cost_multiplier),
            "position_manager_drive": self.position_manager_drive,
            "position_manager_enable_trim": self.position_manager_enable_trim,
            "position_manager_trim_min_fraction": (self.position_manager_trim_min_fraction),
            "position_manager_trim_edge_gate_multiplier": (
                self.position_manager_trim_edge_gate_multiplier
            ),
            "position_manager_urgency_exec": (self.position_manager_urgency_exec),
            "session_flatten_enabled": self.session_flatten_enabled,
            "session_flatten_seconds_before_close": (self.session_flatten_seconds_before_close),
            "enable_portfolio_netting": self.enable_portfolio_netting,
            "net_staleness_k": self.net_staleness_k,
            "sizer_tilt_drive": self.sizer_tilt_drive,
            "sizer_edge_weighting_enabled": self.sizer_edge_weighting_enabled,
            "sizer_edge_ref_bps": self.sizer_edge_ref_bps,
            "sizer_edge_floor": self.sizer_edge_floor,
            "sizer_edge_cap": self.sizer_edge_cap,
            "sizer_vol_targeting_enabled": self.sizer_vol_targeting_enabled,
            "sizer_vol_target_bps": self.sizer_vol_target_bps,
            "sizer_vol_floor": self.sizer_vol_floor,
            "sizer_vol_cap": self.sizer_vol_cap,
            "sizer_inventory_penalty_enabled": (self.sizer_inventory_penalty_enabled),
            "sizer_inventory_floor": self.sizer_inventory_floor,
            "sizer_tilt_floor": self.sizer_tilt_floor,
            "sizer_tilt_cap": self.sizer_tilt_cap,
            "signal_edge_cost_basis": self.signal_edge_cost_basis,
            "regime_calibration_max_quotes": self.regime_calibration_max_quotes,
            "regime_min_discriminability": self.regime_min_discriminability,
            "enforce_regime_state_scale_alignment": (self.enforce_regime_state_scale_alignment),
            "cost_market_impact_factor": self.cost_market_impact_factor,
            "cost_max_impact_half_spreads": self.cost_max_impact_half_spreads,
            "cost_htb_borrow_annual_bps": self.cost_htb_borrow_annual_bps,
            "cost_within_l1_impact_factor": self.cost_within_l1_impact_factor,
            "cost_permanent_impact_coefficient": (self.cost_permanent_impact_coefficient),
            "cost_moc_penalty_bps": self.cost_moc_penalty_bps,
            "cost_stop_depth_depletion_factor": (self.cost_stop_depth_depletion_factor),
            "passive_through_fill_size_cap_enabled": (self.passive_through_fill_size_cap_enabled),
            "passive_require_trade_for_level_fill": (self.passive_require_trade_for_level_fill),
            "borrow_default_tier": self.borrow_default_tier,
            "realized_cost_escalation_enabled": (self.realized_cost_escalation_enabled),
            "realized_cost_escalation_streak": (self.realized_cost_escalation_streak),
            # Sensor settings participate in the deterministic checksum.
            "session_open_ns": self.session_open_ns,
            "horizons_seconds": sorted(self.horizons_seconds),
            "sensor_specs": [
                {
                    "sensor_id": s.sensor_id,
                    "sensor_version": s.sensor_version,
                    "cls": f"{s.cls.__module__}.{s.cls.__qualname__}",
                    "params": dict(s.params),
                    "subscribes_to": sorted(t.__name__ for t in s.subscribes_to),
                    "input_sensor_ids": list(s.input_sensor_ids),
                    "min_history": s.min_history,
                    "throttled_ms": s.throttled_ms,
                    "stateful": s.stateful,
                }
                for s in self.sensor_specs
            ],
            "prune_unused_sensors": self.prune_unused_sensors,
            "event_calendar_path": (
                self.event_calendar_path.name if self.event_calendar_path else None
            ),
            "ex_date_calendar_path": (
                self.ex_date_calendar_path.name if self.ex_date_calendar_path else None
            ),
            "backtest_enforce_ex_date_guard": self.backtest_enforce_ex_date_guard,
            "market_id": self.market_id,
            "session_kind": self.session_kind,
            "enforce_trend_mechanism": self.enforce_trend_mechanism,
            # Composition settings participate in the deterministic checksum.
            "composition_completeness_threshold": (self.composition_completeness_threshold),
            "factor_model": self.factor_model,
            "factor_loadings_refresh_seconds": (self.factor_loadings_refresh_seconds),
            "factor_loadings_max_age_seconds": (self.factor_loadings_max_age_seconds),
            "factor_loadings_dir": (
                self.factor_loadings_dir.name if self.factor_loadings_dir else None
            ),
            "sector_map_path": (self.sector_map_path.name if self.sector_map_path else None),
            "composition_lambda_tc": self.composition_lambda_tc,
            "composition_lambda_risk": self.composition_lambda_risk,
            "composition_max_universe_size": self.composition_max_universe_size,
            # Omit defaults to preserve established snapshot checksums.
            **(
                {"composition_signal_max_age_seconds": self.composition_signal_max_age_seconds}
                if self.composition_signal_max_age_seconds is not None
                else {}
            ),
            **(
                {"composition_optimizer_mode": self.composition_optimizer_mode}
                if self.composition_optimizer_mode != "closed_form"
                else {}
            ),
            # Omit default caps for the same checksum policy.
            **(
                {"composition_gross_cap_pct": self.composition_gross_cap_pct}
                if self.composition_gross_cap_pct != 2.0
                else {}
            ),
            **(
                {"composition_per_name_cap_pct": self.composition_per_name_cap_pct}
                if self.composition_per_name_cap_pct != 0.05
                else {}
            ),
            "enforce_layer_gates": self.enforce_layer_gates,
            "enforce_per_alpha_risk_budget": (self.enforce_per_alpha_risk_budget),
            # Hash the ledger basename, not its machine-specific location.
            "promotion_ledger_path": (
                self.promotion_ledger_path.name if self.promotion_ledger_path else None
            ),
            "gate_thresholds_overrides": dict(sorted(self.gate_thresholds_overrides.items())),
            # PAPER / LIVE connection settings — folded so config
            # checksums change when an operator points the same
            # platform at a different broker host or WS endpoint.
            "ib_host": self.ib_host,
            "ib_port": self.ib_port,
            "ib_client_id": self.ib_client_id,
            "massive_ws_url": self.massive_ws_url,
        }

    @classmethod
    def from_yaml(cls, path: str | Path, *, strict: bool = False) -> PlatformConfig:
        """Load configuration from a YAML file.

        With ``strict=True`` an unrecognized top-level key raises
        ``ConfigurationError`` instead of warning — opt-in fail-closed loading
        for CI / operator runs that want a misspelled override to abort rather
        than silently keep the default (default ``False`` preserves the
        forward-compatible warn-and-load behaviour).

        Raises ``ConfigurationError`` if the file is unreadable or
        contains invalid structure (including loosely-typed scalars, see
        :meth:`_check_yaml_keys_and_types`).

        Note: this only parses + type-coerces the YAML.  It does NOT run the
        semantic range checks in :meth:`validate` (e.g. "symbols non-empty",
        "ratios in range") — callers (``bootstrap.build_platform``) must call
        ``config.validate()`` before use.  Construction is kept separate from
        validation so partially-specified configs can be assembled in tests.
        """
        path = Path(path)
        from feelies.core.config_yaml import load_yaml_mapping

        try:
            data = load_yaml_mapping(path)
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(f"Failed to read config {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ConfigurationError(f"{path}: root must be a YAML mapping")

        # Warn when ignored cost aliases appear in operator config.
        for deprecated in ("cost_exchange_per_share", "passive_rebate_per_share"):
            if deprecated in data:
                logger.warning(
                    "platform.yaml %s sets deprecated field %r (ignored). "
                    "Use cost_taker_exchange_per_share / "
                    "cost_maker_exchange_per_share instead.",
                    path,
                    deprecated,
                )

        # Reject loose scalar types and unknown keys before coercion hides mistakes.
        cls._check_yaml_keys_and_types(data, source=path, strict=strict)

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

        terminal_raw = data.get("ingest_terminal_symbol_health")
        ingest_terminal_symbol_health: tuple[tuple[str, str], ...] = ()
        if terminal_raw:
            if not isinstance(terminal_raw, list):
                raise ConfigurationError(
                    f"{path}: ingest_terminal_symbol_health must be a list of pairs",
                )
            parsed_term: list[tuple[str, str]] = []
            for i, item in enumerate(terminal_raw):
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    raise ConfigurationError(
                        f"{path}: ingest_terminal_symbol_health[{i}] must be [symbol, state]",
                    )
                parsed_term.append((str(item[0]), str(item[1])))
            ingest_terminal_symbol_health = tuple(parsed_term)

        # Optional sensor and horizon fields.
        horizons_raw = data.get("horizons_seconds")
        if horizons_raw is None:
            horizons_seconds = frozenset({30, 120, 300, 900, 1800})
        else:
            try:
                horizons_seconds = frozenset(int(h) for h in horizons_raw)
            except (TypeError, ValueError) as exc:
                raise ConfigurationError(
                    f"horizons_seconds must be a list of positive ints: {exc}"
                ) from exc

        sensor_specs_raw = data.get("sensor_specs", []) or []
        if not isinstance(sensor_specs_raw, list):
            raise ConfigurationError("sensor_specs must be a YAML list (or omitted)")
        sensor_specs = tuple(
            cls._parse_sensor_spec(entry, source=path) for entry in sensor_specs_raw
        )

        event_calendar_raw = data.get("event_calendar_path")
        event_calendar_path = Path(event_calendar_raw) if event_calendar_raw else None

        session_open_ns_raw = data.get("session_open_ns")
        session_open_ns: int | None = (
            int(session_open_ns_raw) if session_open_ns_raw is not None else None
        )

        taker_exch_raw = data.get("cost_taker_exchange_per_share")
        maker_exch_raw = data.get("cost_maker_exchange_per_share")
        legacy_exch = data.get("cost_exchange_per_share")
        if taker_exch_raw is None and legacy_exch is not None:
            taker_exch_raw = legacy_exch
        if maker_exch_raw is None and legacy_exch is not None:
            maker_exch_raw = legacy_exch

        # Resolve each adverse-selection alias pair while preserving explicit zero.
        passive_adverse_raw = data.get("cost_passive_adverse_selection_bps")
        if passive_adverse_raw is None:
            passive_adverse_raw = data.get("cost_adverse_selection_drain_bps")
        through_adverse_raw = data.get("cost_through_fill_adverse_selection_bps")
        if through_adverse_raw is None:
            through_adverse_raw = data.get("cost_adverse_selection_through_bps")

        regime_cal_raw = data.get("regime_calibration_max_quotes")
        if regime_cal_raw is None:
            regime_calibration_max_quotes = None
        else:
            regime_calibration_max_quotes = int(regime_cal_raw)

        raw_regime_opts = data.get("regime_engine_options")
        if raw_regime_opts is None:
            regime_engine_options: dict[str, object] = {}
        else:
            if not isinstance(raw_regime_opts, dict):
                raise ConfigurationError(f"{path}: regime_engine_options must be a YAML mapping")
            regime_engine_options = {str(k): v for k, v in raw_regime_opts.items()}

        # PAPER mode connection settings: accept either flat top-level
        # keys (``ib_host: 127.0.0.1``) or a nested ``paper:`` block
        # (``paper: {ib_host: 127.0.0.1, ...}``).  Top-level keys win
        # when both are present.
        paper_block = data.get("paper") or {}
        if not isinstance(paper_block, dict):
            raise ConfigurationError(
                f"{path}: 'paper' must be a mapping, got {type(paper_block).__name__}"
            )
        ib_host = str(
            data.get(
                "ib_host",
                paper_block.get("ib_host", "127.0.0.1"),
            )
        )
        ib_port = int(
            data.get(  # type: ignore[arg-type]
                "ib_port",
                paper_block.get("ib_port", 4002),
            )
        )
        ib_client_id = int(
            data.get(  # type: ignore[arg-type]
                "ib_client_id",
                paper_block.get("ib_client_id", 1),
            )
        )
        massive_ws_url = str(
            data.get(
                "massive_ws_url",
                paper_block.get(
                    "massive_ws_url",
                    "wss://socket.massive.com/stocks",
                ),
            )
        )

        return cls(
            version=str(data.get("version", "0.1.0")),
            author=str(data.get("author", "system")),
            symbols=symbols,
            mode=mode,
            alpha_spec_dir=alpha_spec_dir,
            alpha_specs=alpha_specs,
            parameter_overrides=data.get("parameter_overrides", {}),
            regime_engine=data.get("regime_engine", "hmm_3state_fractional"),
            regime_engine_options=regime_engine_options,
            data_dir=Path(data_dir_raw) if data_dir_raw else None,
            event_log_path=Path(event_log_raw) if event_log_raw else None,
            risk_max_position_per_symbol=int(data.get("risk_max_position_per_symbol", 1000)),
            risk_max_gross_exposure_pct=float(data.get("risk_max_gross_exposure_pct", 20.0)),
            risk_max_drawdown_pct=float(data.get("risk_max_drawdown_pct", 5.0)),
            risk_regime_vol_breakout_scale=float(data.get("risk_regime_vol_breakout_scale", 0.5)),
            risk_regime_compression_scale=float(data.get("risk_regime_compression_scale", 0.75)),
            risk_regime_normal_scale=float(data.get("risk_regime_normal_scale", 1.0)),
            require_healthy_disk_cache_manifests=bool(
                data.get("require_healthy_disk_cache_manifests", False)
            ),
            degrade_on_data_gap=bool(data.get("degrade_on_data_gap", True)),
            warn_on_unhealthy_disk_cache=bool(data.get("warn_on_unhealthy_disk_cache", True)),
            ingest_terminal_symbol_health=ingest_terminal_symbol_health,
            backtest_enforce_ingest_terminal_health=bool(
                data.get("backtest_enforce_ingest_terminal_health", False)
            ),
            backtest_reject_zero_ingest_events=bool(
                data.get("backtest_reject_zero_ingest_events", False)
            ),
            strict_normalizer_symbol_coverage=bool(
                data.get("strict_normalizer_symbol_coverage", False)
            ),
            enable_rest_sequence_gap_detection=bool(
                data.get("enable_rest_sequence_gap_detection", False)
            ),
            halt_on_condition_codes=tuple(int(x) for x in data.get("halt_on_condition_codes", ())),
            halt_off_condition_codes=tuple(
                int(x) for x in data.get("halt_off_condition_codes", ())
            ),
            halt_resolution_blackout_seconds=int(data.get("halt_resolution_blackout_seconds", 60)),
            ssr_active_symbols=tuple(str(s) for s in data.get("ssr_active_symbols", ())),
            ssr_trigger_condition_codes=tuple(
                int(x) for x in data.get("ssr_trigger_condition_codes", ())
            ),
            ssr_mode=str(data.get("ssr_mode", "refuse_short")),
            borrow_availability={
                str(k).upper(): str(v).lower()
                for k, v in (data.get("borrow_availability") or {}).items()
            },
            moc_strategy_ids=tuple(
                str(s) for s in data.get("moc_strategy_ids", ("sig_moc_imbalance_v1",))
            ),
            moc_session_date=(
                str(data["moc_session_date"]) if data.get("moc_session_date") is not None else None
            ),
            moc_cutoff_et=str(data.get("moc_cutoff_et", "15:50")),
            official_close_et=str(data.get("official_close_et", "16:00")),
            early_close_dates=tuple(str(d) for d in data.get("early_close_dates", ())),
            early_close_moc_cutoff_et=str(data.get("early_close_moc_cutoff_et", "12:50")),
            early_close_official_close_et=str(data.get("early_close_official_close_et", "13:00")),
            rth_session_gating_enabled=bool(data.get("rth_session_gating_enabled", True)),
            rth_session_date=(
                str(data["rth_session_date"]) if data.get("rth_session_date") is not None else None
            ),
            rth_open_et=str(data.get("rth_open_et", "09:30")),
            rth_close_et=str(data.get("rth_close_et", "16:00")),
            early_close_rth_close_et=str(data.get("early_close_rth_close_et", "13:00")),
            market_holiday_dates=tuple(str(d) for d in data.get("market_holiday_dates", ())),
            no_entry_first_seconds=int(data.get("no_entry_first_seconds", 0)),
            account_equity=float(data.get("account_equity", 50_000.0)),
            account_type=str(data.get("account_type", "margin_25k")),
            account_id=str(data.get("account_id", "default")),
            pdt_min_equity_usd=float(data.get("pdt_min_equity_usd", 25_000.0)),
            risk_margin_intraday_buying_power_multiplier=float(
                data.get("risk_margin_intraday_buying_power_multiplier", 4.0)
            ),
            risk_margin_overnight_buying_power_multiplier=float(
                data.get("risk_margin_overnight_buying_power_multiplier", 2.0)
            ),
            backtest_fill_latency_ns=int(
                data.get(
                    "backtest_fill_latency_ns",
                    DEFAULT_BACKTEST_FILL_LATENCY_NS,
                )
            ),
            market_data_latency_ns=int(
                data.get(
                    "market_data_latency_ns",
                    DEFAULT_MARKET_DATA_LATENCY_NS,
                )
            ),
            stop_loss_per_share=float(data.get("stop_loss_per_share", 0.0)),
            trail_activate_per_share=float(data.get("trail_activate_per_share", 0.0)),
            trail_pct=float(data.get("trail_pct", 0.5)),
            stop_loss_pct=float(data.get("stop_loss_pct", 0.0)),
            trail_activate_pct=float(data.get("trail_activate_pct", 0.0)),
            cost_min_spread_bps=float(data.get("cost_min_spread_bps", 0.3)),
            cost_commission_per_share=float(data.get("cost_commission_per_share", 0.0035)),
            cost_exchange_per_share=float(data.get("cost_exchange_per_share", 0.0005)),
            cost_taker_exchange_per_share=float(
                taker_exch_raw if taker_exch_raw is not None else 0.003
            ),
            cost_maker_exchange_per_share=float(
                maker_exch_raw if maker_exch_raw is not None else 0.0
            ),
            cost_passive_adverse_selection_bps=float(
                passive_adverse_raw if passive_adverse_raw is not None else 2.0
            ),
            cost_through_fill_adverse_selection_bps=float(
                through_adverse_raw if through_adverse_raw is not None else 5.0
            ),
            cost_adverse_selection_through_bps=float(
                through_adverse_raw if through_adverse_raw is not None else 5.0
            ),
            cost_adverse_selection_drain_bps=float(
                passive_adverse_raw if passive_adverse_raw is not None else 2.0
            ),
            cost_sell_regulatory_bps=float(data.get("cost_sell_regulatory_bps", 0.5)),
            cost_stress_multiplier=float(data.get("cost_stress_multiplier", 1.0)),
            cost_min_commission=float(data.get("cost_min_commission", 0.35)),
            cost_max_commission_pct=float(data.get("cost_max_commission_pct", 1.0)),
            cost_finra_taf_per_share=float(data.get("cost_finra_taf_per_share", 0.000166)),
            cost_finra_taf_max_per_order=float(data.get("cost_finra_taf_max_per_order", 8.30)),
            cost_min_commission_applies_to_per_share_only=bool(
                data.get("cost_min_commission_applies_to_per_share_only", True)
            ),
            cost_spread_floor_taker_only=bool(data.get("cost_spread_floor_taker_only", True)),
            cost_max_impact_half_spreads=float(data.get("cost_max_impact_half_spreads", 10.0)),
            cost_stop_slippage_half_spreads=float(
                data.get("cost_stop_slippage_half_spreads", 2.0)
            ),
            execution_mode=str(data.get("execution_mode", "market")),
            cost_min_passive_bias_bps=float(data.get("cost_min_passive_bias_bps", 0.0)),
            cost_min_small_order_threshold_shares=int(
                data.get("cost_min_small_order_threshold_shares", 0)
            ),
            cost_min_half_spread_threshold=float(data.get("cost_min_half_spread_threshold", 0.0)),
            cost_min_allow_passive_short_entry=bool(
                data.get("cost_min_allow_passive_short_entry", True)
            ),
            cost_min_passive_non_fill_probability=float(
                data.get("cost_min_passive_non_fill_probability", 0.30)
            ),
            realized_cost_alert_ratio=float(data.get("realized_cost_alert_ratio", 1.5)),
            passive_fill_delay_ticks=int(data.get("passive_fill_delay_ticks", 3)),
            passive_max_resting_ticks=int(data.get("passive_max_resting_ticks", 50)),
            passive_rebate_per_share=float(data.get("passive_rebate_per_share", 0.002)),
            passive_queue_position_shares=int(data.get("passive_queue_position_shares", 0)),
            passive_fill_hazard_max=float(data.get("passive_fill_hazard_max", 0.5)),
            passive_cancel_fee_per_share=float(data.get("passive_cancel_fee_per_share", 0.0)),
            platform_min_order_shares=int(data.get("platform_min_order_shares", 1)),
            signal_min_edge_cost_ratio=float(data.get("signal_min_edge_cost_ratio", 1.0)),
            reversal_min_edge_cost_multiplier=float(
                data.get("reversal_min_edge_cost_multiplier", 1.5)
            ),
            position_manager_drive=bool(data.get("position_manager_drive", True)),
            position_manager_enable_trim=bool(data.get("position_manager_enable_trim", True)),
            position_manager_trim_min_fraction=float(
                data.get("position_manager_trim_min_fraction", 0.10)
            ),
            position_manager_trim_edge_gate_multiplier=float(
                data.get("position_manager_trim_edge_gate_multiplier", 1.0)
            ),
            position_manager_urgency_exec=bool(data.get("position_manager_urgency_exec", True)),
            session_flatten_enabled=bool(data.get("session_flatten_enabled", True)),
            session_flatten_seconds_before_close=int(
                data.get("session_flatten_seconds_before_close", 0)
            ),
            enable_portfolio_netting=bool(data.get("enable_portfolio_netting", False)),
            net_staleness_k=float(data.get("net_staleness_k", 1.0)),
            sizer_tilt_drive=bool(data.get("sizer_tilt_drive", False)),
            sizer_edge_weighting_enabled=bool(data.get("sizer_edge_weighting_enabled", False)),
            sizer_edge_ref_bps=float(data.get("sizer_edge_ref_bps", 20.0)),
            sizer_edge_floor=float(data.get("sizer_edge_floor", 0.25)),
            sizer_edge_cap=float(data.get("sizer_edge_cap", 2.0)),
            sizer_vol_targeting_enabled=bool(data.get("sizer_vol_targeting_enabled", False)),
            sizer_vol_target_bps=float(data.get("sizer_vol_target_bps", 100.0)),
            sizer_vol_floor=float(data.get("sizer_vol_floor", 0.25)),
            sizer_vol_cap=float(data.get("sizer_vol_cap", 2.0)),
            sizer_inventory_penalty_enabled=bool(
                data.get("sizer_inventory_penalty_enabled", False)
            ),
            sizer_inventory_floor=float(data.get("sizer_inventory_floor", 0.0)),
            sizer_tilt_floor=float(data.get("sizer_tilt_floor", 0.10)),
            sizer_tilt_cap=float(data.get("sizer_tilt_cap", 3.0)),
            signal_edge_cost_basis=str(data.get("signal_edge_cost_basis", "round_trip")),
            regime_calibration_max_quotes=regime_calibration_max_quotes,
            regime_min_discriminability=float(data.get("regime_min_discriminability", 0.0)),
            enforce_regime_state_scale_alignment=bool(
                data.get("enforce_regime_state_scale_alignment", False)
            ),
            cost_market_impact_factor=float(data.get("cost_market_impact_factor", 0.5)),
            cost_htb_borrow_annual_bps=float(data.get("cost_htb_borrow_annual_bps", 0.0)),
            cost_within_l1_impact_factor=float(data.get("cost_within_l1_impact_factor", 0.0)),
            cost_permanent_impact_coefficient=float(
                data.get("cost_permanent_impact_coefficient", 0.0)
            ),
            cost_moc_penalty_bps=float(data.get("cost_moc_penalty_bps", 0.0)),
            cost_stop_depth_depletion_factor=float(
                data.get("cost_stop_depth_depletion_factor", 1.0)
            ),
            passive_through_fill_size_cap_enabled=bool(
                data.get("passive_through_fill_size_cap_enabled", False)
            ),
            passive_require_trade_for_level_fill=bool(
                data.get("passive_require_trade_for_level_fill", False)
            ),
            borrow_default_tier=str(data.get("borrow_default_tier", "available")),
            realized_cost_escalation_enabled=bool(
                data.get("realized_cost_escalation_enabled", False)
            ),
            realized_cost_escalation_streak=int(data.get("realized_cost_escalation_streak", 3)),
            cache_dir=Path(cache_dir_raw) if cache_dir_raw else None,
            session_open_ns=session_open_ns,
            horizons_seconds=horizons_seconds,
            sensor_specs=sensor_specs,
            prune_unused_sensors=bool(data.get("prune_unused_sensors", False)),
            event_calendar_path=event_calendar_path,
            ex_date_calendar_path=(
                Path(str(data["ex_date_calendar_path"]))
                if data.get("ex_date_calendar_path") is not None
                else None
            ),
            backtest_enforce_ex_date_guard=bool(data.get("backtest_enforce_ex_date_guard", True)),
            market_id=str(data.get("market_id", "US_EQUITY")),
            session_kind=str(data.get("session_kind", "RTH")),
            enforce_trend_mechanism=bool(data.get("enforce_trend_mechanism", True)),
            composition_completeness_threshold=float(
                data.get("composition_completeness_threshold", 0.80)
            ),
            factor_model=str(data.get("factor_model", "FF5_momentum_STR")),
            factor_loadings_refresh_seconds=int(data.get("factor_loadings_refresh_seconds", 0)),
            factor_loadings_max_age_seconds=int(
                data.get("factor_loadings_max_age_seconds", 7 * 24 * 3600)
            ),
            composition_signal_max_age_seconds=(
                int(data["composition_signal_max_age_seconds"])
                if data.get("composition_signal_max_age_seconds") is not None
                else None
            ),
            composition_optimizer_mode=str(data.get("composition_optimizer_mode", "closed_form")),
            factor_loadings_dir=(
                Path(data["factor_loadings_dir"]) if data.get("factor_loadings_dir") else None
            ),
            sector_map_path=(
                Path(data["sector_map_path"]) if data.get("sector_map_path") else None
            ),
            composition_lambda_tc=float(data.get("composition_lambda_tc", 1.0)),
            composition_lambda_risk=float(data.get("composition_lambda_risk", 0.1)),
            composition_max_universe_size=int(data.get("composition_max_universe_size", 50)),
            composition_gross_cap_pct=float(data.get("composition_gross_cap_pct", 2.0)),
            composition_per_name_cap_pct=float(data.get("composition_per_name_cap_pct", 0.05)),
            enforce_layer_gates=bool(data.get("enforce_layer_gates", True)),
            enforce_per_alpha_risk_budget=bool(data.get("enforce_per_alpha_risk_budget", True)),
            promotion_ledger_path=(
                Path(data["promotion_ledger_path"]) if data.get("promotion_ledger_path") else None
            ),
            gate_thresholds_overrides=cls._parse_gate_thresholds_block(
                data.get("gate_thresholds"), source=path
            ),
            ib_host=ib_host,
            ib_port=ib_port,
            ib_client_id=ib_client_id,
            massive_ws_url=massive_ws_url,
        )

    # Top-level YAML keys that are accepted but do not map 1:1 to a
    # PlatformConfig field name: ``gate_thresholds`` → gate_thresholds_overrides,
    # ``paper`` is a nested connection block, ``extends`` is consumed by the
    # YAML loader (may survive as ``extends: null``).
    _NON_FIELD_YAML_KEYS = frozenset({"gate_thresholds", "paper", "extends"})

    @classmethod
    def _check_yaml_keys_and_types(
        cls, data: dict[str, Any], *, source: Path, strict: bool = False
    ) -> None:
        """Validate YAML keys and bare scalar types before coercion.

        Unknown keys warn because they are usually misspelled overrides.
        Bare ``bool``, ``int``, and ``float`` fields require matching YAML
        types, except that integers may widen to floats. Union fields retain
        their dedicated parsers.
        """
        fields = cls.__dataclass_fields__
        known = set(fields) | cls._NON_FIELD_YAML_KEYS

        unknown = sorted(k for k in data if k not in known)
        if unknown:
            if strict:
                raise ConfigurationError(
                    f"{source}: unrecognized config key(s) {unknown} — check for typos. "
                    "(strict config loading is enabled; a misspelled key would otherwise "
                    "silently keep the default.)"
                )
            logger.warning(
                "%s: ignoring unrecognized config key(s) %s — check for typos; "
                "a misspelled key silently keeps the default.",
                source,
                unknown,
            )

        for key, value in data.items():
            field_obj = fields.get(key)
            if field_obj is None:
                continue
            ann = field_obj.type if isinstance(field_obj.type, str) else None
            if ann == "bool":
                # bool first: bool is a subclass of int, so the int branch
                # below must never see a bool.
                if not isinstance(value, bool):
                    raise ConfigurationError(
                        f"{source}: {key} must be a boolean (true/false), "
                        f"got {type(value).__name__}: {value!r}"
                    )
            elif ann == "int":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ConfigurationError(
                        f"{source}: {key} must be an integer, "
                        f"got {type(value).__name__}: {value!r}"
                    )
            elif ann == "float":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ConfigurationError(
                        f"{source}: {key} must be a number, got {type(value).__name__}: {value!r}"
                    )

    @staticmethod
    def _parse_gate_thresholds_block(
        block: Any,
        *,
        source: Path,
    ) -> dict[str, Any]:
        """Parse the optional top-level ``gate_thresholds:`` block.

        Keys must name fields of
        :class:`feelies.alpha.promotion_evidence.GateThresholds`.
        Per-key validation + type coercion is delegated to
        :func:`feelies.alpha.promotion_evidence.parse_gate_thresholds_overrides`
        — failures are re-raised as
        :class:`~feelies.core.errors.ConfigurationError` so the
        operator sees a single error class for every YAML parse
        failure under this loader.

        Returns an empty dict when the block is absent or empty.
        """
        if block is None:
            return {}
        if not isinstance(block, dict):
            raise ConfigurationError(
                f"{source}: 'gate_thresholds' must be a mapping, got {type(block).__name__}"
            )
        if not block:
            return {}

        # Imported lazily to avoid a hard dependency cycle between
        # core.platform_config and alpha.promotion_evidence at import
        # time (alpha modules import core.events / core.config).
        from feelies.alpha.promotion_evidence import (
            parse_gate_thresholds_overrides,
        )

        try:
            return parse_gate_thresholds_overrides(block)
        except ValueError as exc:
            raise ConfigurationError(f"{source}: gate_thresholds: {exc}") from exc

    @staticmethod
    def _parse_sensor_spec(entry: Any, *, source: Path) -> SensorSpec:
        """Parse a single ``sensor_specs:`` entry from YAML.

        Expected schema:

        .. code-block:: yaml

            sensor_specs:
              - sensor_id: ofi_ewma
                sensor_version: "1.0.0"
                cls: feelies.sensors.impl.ofi_ewma.OfiEwmaSensor
                params:
                  half_life_ns: 5000000000
                subscribes_to: [NBBOQuote]
                input_sensor_ids: []
                min_history: 100
                throttled_ms: null

        ``cls`` is an importable dotted path restricted to
        ``feelies.sensors.impl.*`` to prevent arbitrary imports from config.
        """
        if not isinstance(entry, dict):
            raise ConfigurationError(
                f"{source}: each sensor_specs entry must be a mapping, got {type(entry).__name__}"
            )

        sensor_id = entry.get("sensor_id")
        sensor_version = entry.get("sensor_version")
        cls_path = entry.get("cls")
        if not (
            isinstance(sensor_id, str)
            and isinstance(sensor_version, str)
            and isinstance(cls_path, str)
        ):
            raise ConfigurationError(
                f"{source}: sensor_specs entry requires string "
                f"sensor_id, sensor_version, cls; got {entry!r}"
            )

        if not cls_path.startswith("feelies.sensors.impl."):
            raise ConfigurationError(
                f"{source}: sensor cls must live under feelies.sensors.impl.*; got {cls_path!r}"
            )
        module_name, _, class_name = cls_path.rpartition(".")
        try:
            module = importlib.import_module(module_name)
            sensor_cls = getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            raise ConfigurationError(
                f"{source}: cannot import sensor class {cls_path!r}: {exc}"
            ) from exc

        subscribes_to_raw = entry.get("subscribes_to") or ["NBBOQuote"]
        type_map = {"NBBOQuote": NBBOQuote, "Trade": Trade}
        try:
            subscribes_to = tuple(type_map[name] for name in subscribes_to_raw)
        except KeyError as exc:
            raise ConfigurationError(
                f"{source}: unknown event type in subscribes_to "
                f"for sensor {sensor_id!r}: {exc.args[0]!r}; valid "
                f"types are {sorted(type_map)}"
            ) from exc

        input_sensor_ids = tuple(entry.get("input_sensor_ids", []) or [])
        params = dict(entry.get("params", {}) or {})
        min_history = int(entry.get("min_history", 0))
        throttled_ms_raw = entry.get("throttled_ms")
        throttled_ms = None if throttled_ms_raw is None else int(throttled_ms_raw)
        # Stateful throttled sensors update on every event. Explicit false confirms
        # that skipping intermediate updates is safe; omission still warns.
        stateful_key_present = "stateful" in entry
        stateful = bool(entry.get("stateful", False))
        stateless_throttle_ok = (
            throttled_ms is not None and throttled_ms > 0 and stateful_key_present and not stateful
        )

        return SensorSpec(
            sensor_id=sensor_id,
            sensor_version=sensor_version,
            cls=sensor_cls,
            params=params,
            subscribes_to=subscribes_to,
            input_sensor_ids=input_sensor_ids,
            min_history=min_history,
            throttled_ms=throttled_ms,
            stateful=stateful,
            stateless_throttle_ok=stateless_throttle_ok,
        )
