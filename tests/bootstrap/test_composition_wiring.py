"""Bootstrap-time wiring tests for the Phase-4 composition layer.

Covers three sub-cases (plan §p4f_bootstrap_tests):

1. ``test_no_portfolio_alpha_no_composition`` --when no PORTFOLIO alpha
   is registered, none of the composition layer components are
   constructed.  Validates Inv-A: SIGNAL-only deployments do not pay
   for the composition pipeline.
2. ``test_single_portfolio_alpha_wires_full_pipeline`` --registering a
   single PORTFOLIO alpha brings up the entire composition pipeline:
   ``CompositionEngine``, ``CrossSectionalTracker``,
   ``HorizonMetricsCollector``, and (when hazard_exit is enabled) a
   ``HazardExitController``.
3. ``test_universe_scale_cap_fail_stop`` --exceeding
   ``composition_max_universe_size`` raises :class:`UniverseScaleError`
   at bootstrap rather than silently shipping a quietly-wrong pipeline
   (Inv-11 fail-safe).

Workstream D.2: the upstream-alpha fixture is now a ``layer: SIGNAL``
manifest (LEGACY_SIGNAL was retired from the loader's accepted layer
set).  PORTFOLIO alphas reference its ``alpha_id`` in
``depends_on_signals``.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from feelies.bootstrap import (
    StaleFactorLoadingsError,
    UniverseScaleError,
    build_platform,
)
from feelies.composition.engine import CompositionEngine
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.monitoring.horizon_metrics import HorizonMetricsCollector
from feelies.portfolio.cross_sectional_tracker import CrossSectionalTracker
from feelies.risk.hazard_exit import HazardExitController
from feelies.sensors.spec import SensorSpec
from tests._fixtures.sensor_specs import ALL_FINGERPRINT_SENSOR_SPECS


# ── Sensor catalog the upstream SIGNAL fixture depends on ──────────────
#
# Workstream D.2 swapped the LEGACY_SIGNAL upstream fixture (which had
# no sensor dependencies) for a horizon-anchored SIGNAL alpha.  SIGNAL
# alphas declare ``depends_on_sensors:`` and the bootstrap layer
# resolves those IDs against the configured ``sensor_specs`` tuple.
#
# Audit follow-up #6: ``ALL_FINGERPRINT_SENSOR_SPECS`` (shared fixture)
# is the union of every G16 family fingerprint sensor plus the two
# baseline sensors (``ofi_ewma`` / ``spread_z_30d``) the upstream
# fixture's gate references.  Using the union lets SIGNAL fixtures
# declare any ``trend_mechanism.family`` without G16's
# ``MissingFingerprintSensorError`` blocking the load.
_TEST_SENSOR_SPECS: tuple[SensorSpec, ...] = ALL_FINGERPRINT_SENSOR_SPECS


_UPSTREAM_SIGNAL_ALPHA_YAML = textwrap.dedent(
    """\
    schema_version: "1.1"
    layer: SIGNAL
    alpha_id: upstream_test_alpha
    version: "1.0.0"
    author: test
    description: upstream signal fixture for portfolio wiring tests
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
    horizon_seconds: 300
    depends_on_sensors:
      - ofi_ewma
      - spread_z_30d
    regime_gate:
      regime_engine: hmm_3state_fractional
      on_condition: "P(normal) > 0.7"
      off_condition: "P(normal) < 0.5"
    cost_arithmetic:
      edge_estimate_bps: 9.0
      half_spread_bps: 2.0
      impact_bps: 2.0
      fee_bps: 1.0
      margin_ratio: 1.8
    signal: |
      def evaluate(snapshot, regime, params):
          return None
    """
)


def _portfolio_alpha_yaml(
    *,
    alpha_id: str = "pro_xsect_v1",
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
        "  - upstream_test_alpha",
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


def _signal_alpha_yaml(
    *,
    alpha_id: str,
    horizon_seconds: int,
    family: str,
    expected_half_life_seconds: int,
    depends_on_sensors: tuple[str, ...] = ("ofi_ewma", "spread_z_30d"),
    l1_signature_sensors: tuple[str, ...] = (),
    hazard_block: dict[str, object] | None = None,
) -> str:
    """Build a self-contained SIGNAL alpha YAML for hazard-wiring tests.

    Lets each test pick (horizon, half_life, family, sensor deps) that
    satisfy G16 simultaneously, without coupling to the shared
    upstream fixture's horizon=300.
    """
    lines: list[str] = [
        'schema_version: "1.1"',
        "layer: SIGNAL",
        f"alpha_id: {alpha_id}",
        'version: "1.0.0"',
        "author: test",
        "description: hazard-wiring signal fixture",
        "hypothesis: test",
        "falsification_criteria:",
        "  - test criterion",
        "symbols:",
        "  - AAPL",
        "parameters: {}",
        "risk_budget:",
        "  max_position_per_symbol: 100",
        "  max_gross_exposure_pct: 5.0",
        "  max_drawdown_pct: 1.0",
        "  capital_allocation_pct: 10.0",
        f"horizon_seconds: {horizon_seconds}",
        "depends_on_sensors:",
    ]
    lines.extend(f"  - {s}" for s in depends_on_sensors)
    lines.extend([
        "regime_gate:",
        "  regime_engine: hmm_3state_fractional",
        '  on_condition: "P(normal) > 0.7"',
        '  off_condition: "P(normal) < 0.5"',
        "cost_arithmetic:",
        "  edge_estimate_bps: 9.0",
        "  half_spread_bps: 2.0",
        "  impact_bps: 2.0",
        "  fee_bps: 1.0",
        "  margin_ratio: 1.8",
        "trend_mechanism:",
        f"  family: {family}",
        f"  expected_half_life_seconds: {expected_half_life_seconds}",
        f"  expected_holding_period_seconds: {expected_half_life_seconds * 2}",
    ])
    if l1_signature_sensors:
        lines.append("  l1_signature_sensors:")
        lines.extend(f"    - {s}" for s in l1_signature_sensors)
    # G16 rule 6: mechanism alphas must declare a non-empty
    # ``failure_signature`` block (Inv-2 / mechanism falsifiers).  The
    # specific content doesn't matter for wiring tests — it just has
    # to be a non-empty list.
    lines.extend([
        "  failure_signature:",
        '    - "spread_z_30d > 2.5"',
    ])
    if hazard_block is not None:
        lines.append("hazard_exit:")
        for k, v in hazard_block.items():
            if isinstance(v, bool):
                lines.append(f"  {k}: {'true' if v else 'false'}")
            else:
                lines.append(f"  {k}: {v}")
    lines.extend([
        "signal: |",
        "  def evaluate(snapshot, regime, params):",
        "      return None",
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
        sensor_specs=_TEST_SENSOR_SPECS,
        # Workstream E flipped the platform default to ``true``.  These
        # bootstrap-wiring tests are orthogonal to G16 (composition
        # wiring, hazard-exit construction, scale-cap fail-stop) and
        # the upstream SIGNAL fixture only registers ``ofi_ewma`` and
        # ``spread_z_30d``, neither of which is a primary fingerprint
        # sensor for any mechanism family.  Pinning the opt-out here
        # preserves the v0.2-style fixture without dragging the
        # mechanism taxonomy into a wiring test (parity with the
        # ``platform.yaml`` opt-out documented for ``sig_benign_midcap_v1``).
        enforce_trend_mechanism=False,
    )


class TestCompositionWiring:

    def test_no_portfolio_alpha_no_composition(self, tmp_path: Path) -> None:
        """Inv-A: legacy fast-path preserved when no PORTFOLIO alpha exists."""
        _write_alpha(tmp_path, "upstream.alpha.yaml", _UPSTREAM_SIGNAL_ALPHA_YAML)
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
        _write_alpha(tmp_path, "upstream.alpha.yaml", _UPSTREAM_SIGNAL_ALPHA_YAML)
        _write_alpha(
            tmp_path,
            "pro_xsect_v1.alpha.yaml",
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
        # No alpha enabled hazard_exit ->controller stays None.
        assert orchestrator._hazard_exit_controller is None

    def test_hazard_exit_alpha_constructs_controller(
        self, tmp_path: Path
    ) -> None:
        """Opt-in hazard_exit.enabled=true wires HazardExitController."""
        _write_alpha(tmp_path, "upstream.alpha.yaml", _UPSTREAM_SIGNAL_ALPHA_YAML)
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

    def test_signal_layer_hazard_exit_opt_in_wires_controller(
        self, tmp_path: Path
    ) -> None:
        """Audit P0 H-1: SIGNAL-layer ``hazard_exit.enabled: true`` must
        actually wire a controller.  Before the fix,
        ``_create_composition_layer`` scanned only PORTFOLIO modules
        and a SIGNAL opt-in produced spikes with no consumer.

        Re-introduced after follow-up #6 added the shared fingerprint-
        sensor catalog, which lets the SIGNAL fixture declare a
        ``trend_mechanism:`` block without G16 blocking the load.
        """
        # KYLE_INFO has half-life range [60, 1800]; horizon 300 / half 150
        # = ratio 2.0, within G16's [0.5, 4.0].  Its fingerprint sensors
        # (kyle_lambda_60s, micro_price) ship in ALL_FINGERPRINT_SENSOR_SPECS
        # and don't need event_calendar_path.
        signal_with_hazard = _signal_alpha_yaml(
            alpha_id="haz_test_alpha",
            horizon_seconds=300,
            family="KYLE_INFO",
            expected_half_life_seconds=150,
            depends_on_sensors=("ofi_ewma", "spread_z_30d",
                                "kyle_lambda_60s", "micro_price"),
            l1_signature_sensors=("kyle_lambda_60s", "micro_price"),
            hazard_block={
                "enabled": True,
                "hazard_score_threshold": 0.4,
                "min_age_seconds": 5,
            },
        )
        _write_alpha(tmp_path, "haz_signal.alpha.yaml", signal_with_hazard)
        config = _make_config(tmp_path, symbols=("AAPL",))
        orchestrator, _ = build_platform(config)
        controller = orchestrator._hazard_exit_controller
        assert isinstance(controller, HazardExitController), (
            "SIGNAL-layer hazard_exit.enabled must wire HazardExitController"
        )
        assert "haz_test_alpha" in controller.policies
        policy = controller.policies["haz_test_alpha"]
        assert policy.hazard_score_threshold == pytest.approx(0.4)
        assert policy.min_age_seconds == 5
        # HM-1 default: 2 × expected_half_life_seconds (150) = 300.
        assert policy.hard_exit_age_seconds == 300
        # SIGNAL alphas lack a per-alpha universe, so the policy falls
        # back to the platform symbols.
        assert policy.universe == ("AAPL",)

    def test_signal_hazard_exit_uses_explicit_hard_exit_age_when_provided(
        self, tmp_path: Path
    ) -> None:
        """HM-1 default applies only when the YAML omits the field; an
        explicit value must be honored verbatim."""
        signal_with_hazard = _signal_alpha_yaml(
            alpha_id="haz_explicit_alpha",
            horizon_seconds=300,
            family="KYLE_INFO",
            expected_half_life_seconds=150,
            depends_on_sensors=("ofi_ewma", "spread_z_30d",
                                "kyle_lambda_60s", "micro_price"),
            l1_signature_sensors=("kyle_lambda_60s", "micro_price"),
            hazard_block={
                "enabled": True,
                "hard_exit_age_seconds": 1234,
            },
        )
        _write_alpha(tmp_path, "haz_explicit.alpha.yaml", signal_with_hazard)
        config = _make_config(tmp_path, symbols=("AAPL",))
        orchestrator, _ = build_platform(config)
        controller = orchestrator._hazard_exit_controller
        assert controller is not None
        assert controller.policies["haz_explicit_alpha"].hard_exit_age_seconds == 1234

    def test_universe_scale_cap_fail_stop(self, tmp_path: Path) -> None:
        """Exceeding composition_max_universe_size raises UniverseScaleError."""
        _write_alpha(tmp_path, "upstream.alpha.yaml", _UPSTREAM_SIGNAL_ALPHA_YAML)
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
        _write_alpha(tmp_path, "upstream.alpha.yaml", _UPSTREAM_SIGNAL_ALPHA_YAML)
        _write_alpha(
            tmp_path,
            "pro_xsect_v1.alpha.yaml",
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
            sensor_specs=_TEST_SENSOR_SPECS,
            # See ``_make_config`` above for the rationale.
            enforce_trend_mechanism=False,
        )
        with pytest.raises(StaleFactorLoadingsError):
            build_platform(config)
