"""Workstream F-5: bootstrap-time wiring of platform-level gate thresholds.

Pins how :func:`feelies.bootstrap.build_platform` plumbs
``PlatformConfig.gate_thresholds_overrides`` through to
:class:`feelies.alpha.registry.AlphaRegistry` so that every
:class:`AlphaLifecycle` constructed by the registry is born with the
correctly-layered acceptance thresholds.

Layering precedence (lowest → highest):

  1. ``GateThresholds()`` skill-pinned defaults.
  2. ``platform.yaml :: gate_thresholds`` (this file's focus).
  3. ``<alpha>.alpha.yaml :: promotion.gate_thresholds`` (covered by
     ``test_loader_promotion_block.py`` +
     ``test_registry_per_alpha_thresholds.py``).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from feelies.alpha.promotion_evidence import GateThresholds
from feelies.bootstrap import _build_platform_gate_thresholds, build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.sensors.impl.ofi_ewma import OFIEwmaSensor
from feelies.sensors.impl.spread_z_30d import SpreadZScoreSensor
from feelies.sensors.spec import SensorSpec


_TEST_SENSOR_SPECS: tuple[SensorSpec, ...] = (
    SensorSpec(
        sensor_id="ofi_ewma",
        sensor_version="1.0.0",
        cls=OFIEwmaSensor,
        subscribes_to=(NBBOQuote,),
    ),
    SensorSpec(
        sensor_id="spread_z_30d",
        sensor_version="1.0.0",
        cls=SpreadZScoreSensor,
        subscribes_to=(NBBOQuote,),
    ),
)


_SIGNAL_ALPHA_YAML = textwrap.dedent(
    """\
    schema_version: "1.1"
    layer: SIGNAL
    alpha_id: f5_wiring_alpha
    version: "1.0.0"
    author: test
    description: minimal signal fixture for F-5 wiring tests
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


def _make_config(
    tmp_path: Path,
    *,
    gate_thresholds_overrides: dict[str, object] | None = None,
) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        sensor_specs=_TEST_SENSOR_SPECS,
        gate_thresholds_overrides=(
            dict(gate_thresholds_overrides)
            if gate_thresholds_overrides is not None
            else {}
        ),
    )


def _write_alpha(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# _build_platform_gate_thresholds helper
# ─────────────────────────────────────────────────────────────────────


class TestBuildPlatformGateThresholds:
    def test_empty_config_returns_none(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
        )
        assert _build_platform_gate_thresholds(cfg) is None

    def test_overrides_layered_on_skill_defaults(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
            gate_thresholds_overrides={"dsr_min": 1.5},
        )
        thresholds = _build_platform_gate_thresholds(cfg)
        assert thresholds is not None
        assert thresholds.dsr_min == 1.5
        assert (
            thresholds.paper_min_trading_days
            == GateThresholds().paper_min_trading_days
        )

    def test_returns_fresh_instance_each_call(self) -> None:
        cfg = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            alpha_specs=[Path("dummy.alpha.yaml")],
            gate_thresholds_overrides={"dsr_min": 1.5},
        )
        a = _build_platform_gate_thresholds(cfg)
        b = _build_platform_gate_thresholds(cfg)
        assert a == b
        assert a is not b


# ─────────────────────────────────────────────────────────────────────
# build_platform → AlphaRegistry wiring
# ─────────────────────────────────────────────────────────────────────


class TestBuildPlatformGateThresholdsWiring:
    def test_default_config_leaves_registry_thresholds_none(
        self, tmp_path: Path
    ) -> None:
        _write_alpha(tmp_path, "f5.alpha.yaml", _SIGNAL_ALPHA_YAML)
        config = _make_config(tmp_path)
        orchestrator, _ = build_platform(config)

        registry = orchestrator._alpha_registry
        assert registry is not None
        assert registry._gate_thresholds is None  # noqa: SLF001

    def test_platform_overrides_propagate_to_registry(
        self, tmp_path: Path
    ) -> None:
        _write_alpha(tmp_path, "f5.alpha.yaml", _SIGNAL_ALPHA_YAML)
        config = _make_config(
            tmp_path,
            gate_thresholds_overrides={
                "dsr_min": 1.5,
                "paper_min_trading_days": 7,
            },
        )

        orchestrator, _ = build_platform(config)

        registry = orchestrator._alpha_registry
        assert registry is not None
        thresholds = registry._gate_thresholds  # noqa: SLF001
        assert thresholds is not None
        assert thresholds.dsr_min == 1.5
        assert thresholds.paper_min_trading_days == 7
        assert (
            thresholds.cpcv_min_folds == GateThresholds().cpcv_min_folds
        )
