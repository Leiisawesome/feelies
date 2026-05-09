"""Bootstrap-time wiring tests for the per-alpha risk-budget enforcement
flag (audit R2).

Covers:

1. ``test_default_does_not_wire_wrapper`` — default ``PlatformConfig``
   leaves ``enforce_per_alpha_risk_budget=False`` and the orchestrator
   receives the raw ``BasicRiskEngine``.  Preserves bit-identical
   replay against existing baselines (Inv-A).
2. ``test_flag_on_wires_alpha_budget_wrapper`` — flipping the flag
   wraps the engine in :class:`AlphaBudgetRiskWrapper` so per-alpha
   ``risk_budget`` blocks are enforced at runtime.
3. ``test_yaml_round_trip_preserves_flag`` — the flag survives the
   ``PlatformConfig.to_yaml`` / ``from_yaml`` round trip so
   operator-set ``platform.yaml: enforce_per_alpha_risk_budget: true``
   is not silently lost across config snapshots.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml  # pyright: ignore[reportMissingModuleSource]

from feelies.alpha.risk_wrapper import AlphaBudgetRiskWrapper
from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.risk.basic_risk import BasicRiskEngine
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
    alpha_id: r2_wiring_alpha
    version: "1.0.0"
    author: test
    description: minimal signal fixture for R2 wiring tests
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
    tmp_path: Path, *, enforce: bool = False,
) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        sensor_specs=_TEST_SENSOR_SPECS,
        enforce_trend_mechanism=False,
        enforce_per_alpha_risk_budget=enforce,
    )


def _write_alpha(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


class TestPerAlphaRiskBudgetWiring:
    def test_default_does_not_wire_wrapper(self, tmp_path: Path) -> None:
        _write_alpha(tmp_path, "r2.alpha.yaml", _SIGNAL_ALPHA_YAML)
        config = _make_config(tmp_path)
        orchestrator, _ = build_platform(config)

        assert isinstance(orchestrator._risk_engine, BasicRiskEngine)
        assert not isinstance(
            orchestrator._risk_engine, AlphaBudgetRiskWrapper,
        )

    def test_flag_on_wires_alpha_budget_wrapper(
        self, tmp_path: Path,
    ) -> None:
        _write_alpha(tmp_path, "r2.alpha.yaml", _SIGNAL_ALPHA_YAML)
        config = _make_config(tmp_path, enforce=True)
        orchestrator, _ = build_platform(config)

        assert isinstance(
            orchestrator._risk_engine, AlphaBudgetRiskWrapper,
        )

    def test_yaml_round_trip_preserves_flag(self, tmp_path: Path) -> None:
        config_in = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            account_equity=100_000.0,
            enforce_per_alpha_risk_budget=True,
        )
        yaml_path = tmp_path / "platform.yaml"
        yaml_path.write_text(yaml.safe_dump(config_in._to_dict()))
        config_out = PlatformConfig.from_yaml(yaml_path)
        assert config_out.enforce_per_alpha_risk_budget is True

    def test_yaml_round_trip_default_false(self, tmp_path: Path) -> None:
        config_in = PlatformConfig(
            symbols=frozenset({"AAPL"}),
            mode=OperatingMode.BACKTEST,
            account_equity=100_000.0,
        )
        yaml_path = tmp_path / "platform.yaml"
        yaml_path.write_text(yaml.safe_dump(config_in._to_dict()))
        config_out = PlatformConfig.from_yaml(yaml_path)
        assert config_out.enforce_per_alpha_risk_budget is False
