"""Audit P0 (2026-06-18): lock the default-on TRIM wiring without a dataset.

The kernel-level TRIM behaviour is exercised in
``tests/kernel/test_orchestrator.py``, but those tests pass
``position_manager_drive=True`` / ``position_manager_enable_trim=True``
*explicitly* — so they would still pass if the ``PlatformConfig`` defaults
silently regressed to ``False``.  The functional APP baseline
(``tests/acceptance/test_backtest_app_baseline.py``) does lock the trim-on
trade path, but it is data-gated and skips on cache miss, so it never runs
in CI.

This module closes that precise gap: it pins (a) the ``PlatformConfig``
defaults and (b) that :func:`feelies.bootstrap.build_platform` plumbs those
defaults into a TRIM-capable, driving ``TargetPositionManager`` on the
constructed orchestrator — entirely data-free.
"""

from __future__ import annotations

import textwrap
from dataclasses import replace
from pathlib import Path

from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.execution.position_manager import TargetPositionManager
from feelies.risk.edge_weighted_sizer import EdgeWeightedSizer
from feelies.risk.position_sizer import BudgetBasedSizer
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec

_TEST_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.1.0",
        cls=OFIEwmaSensor,
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.1.0",
        cls=SpreadZScoreSensor,
        subscribes_to=(NBBOQuote,),
    ),
)

_SIGNAL_ALPHA_YAML = textwrap.dedent(
    """\
    schema_version: "1.1"
    layer: SIGNAL
    alpha_id: pm_wiring_alpha
    version: "1.0.0"
    author: test
    description: minimal signal fixture for position-manager wiring tests
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


def _make_config(tmp_path: Path) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        sensor_specs=_TEST_SENSOR_SPECS,
        enforce_trend_mechanism=False,
    )


class TestPositionManagerConfigDefaults:
    """The audited default-ON contract is a deliberate, pinned choice."""

    def test_drive_and_trim_default_on(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}))
        assert cfg.position_manager_drive is True
        assert cfg.position_manager_enable_trim is True
        assert cfg.position_manager_trim_edge_gate_multiplier == 1.0

    def test_trim_execution_style_defaults_to_passive(self) -> None:
        # Audit P2.1 (2026-06-18): urgency_exec ON → discretionary trims work
        # PASSIVE (post a limit, save the spread) with a guaranteed MARKET
        # fallback if unfilled.  Pinned so any future flip back to MARKET-by-
        # default is a conscious, re-baselined change rather than a silent
        # regression.
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}))
        assert cfg.position_manager_urgency_exec is True


class TestSizerTiltConfigDefaults:
    """Audit P2.3 (2026-06-18): the EDGE tilt is available **opt-in**.

    It is fully wired but left OFF by default, so the live size stays
    single-factor (byte-identical to the baseline) unless an operator
    consciously promotes it per deployment.  Pinned so any future flip to
    default-on is a deliberate, re-baselined change rather than a silent
    regression of the platform-wide trade path.
    """

    def test_edge_tilt_off_by_default(self) -> None:
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}))
        assert cfg.sizer_tilt_drive is False
        assert cfg.sizer_edge_weighting_enabled is False

    def test_all_tilt_factors_off_by_default(self) -> None:
        # No factor drives the live size by default; vol has no wired
        # provider and inventory tapering is a separate decision.
        cfg = PlatformConfig(symbols=frozenset({"AAPL"}))
        assert cfg.sizer_vol_targeting_enabled is False
        assert cfg.sizer_inventory_penalty_enabled is False


class TestBuildPlatformPositionManagerWiring:
    def test_defaults_drive_a_trim_capable_planner(self, tmp_path: Path) -> None:
        (tmp_path / "pm.alpha.yaml").write_text(_SIGNAL_ALPHA_YAML, encoding="utf-8")
        orchestrator, _ = build_platform(_make_config(tmp_path))

        # The planner is the cost-aware TargetPositionManager (not the
        # legacy translator), and it is wired to drive the live decision
        # with TRIM enabled — i.e. the audited default-on trade path.
        assert isinstance(orchestrator._position_manager, TargetPositionManager)  # noqa: SLF001
        assert orchestrator._position_manager_drive is True  # noqa: SLF001
        assert orchestrator._position_manager_enable_trim is True  # noqa: SLF001
        assert orchestrator._position_manager_trim_edge_gate_multiplier == 1.0  # noqa: SLF001

    def test_defaults_keep_the_base_sizer_live(self, tmp_path: Path) -> None:
        # Audit P2.3: with sizer_tilt_drive OFF (default), bootstrap leaves the
        # bare base sizer driving the live decision — the tilt is shadow-only.
        (tmp_path / "pm.alpha.yaml").write_text(_SIGNAL_ALPHA_YAML, encoding="utf-8")
        orchestrator, _ = build_platform(_make_config(tmp_path))

        sizer = orchestrator._position_sizer  # noqa: SLF001
        assert isinstance(sizer, BudgetBasedSizer)
        assert not isinstance(sizer, EdgeWeightedSizer)

    def test_opt_in_routes_through_the_edge_weighted_sizer(self, tmp_path: Path) -> None:
        # Audit P2.3: an operator promoting the edge tilt per deployment
        # (sizer_tilt_drive + sizer_edge_weighting_enabled) routes the live
        # decision through the EdgeWeightedSizer with the edge factor on.
        (tmp_path / "pm.alpha.yaml").write_text(_SIGNAL_ALPHA_YAML, encoding="utf-8")
        cfg = replace(
            _make_config(tmp_path),
            sizer_tilt_drive=True,
            sizer_edge_weighting_enabled=True,
        )
        orchestrator, _ = build_platform(cfg)

        sizer = orchestrator._position_sizer  # noqa: SLF001
        assert isinstance(sizer, EdgeWeightedSizer)
        assert sizer.config.edge_enabled is True
