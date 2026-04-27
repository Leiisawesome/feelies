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
import importlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

import yaml  # pyright: ignore[reportMissingModuleSource]

from feelies.core.config import ConfigSnapshot
from feelies.core.errors import ConfigurationError
from feelies.core.events import NBBOQuote, Trade
from feelies.sensors.spec import SensorSpec


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
    cost_exchange_per_share: float = 0.0005  # deprecated; use taker/maker fields below
    cost_taker_exchange_per_share: float = 0.003
    cost_maker_exchange_per_share: float = -0.002
    cost_passive_adverse_selection_bps: float = 0.5
    cost_sell_regulatory_bps: float = 0.0
    cost_stress_multiplier: float = 1.0
    cost_min_commission: float = 0.35
    cost_max_commission_pct: float = 1.0

    # Execution mode: "market" (immediate mid-price fill, spread cost charged)
    # or "passive_limit" (limit orders at BBO, queue-position fill model).
    execution_mode: str = "market"
    # Ticks at our level before queue-drain fill triggers (legacy tick-based mode).
    passive_fill_delay_ticks: int = 3
    # Cancel unfilled resting orders after this many ticks.
    passive_max_resting_ticks: int = 50
    # Maker rebate per share — deprecated; maker fee now in cost model.
    passive_rebate_per_share: float = 0.002
    # Shares traded at our level before queue-drain fill triggers (D10 mode).
    # 0 = disabled, use tick-based fill_delay_ticks instead.
    passive_queue_position_shares: int = 0
    # Cancel fee charged per share when a resting order times out (default 0).
    passive_cancel_fee_per_share: float = 0.0

    # Minimum order size gate: orders below this number of shares are suppressed.
    platform_min_order_shares: int = 1

    # B4: signal edge vs round-trip cost gate.
    # Orders are suppressed when signal.edge_estimate_bps < ratio × 2 × cost_bps.
    # Set to 0 to disable the gate (no filtering).  Default 2.0.
    signal_min_edge_cost_ratio: float = 0.0

    # 2d: market-impact factor for walk-the-book slippage on large orders.
    # Excess beyond L1 available depth is priced at
    #   fill_price ± impact_factor × (excess / depth) × half_spread.
    # Default 0.5 (half a spread per full-depth multiple of excess).
    cost_market_impact_factor: float = 0.5

    # 2g: annualised hard-to-borrow fee in basis points for short-side fills.
    # Applied as a daily cost (annual_bps / 252) on SELL fills flagged as_short.
    # Default 0 = disabled.  Set for short-selling strategies only.
    cost_htb_borrow_annual_bps: float = 0.0

    cache_dir: Path | None = None

    # ── Phase-2 (three-layer architecture) — all optional ──────────────
    #
    # These fields drive the new sensor / horizon scheduler subsystem
    # introduced by ``design_docs/three_layer_architecture.md``.  They
    # are *all* optional with defaults that preserve Phase-1 behaviour
    # bit-for-bit:
    #
    # - ``sensor_specs=()`` causes the bootstrap layer to skip the
    #   sensor registry entirely and the orchestrator to take the
    #   legacy micro-state path (Inv-A in the implementation plan).
    # - ``session_open_ns=None`` defers session-anchor binding to the
    #   ``HorizonScheduler``'s lazy first-event auto-bind.
    # - ``horizons_seconds`` carries the canonical five horizons from
    #   §7.4 of the design doc; consumers that don't need them simply
    #   register no sensors and pay no cost.
    # - ``event_calendar_path`` is parsed in P2.1 by the calendar
    #   adapter; ``None`` keeps the demo deterministic.
    session_open_ns: int | None = None
    horizons_seconds: frozenset[int] = field(
        default_factory=lambda: frozenset({30, 120, 300, 900, 1800})
    )
    sensor_specs: tuple[SensorSpec, ...] = ()
    event_calendar_path: Path | None = None
    market_id: str = "US_EQUITY"
    session_kind: str = "RTH"

    # ── Phase-3.1 (mechanism enforcement) ─────────────────────────────
    #
    # Strict-mode default for gate G16 (§20.6.2).  When ``True``
    # (the post-Workstream-E default), every schema-1.1 SIGNAL/PORTFOLIO
    # spec MUST declare a fully-formed ``trend_mechanism:`` block —
    # the loader refuses to load otherwise via
    # :class:`MissingTrendMechanismError`.  When ``False`` (legacy
    # opt-out), schema-1.1 SIGNAL/PORTFOLIO specs may omit the block
    # and G16 only fires for specs that *do* declare it; this is the
    # documented escape hatch for v0.2-baseline alphas (such as the
    # reference ``pofi_benign_midcap_v1``) that pre-date the mechanism
    # taxonomy.
    #
    # Workstream E (acceptance row 84, §20.12.1) flipped the default
    # from False → True now that the four canonical reference alphas
    # (one per non-stress family — KYLE_INFO / INVENTORY /
    # HAWKES_SELF_EXCITE / SCHEDULED_FLOW) ship under strict mode and
    # close the §20.12.2 #4 acceptance criterion.  Operators relying
    # on a v0.2 baseline alpha must now opt back in by pinning
    # ``enforce_trend_mechanism: false`` in their ``platform.yaml``;
    # the reference ``platform.yaml`` documents this opt-out path
    # alongside the v0.2 reference alpha.
    enforce_trend_mechanism: bool = True

    # ── Phase-4 (composition layer) ──────────────────────────────────
    #
    # All optional with v0.2-preserving defaults.  When no PORTFOLIO
    # alpha is loaded, the composition pipeline is not wired and these
    # fields are inert (Inv-A; bootstrap §6.11 step 7-8).
    #
    # ``composition_completeness_threshold`` — UNIVERSE-scope barrier
    # close: if the fraction of universe symbols with valid signals at
    # the decision-horizon tick is below this, the composition engine
    # *skips* the decision (per-symbol fallback = no position change,
    # Inv-11 fail-safe).  Default 0.80.
    #
    # ``factor_model`` — neutralization model identifier consumed by
    # ``composition/factor_neutralizer.py``.  ``"none"`` disables
    # neutralization (passthrough).  Default ``"FF5_momentum_STR"``.
    #
    # ``factor_loadings_refresh_seconds`` — cadence at which the
    # neutralizer reloads its loadings table.  ``0`` = static-at-bootstrap
    # (deterministic for backtests; the recommended setting).
    #
    # ``factor_loadings_max_age_seconds`` — bootstrap-time staleness
    # gate: every symbol in any loaded PORTFOLIO alpha's effective
    # universe MUST have a loadings row dated within this window or
    # bootstrap raises ``StaleFactorLoadingsError``.  Default 7 days.
    #
    # ``composition_lambda_tc`` / ``composition_lambda_risk`` — turnover
    # and risk penalty weights in the CVXPY objective
    # ``max w·α − λ_TC·‖Δw‖₁ − λ_risk·w'Σw``.
    #
    # ``composition_max_universe_size`` — Phase-4 ships with a 10-symbol
    # reference universe.  Per §15.1 we hard-cap at 50 in v0.2 and defer
    # universe-scaling to a separate workstream (v0.4); exceeding this
    # cap raises ``UniverseScaleError`` at bootstrap.
    #
    # ``enforce_layer_gates`` — when True (default, production setting)
    # alphas failing G1/G3/G9/G10/G11 are refused.  When False, G1/G3
    # downgrade to WARN (research escape hatch).  G9/G10/G11 are
    # always blocking regardless of this flag (data-integrity gates).
    composition_completeness_threshold: float = 0.80
    factor_model: str = "FF5_momentum_STR"
    factor_loadings_refresh_seconds: int = 0
    factor_loadings_max_age_seconds: int = 7 * 24 * 3600
    factor_loadings_dir: Path | None = None
    sector_map_path: Path | None = None
    composition_lambda_tc: float = 1.0
    composition_lambda_risk: float = 0.1
    composition_max_universe_size: int = 50
    enforce_layer_gates: bool = True

    # ── Workstream F-1 (promotion evidence ledger) ────────────────
    #
    # Optional path to an append-only JSONL ledger that records every
    # committed alpha-lifecycle transition (RESEARCH→PAPER, PAPER→LIVE,
    # LIVE→QUARANTINED, QUARANTINED→PAPER, QUARANTINED→DECOMMISSIONED).
    # When ``None`` (default), no ledger is constructed and lifecycle
    # transitions emit no forensic record (preserving Phase-1/2/3/4
    # behaviour bit-identically).
    #
    # When set, ``bootstrap.build_platform`` instantiates a
    # :class:`feelies.alpha.promotion_ledger.PromotionLedger` at this
    # path, passes it to :class:`AlphaRegistry`, and every
    # :class:`AlphaLifecycle` constructed by the registry registers a
    # ``StateMachine.on_transition`` callback that appends a
    # :class:`PromotionLedgerEntry` for each successful transition.
    # Backtest deployments — which already disable per-alpha lifecycle
    # tracking via ``registry_clock=None`` — leave the ledger file
    # untouched (no transitions occur).
    #
    # The ledger is *forensic-only*: production code paths must NOT
    # consume it for per-tick decisions.  See
    # :mod:`feelies.alpha.promotion_ledger` for the consumer contract.
    promotion_ledger_path: Path | None = None

    # ── Workstream F-5 (per-platform gate-threshold overrides) ─────
    #
    # Optional flat-key mapping of
    # :class:`feelies.alpha.promotion_evidence.GateThresholds` field
    # names to override values applied on top of the skill-pinned
    # defaults at bootstrap time.  Per-alpha overrides declared in the
    # ``promotion: { gate_thresholds: ... }`` block of an
    # ``.alpha.yaml`` are then layered on top of *this* result by
    # :class:`feelies.alpha.registry.AlphaRegistry`.
    #
    # Layering precedence (lowest to highest):
    #
    #   1. ``GateThresholds()`` skill-pinned defaults
    #      (``promotion_evidence.py``).
    #   2. ``platform.yaml :: gate_thresholds`` (this field).
    #   3. ``<alpha>.alpha.yaml :: promotion.gate_thresholds``
    #      (manifest-level).
    #
    # An empty dict (default) means "no platform overrides; pure
    # skill-pinned defaults are used everywhere except where a
    # per-alpha override applies".
    #
    # Keys are *not* validated at config-construction time — the
    # validator is invoked from
    # :func:`feelies.bootstrap.build_platform` so YAML errors surface
    # at bootstrap with a single error class
    # (:class:`feelies.core.errors.ConfigurationError`).
    gate_thresholds_overrides: dict[str, Any] = field(default_factory=dict)

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

        # ── Phase-2 validation ────────────────────────────────────────
        for h in self.horizons_seconds:
            if h <= 0:
                raise ConfigurationError(
                    f"horizons_seconds must contain positive integers, "
                    f"got {h}"
                )
        if self.session_open_ns is not None and self.session_open_ns < 0:
            raise ConfigurationError(
                f"session_open_ns must be non-negative or None, "
                f"got {self.session_open_ns}"
            )
        if not self.market_id:
            raise ConfigurationError("market_id must be non-empty")
        if not self.session_kind:
            raise ConfigurationError("session_kind must be non-empty")

        # Sensor specs: detect duplicate (sensor_id, sensor_version)
        # pairs early so registration-time errors at boot are reserved
        # for genuinely missing dependencies.
        seen: set[tuple[str, str]] = set()
        spec_ids: set[str] = set()
        for spec in self.sensor_specs:
            if spec.key in seen:
                raise ConfigurationError(
                    f"duplicate sensor spec: {spec.sensor_id!r} "
                    f"version {spec.sensor_version!r}"
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
                        f"sensor {spec.sensor_id!r} declares unknown "
                        f"input sensor {upstream!r}"
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
            # P2.1: the calendar adapter loads YAML at boot; surface
            # a missing file as a config error rather than letting it
            # explode at first event.
            raise ConfigurationError(
                f"event_calendar_path does not exist: "
                f"{self.event_calendar_path}"
            )

        # ── Phase-4 validation ────────────────────────────────────────
        if not 0.0 <= self.composition_completeness_threshold <= 1.0:
            raise ConfigurationError(
                f"composition_completeness_threshold must be in [0,1], "
                f"got {self.composition_completeness_threshold}"
            )
        if self.factor_loadings_refresh_seconds < 0:
            raise ConfigurationError(
                "factor_loadings_refresh_seconds must be non-negative"
            )
        if self.factor_loadings_max_age_seconds <= 0:
            raise ConfigurationError(
                "factor_loadings_max_age_seconds must be positive"
            )
        if self.composition_lambda_tc < 0.0:
            raise ConfigurationError(
                "composition_lambda_tc must be non-negative"
            )
        if self.composition_lambda_risk < 0.0:
            raise ConfigurationError(
                "composition_lambda_risk must be non-negative"
            )
        if self.composition_max_universe_size <= 0:
            raise ConfigurationError(
                "composition_max_universe_size must be positive"
            )
        if (
            self.factor_loadings_dir is not None
            and not self.factor_loadings_dir.is_dir()
        ):
            raise ConfigurationError(
                f"factor_loadings_dir does not exist: "
                f"{self.factor_loadings_dir}"
            )
        if (
            self.sector_map_path is not None
            and not self.sector_map_path.is_file()
        ):
            raise ConfigurationError(
                f"sector_map_path does not exist: {self.sector_map_path}"
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
        # Path-based fields are normalised to their basename before being
        # folded into the snapshot. Absolute filesystem paths are
        # environment metadata (per machine, per tempdir, per checkout
        # location) and would otherwise leak into ``checksum``, breaking
        # both two-run determinism (audit A-DET-02) and cross-machine
        # reproducibility (audit B-PROMO-04). The basename still
        # discriminates between distinct alpha bundles by name.
        return {
            "version": self.version,
            "author": self.author,
            "symbols": sorted(self.symbols),
            "mode": self.mode.name,
            "alpha_spec_dir": self.alpha_spec_dir.name if self.alpha_spec_dir else None,
            "alpha_specs": sorted(p.name for p in self.alpha_specs),
            "parameter_overrides": self.parameter_overrides,
            "regime_engine": self.regime_engine,
            "data_dir": self.data_dir.name if self.data_dir else None,
            "event_log_path": self.event_log_path.name if self.event_log_path else None,
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
            "cost_taker_exchange_per_share": self.cost_taker_exchange_per_share,
            "cost_maker_exchange_per_share": self.cost_maker_exchange_per_share,
            "cost_passive_adverse_selection_bps": self.cost_passive_adverse_selection_bps,
            "cost_sell_regulatory_bps": self.cost_sell_regulatory_bps,
            "cost_stress_multiplier": self.cost_stress_multiplier,
            "cost_min_commission": self.cost_min_commission,
            "cost_max_commission_pct": self.cost_max_commission_pct,
            "execution_mode": self.execution_mode,
            "passive_fill_delay_ticks": self.passive_fill_delay_ticks,
            "passive_max_resting_ticks": self.passive_max_resting_ticks,
            "passive_queue_position_shares": self.passive_queue_position_shares,
            "passive_cancel_fee_per_share": self.passive_cancel_fee_per_share,
            "platform_min_order_shares": self.platform_min_order_shares,
            "signal_min_edge_cost_ratio": self.signal_min_edge_cost_ratio,
            "cost_market_impact_factor": self.cost_market_impact_factor,
            "cost_htb_borrow_annual_bps": self.cost_htb_borrow_annual_bps,
            # Phase-2 fields (folded into the snapshot so determinism
            # checksums change when sensor configuration changes — but
            # default values keep the snapshot bit-stable for legacy
            # configs).
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
                }
                for s in self.sensor_specs
            ],
            "event_calendar_path": (
                self.event_calendar_path.name
                if self.event_calendar_path
                else None
            ),
            "market_id": self.market_id,
            "session_kind": self.session_kind,
            "enforce_trend_mechanism": self.enforce_trend_mechanism,
            # Phase-4 fields (folded into the snapshot so determinism
            # checksums change when composition configuration changes;
            # default values keep the snapshot bit-stable for legacy
            # configs).
            "composition_completeness_threshold": (
                self.composition_completeness_threshold
            ),
            "factor_model": self.factor_model,
            "factor_loadings_refresh_seconds": (
                self.factor_loadings_refresh_seconds
            ),
            "factor_loadings_max_age_seconds": (
                self.factor_loadings_max_age_seconds
            ),
            "factor_loadings_dir": (
                self.factor_loadings_dir.name
                if self.factor_loadings_dir
                else None
            ),
            "sector_map_path": (
                self.sector_map_path.name if self.sector_map_path else None
            ),
            "composition_lambda_tc": self.composition_lambda_tc,
            "composition_lambda_risk": self.composition_lambda_risk,
            "composition_max_universe_size": self.composition_max_universe_size,
            "enforce_layer_gates": self.enforce_layer_gates,
            # Workstream F-1: ledger path is folded as a basename only
            # (same Path-normalisation policy as event_log_path /
            # cache_dir) so absolute-fs paths don't leak into the
            # config checksum and break two-run determinism (A-DET-02).
            "promotion_ledger_path": (
                self.promotion_ledger_path.name
                if self.promotion_ledger_path
                else None
            ),
            "gate_thresholds_overrides": dict(
                sorted(self.gate_thresholds_overrides.items())
            ),
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

        # ── Phase-2 fields (optional in YAML) ─────────────────────────
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
            raise ConfigurationError(
                "sensor_specs must be a YAML list (or omitted)"
            )
        sensor_specs = tuple(
            cls._parse_sensor_spec(entry, source=path)
            for entry in sensor_specs_raw
        )

        event_calendar_raw = data.get("event_calendar_path")
        event_calendar_path = (
            Path(event_calendar_raw) if event_calendar_raw else None
        )

        session_open_ns_raw = data.get("session_open_ns")
        session_open_ns: int | None = (
            int(session_open_ns_raw) if session_open_ns_raw is not None else None
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
            cost_taker_exchange_per_share=float(
                data.get("cost_taker_exchange_per_share", 0.003)
            ),
            cost_maker_exchange_per_share=float(
                data.get("cost_maker_exchange_per_share", -0.002)
            ),
            cost_passive_adverse_selection_bps=float(
                data.get("cost_passive_adverse_selection_bps", 0.5)
            ),
            cost_sell_regulatory_bps=float(
                data.get("cost_sell_regulatory_bps", 0.0)
            ),
            cost_stress_multiplier=float(
                data.get("cost_stress_multiplier", 1.0)
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
            passive_queue_position_shares=int(
                data.get("passive_queue_position_shares", 0)
            ),
            passive_cancel_fee_per_share=float(
                data.get("passive_cancel_fee_per_share", 0.0)
            ),
            platform_min_order_shares=int(
                data.get("platform_min_order_shares", 1)
            ),
            signal_min_edge_cost_ratio=float(
                data.get("signal_min_edge_cost_ratio", 0.0)
            ),
            cost_market_impact_factor=float(
                data.get("cost_market_impact_factor", 0.5)
            ),
            cost_htb_borrow_annual_bps=float(
                data.get("cost_htb_borrow_annual_bps", 0.0)
            ),
            cache_dir=Path(cache_dir_raw) if cache_dir_raw else None,
            session_open_ns=session_open_ns,
            horizons_seconds=horizons_seconds,
            sensor_specs=sensor_specs,
            event_calendar_path=event_calendar_path,
            market_id=str(data.get("market_id", "US_EQUITY")),
            session_kind=str(data.get("session_kind", "RTH")),
            enforce_trend_mechanism=bool(
                data.get("enforce_trend_mechanism", True)
            ),
            composition_completeness_threshold=float(
                data.get("composition_completeness_threshold", 0.80)
            ),
            factor_model=str(data.get("factor_model", "FF5_momentum_STR")),
            factor_loadings_refresh_seconds=int(
                data.get("factor_loadings_refresh_seconds", 0)
            ),
            factor_loadings_max_age_seconds=int(
                data.get("factor_loadings_max_age_seconds", 7 * 24 * 3600)
            ),
            factor_loadings_dir=(
                Path(data["factor_loadings_dir"])
                if data.get("factor_loadings_dir")
                else None
            ),
            sector_map_path=(
                Path(data["sector_map_path"])
                if data.get("sector_map_path")
                else None
            ),
            composition_lambda_tc=float(
                data.get("composition_lambda_tc", 1.0)
            ),
            composition_lambda_risk=float(
                data.get("composition_lambda_risk", 0.1)
            ),
            composition_max_universe_size=int(
                data.get("composition_max_universe_size", 50)
            ),
            enforce_layer_gates=bool(
                data.get("enforce_layer_gates", True)
            ),
            promotion_ledger_path=(
                Path(data["promotion_ledger_path"])
                if data.get("promotion_ledger_path")
                else None
            ),
            gate_thresholds_overrides=cls._parse_gate_thresholds_block(
                data.get("gate_thresholds"), source=path
            ),
        )

    @staticmethod
    def _parse_gate_thresholds_block(
        block: Any, *, source: Path,
    ) -> dict[str, Any]:
        """Parse the optional top-level ``gate_thresholds:`` YAML block.

        Workstream F-5 platform-level override entry-point.  The
        block, when present, must be a mapping whose keys correspond
        to fields of
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
                f"{source}: 'gate_thresholds' must be a mapping, got "
                f"{type(block).__name__}"
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
            raise ConfigurationError(
                f"{source}: gate_thresholds: {exc}"
            ) from exc

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

        ``cls:`` is a fully-qualified dotted path resolved by importlib.
        Sensor classes live exclusively in
        ``feelies.sensors.impl.*`` per the design doc; we enforce that
        prefix here to keep the YAML attack surface narrow (no
        arbitrary-import via config).
        """
        if not isinstance(entry, dict):
            raise ConfigurationError(
                f"{source}: each sensor_specs entry must be a mapping, "
                f"got {type(entry).__name__}"
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
                f"{source}: sensor cls must live under "
                f"feelies.sensors.impl.*; got {cls_path!r}"
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
        throttled_ms = (
            None if throttled_ms_raw is None else int(throttled_ms_raw)
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
        )
