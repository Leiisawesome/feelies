"""Bootstrap-time wiring tests for the Phase-4 composition layer.

Covers three sub-cases (plan §p4f_bootstrap_tests):

1. ``test_no_portfolio_alpha_no_composition`` — when no PORTFOLIO alpha
   is registered, none of the composition layer components are
   constructed.  Validates Inv-A: legacy LEGACY_SIGNAL parity hash
   stays bit-stable for default deployments.
2. ``test_single_portfolio_alpha_wires_full_pipeline`` — registering a
   single PORTFOLIO alpha brings up the entire composition pipeline:
   ``CompositionEngine``, ``CrossSectionalTracker``,
   ``HorizonMetricsCollector``, and (when hazard_exit is enabled) a
   ``HazardExitController``.
3. ``test_universe_scale_cap_fail_stop`` — exceeding
   ``composition_max_universe_size`` raises :class:`UniverseScaleError`
   at bootstrap rather than silently shipping a quietly-wrong pipeline
   (Inv-11 fail-safe).
"""

from __future__ import annotations

import textwrap  # noqa: F401  (retained for the legacy fixture)
from pathlib import Path

import pytest

from feelies.bootstrap import (
    StaleFactorLoadingsError,
    UniverseScaleError,
    build_platform,
)
from feelies.composition.engine import CompositionEngine
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
from feelies.risk.hazard_exit import HazardExitController


_LEGACY_ALPHA_YAML = textwrap.dedent(
    """\
    schema_version: "1.1"
    layer: LEGACY_SIGNAL
    alpha_id: legacy_test_alpha
    version: "1.0.0"
    author: test
    description: legacy test alpha
    hypothesis: test
    falsification_criteria:
      - test criterion
    symbols:
      - AAPL
    parameters: {}
    risk_budget:
      max_position_per_symbol: 100
      max_gross_exposure_pct: 5.0
      max_drawdown_pct: 1.0
      capital_allocation_pct: 10.0
    features:
      - feature_id: mid
        version: "1.0"
        description: mid price
        depends_on: []
        warm_up:
          min_events: 1
        computation: |
          def initial_state():
              return {}
          def update(quote, state, params):
              return float((quote.bid + quote.ask) / 2)
    signal: |
      def evaluate(features, params):
          return None
    """
)


def _portfolio_alpha_yaml(
    *,
    alpha_id: str = "pofi_xsect_v1",
    universe: tuple[str, ...] = ("AAPL", "GOOG", "MSFT"),
    hazard_exit_enabled: bool = False,
    decay_weighting: bool = False,
) -> str:
    lines: list[str] = [
        'schema_version: "1.1"',
        "layer: PORTFOLIO",
        f"alpha_id: {alpha_id}",
        'version: "1.0.0"',
        "description: cross-sectional test alpha",
        "hypothesis: cross-sectional momentum mean-reverts",
        "falsification_criteria:",
        "  - sharpe_post_cost_below_0.5",
        "horizon_seconds: 300",
        "universe:",
    ]
    lines.extend(f"  - {s}" for s in universe)
    lines.extend([
        "depends_on_signals:",
        "  - legacy_test_alpha",
        "factor_neutralization: true",
        "cost_arithmetic:",
        "  edge_estimate_bps: 10.0",
        "  half_spread_bps: 1.0",
        "  impact_bps: 0.5",
        "  fee_bps: 0.5",
        "  margin_ratio: 5.0",
        "trend_mechanism:",
        "  consumes:",
        "    - {family: KYLE_INFO, max_share_of_gross: 0.6}",
        "    - {family: INVENTORY, max_share_of_gross: 0.4}",
        "  max_share_of_gross: 0.6",
        "risk_budget:",
        "  max_position_per_symbol: 100",
        "  max_gross_exposure_pct: 5.0",
        "  max_drawdown_pct: 1.0",
        "  capital_allocation_pct: 10.0",
    ])
    if decay_weighting:
        lines.extend([
            "parameters:",
            "  decay_weighting_enabled:",
            "    type: bool",
            "    default: true",
        ])
    else:
        lines.append("parameters: {}")
    if hazard_exit_enabled:
        lines.extend([
            "hazard_exit:",
            "  enabled: true",
            "  hazard_score_threshold: 0.7",
            "  min_age_seconds: 60",
        ])
    return "\n".join(lines) + "\n"


def _write_alpha(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


def _make_config(
    tmp_path: Path,
    *,
    symbols: tuple[str, ...] = ("AAPL", "GOOG", "MSFT"),
    composition_max_universe_size: int = 50,
) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset(symbols),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        composition_max_universe_size=composition_max_universe_size,
    )


class TestCompositionWiring:

    def test_no_portfolio_alpha_no_composition(self, tmp_path: Path) -> None:
        """Inv-A: legacy fast-path preserved when no PORTFOLIO alpha exists."""
        _write_alpha(tmp_path, "legacy.alpha.yaml", _LEGACY_ALPHA_YAML)
        config = _make_config(tmp_path, symbols=("AAPL",))
        orchestrator, _ = build_platform(config)
        assert orchestrator._composition_engine is None
        assert orchestrator._cross_sectional_tracker is None
        assert orchestrator._composition_metrics_collector is None
        assert orchestrator._hazard_exit_controller is None

    def test_single_portfolio_alpha_wires_full_pipeline(
        self, tmp_path: Path
    ) -> None:
        """Single PORTFOLIO alpha activates the whole composition layer."""
        _write_alpha(tmp_path, "legacy.alpha.yaml", _LEGACY_ALPHA_YAML)
        _write_alpha(
            tmp_path,
            "pofi_xsect_v1.alpha.yaml",
            _portfolio_alpha_yaml(),
        )
        config = _make_config(tmp_path)
        orchestrator, _ = build_platform(config)
        assert isinstance(orchestrator._composition_engine, CompositionEngine)
        assert isinstance(
            orchestrator._cross_sectional_tracker, CrossSectionalTracker
        )
        assert isinstance(
            orchestrator._composition_metrics_collector,
            HorizonMetricsCollector,
        )
        # No alpha enabled hazard_exit → controller stays None.
        assert orchestrator._hazard_exit_controller is None

    def test_hazard_exit_alpha_constructs_controller(
        self, tmp_path: Path
    ) -> None:
        """Opt-in hazard_exit.enabled=true wires HazardExitController."""
        _write_alpha(tmp_path, "legacy.alpha.yaml", _LEGACY_ALPHA_YAML)
        _write_alpha(
            tmp_path,
            "pofi_xsect_hazard.alpha.yaml",
            _portfolio_alpha_yaml(
                alpha_id="pofi_xsect_hazard_v1",
                hazard_exit_enabled=True,
            ),
        )
        config = _make_config(tmp_path)
        orchestrator, _ = build_platform(config)
        controller = orchestrator._hazard_exit_controller
        assert isinstance(controller, HazardExitController)
        # The policy registered for the alpha mirrors the YAML block.
        assert "pofi_xsect_hazard_v1" in controller.policies
        policy = controller.policies["pofi_xsect_hazard_v1"]
        assert policy.hazard_score_threshold == pytest.approx(0.7)
        assert policy.min_age_seconds == 60

    def test_universe_scale_cap_fail_stop(self, tmp_path: Path) -> None:
        """Exceeding composition_max_universe_size raises UniverseScaleError."""
        _write_alpha(tmp_path, "legacy.alpha.yaml", _LEGACY_ALPHA_YAML)
        big_universe = tuple(f"SYM{i:03d}" for i in range(15))
        _write_alpha(
            tmp_path,
            "pofi_xsect_big.alpha.yaml",
            _portfolio_alpha_yaml(
                alpha_id="pofi_xsect_big_v1",
                universe=big_universe,
            ),
        )
        config = _make_config(
            tmp_path,
            symbols=big_universe,
            composition_max_universe_size=10,
        )
        with pytest.raises(UniverseScaleError, match="exceeds the v0.2 cap"):
            build_platform(config)

    def test_stale_factor_loadings_fail_stop(self, tmp_path: Path) -> None:
        """Bootstrap refuses to wire if factor loadings file is missing."""
        _write_alpha(tmp_path, "legacy.alpha.yaml", _LEGACY_ALPHA_YAML)
        _write_alpha(
            tmp_path,
            "pofi_xsect_v1.alpha.yaml",
            _portfolio_alpha_yaml(),
        )
        loadings_dir = tmp_path / "loadings"
        loadings_dir.mkdir()
        # Intentionally do NOT write loadings.json so the freshness
        # check raises StaleFactorLoadingsError.
        config = PlatformConfig(
            symbols=frozenset({"AAPL", "GOOG", "MSFT"}),
            mode=OperatingMode.BACKTEST,
            alpha_spec_dir=tmp_path,
            account_equity=100_000.0,
            factor_loadings_dir=loadings_dir,
        )
        with pytest.raises(StaleFactorLoadingsError):
            build_platform(config)
