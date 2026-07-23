"""Bootstrap wiring tests for the promotion evidence ledger.

The ledger is optional, configured paths are exposed by the registry, and
backtests never write lifecycle transitions.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from feelies.alpha.promotion_ledger import PromotionLedger
from feelies.bootstrap import build_platform
from feelies.core.events import NBBOQuote
from feelies.core.platform_config import OperatingMode, PlatformConfig
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
    alpha_id: f1_wiring_alpha
    version: "1.0.0"
    author: test
    description: minimal signal fixture for F-1 wiring tests
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
    promotion_ledger_path: Path | None = None,
) -> PlatformConfig:
    return PlatformConfig(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
        sensor_specs=_TEST_SENSOR_SPECS,
        promotion_ledger_path=promotion_ledger_path,
        # Keep ledger wiring independent of mechanism validation.
        enforce_trend_mechanism=False,
    )


def _write_alpha(directory: Path, name: str, body: str) -> None:
    (directory / name).write_text(body, encoding="utf-8")


class TestPromotionLedgerWiring:
    def test_no_promotion_ledger_path_disables_ledger(self, tmp_path: Path) -> None:
        _write_alpha(tmp_path, "f1.alpha.yaml", _SIGNAL_ALPHA_YAML)
        config = _make_config(tmp_path)
        orchestrator, _ = build_platform(config)

        assert orchestrator._alpha_registry is not None
        assert orchestrator._alpha_registry.promotion_ledger is None

    def test_promotion_ledger_path_constructs_and_wires_ledger(self, tmp_path: Path) -> None:
        _write_alpha(tmp_path, "f1.alpha.yaml", _SIGNAL_ALPHA_YAML)
        ledger_path = tmp_path / "audit" / "promotion.jsonl"
        config = _make_config(tmp_path, promotion_ledger_path=ledger_path)

        orchestrator, _ = build_platform(config)

        assert orchestrator._alpha_registry is not None
        ledger = orchestrator._alpha_registry.promotion_ledger
        assert isinstance(ledger, PromotionLedger)
        assert ledger.path == ledger_path
        # File is created at construction time (parent dir made if needed).
        assert ledger_path.exists()
        assert ledger_path.parent.is_dir()

    def test_backtest_mode_does_not_emit_transitions(self, tmp_path: Path) -> None:
        # BACKTEST has no lifecycle clock, so replay must not write the ledger.
        _write_alpha(tmp_path, "f1.alpha.yaml", _SIGNAL_ALPHA_YAML)
        ledger_path = tmp_path / "promotion.jsonl"
        config = _make_config(tmp_path, promotion_ledger_path=ledger_path)

        orchestrator, _ = build_platform(config)
        assert orchestrator._alpha_registry is not None
        ledger = orchestrator._alpha_registry.promotion_ledger
        assert ledger is not None

        # No transitions => no entries on disk after a fresh build.
        assert list(ledger.entries()) == []
