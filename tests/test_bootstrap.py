"""Unit tests for build_platform bootstrap."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from feelies.bootstrap import build_platform
from feelies.core.clock import SimulatedClock
from feelies.core.errors import ConfigurationError
from feelies.core.events import FeatureVector, NBBOQuote, Signal
from feelies.core.platform_config import OperatingMode, PlatformConfig
from feelies.kernel.orchestrator import Orchestrator
from feelies.core.config import ConfigSnapshot
from feelies.monitoring.in_memory import (
    InMemoryAlertManager,
    InMemoryKillSwitch,
    InMemoryMetricCollector,
)
from feelies.storage.memory_event_log import InMemoryEventLog

ALPHA_SPEC_YAML = """\
schema_version: "1.0"
alpha_id: test_alpha
version: "1.0.0"
author: test
description: test alpha
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


def _write_alpha_spec(directory: Path, filename: str = "test.alpha.yaml") -> Path:
    spec_file = directory / filename
    spec_file.write_text(ALPHA_SPEC_YAML, encoding="utf-8")
    return spec_file


def _make_config(tmp_path: Path, **overrides) -> PlatformConfig:
    defaults = dict(
        symbols=frozenset({"AAPL"}),
        mode=OperatingMode.BACKTEST,
        alpha_spec_dir=tmp_path,
        account_equity=100_000.0,
    )
    defaults.update(overrides)
    return PlatformConfig(**defaults)


class TestBuildPlatform:

    def test_returns_orchestrator_with_valid_config(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path)
        orchestrator, returned_config = build_platform(config)
        assert isinstance(orchestrator, Orchestrator)
        assert returned_config is config

    def test_regime_engine_wired_when_configured(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine="hmm_3state_fractional")
        orchestrator, _ = build_platform(config)
        assert orchestrator._regime_engine is not None

    def test_regime_engine_none_when_not_configured(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert orchestrator._regime_engine is None

    def test_backtest_mode_creates_simulated_clock(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert isinstance(orchestrator._clock, SimulatedClock)

    def test_invalid_config_raises_configuration_error(self) -> None:
        config = PlatformConfig(symbols=frozenset(), mode=OperatingMode.BACKTEST)
        with pytest.raises(ConfigurationError, match="symbols must be non-empty"):
            build_platform(config)

    def test_unknown_regime_engine_raises_configuration_error(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine="nonexistent_engine")
        with pytest.raises(ConfigurationError, match="Unknown regime engine 'nonexistent_engine'"):
            build_platform(config)

    def test_metric_collector_is_real(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert isinstance(orchestrator._metrics, InMemoryMetricCollector)

    def test_alert_manager_wired(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert isinstance(orchestrator._alert_manager, InMemoryAlertManager)

    def test_kill_switch_wired(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert isinstance(orchestrator._kill_switch, InMemoryKillSwitch)

    def test_kill_switch_starts_inactive(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        assert orchestrator._kill_switch.is_active is False

    def test_alert_manager_linked_to_kill_switch(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        am = orchestrator._alert_manager
        ks = orchestrator._kill_switch
        assert isinstance(am, InMemoryAlertManager)
        assert am._kill_switch is ks

    def test_config_snapshot_captured(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orchestrator, _ = build_platform(config)
        snap = orchestrator.config_snapshot  # type: ignore[attr-defined]
        assert isinstance(snap, ConfigSnapshot)
        assert snap.checksum
        assert snap.data["mode"] == "BACKTEST"

    def test_config_snapshot_checksum_is_deterministic(self, tmp_path: Path) -> None:
        _write_alpha_spec(tmp_path)
        config = _make_config(tmp_path, regime_engine=None)
        orch1, _ = build_platform(config)
        orch2, _ = build_platform(config)
        assert orch1.config_snapshot.checksum == orch2.config_snapshot.checksum  # type: ignore[attr-defined]


# ── YAML boot-path integration tests ────────────────────────────────

PLATFORM_YAML_TEMPLATE = """\
version: "0.1.0"
author: "test"
mode: BACKTEST
symbols:
  - AAPL
alpha_spec_dir: {alpha_dir}
alpha_specs: []
parameter_overrides: {{}}
regime_engine: null
account_equity: 100000.0
risk_max_position_per_symbol: 500
risk_max_gross_exposure_pct: 15.0
risk_max_drawdown_pct: 3.0
backtest_fill_latency_ns: 0
"""

MEAN_REV_ALPHA_YAML = """\
alpha_id: yaml_test_mean_rev
version: "1.0.0"
author: "test"
description: >
  Test mean reversion alpha for YAML boot-path validation.
hypothesis: >
  Mid-price deviation from EWMA reverts within ticks.
falsification_criteria:
  - "No edge on OOS data (p > 0.05)"
symbols: null
parameters:
  ewma_span:
    type: int
    default: 5
    range: [2, 100]
    description: "EWMA lookback"
  zscore_entry:
    type: float
    default: 1.0
    range: [0.1, 5.0]
    description: "Z-score entry threshold"
  edge_estimate_bps:
    type: float
    default: 2.5
    range: [0.5, 10.0]
    description: "Declared edge per signal"
risk_budget:
  max_position_per_symbol: 100
  max_gross_exposure_pct: 8.0
  max_drawdown_pct: 1.5
  capital_allocation_pct: 15.0
features:
  - feature_id: mid_price
    version: "1.0.0"
    description: "Mid-price"
    depends_on: []
    warm_up:
      min_events: 1
    computation: |
      def initial_state():
          return {}
      def update(quote, state, params):
          return float((quote.bid + quote.ask) / 2)
  - feature_id: mid_ewma
    version: "1.0.0"
    description: "EWMA of mid-price"
    depends_on: [mid_price]
    warm_up:
      min_events: "params['ewma_span']"
    computation: |
      def initial_state():
          return {"ewma": None}
      def update(quote, state, params):
          mid = float((quote.bid + quote.ask) / 2)
          alpha = 2.0 / (params["ewma_span"] + 1)
          if state["ewma"] is None:
              state["ewma"] = mid
          else:
              state["ewma"] = alpha * mid + (1.0 - alpha) * state["ewma"]
          return state["ewma"]
  - feature_id: mid_zscore
    version: "1.0.0"
    description: "Z-score of mid relative to EWMA"
    depends_on: [mid_price, mid_ewma]
    warm_up:
      min_events: "params['ewma_span']"
    computation: |
      def initial_state():
          return {"ewma": None, "ema_var": 0.0}
      def update(quote, state, params):
          mid = float((quote.bid + quote.ask) / 2)
          alpha = 2.0 / (params["ewma_span"] + 1)
          if state["ewma"] is None:
              state["ewma"] = mid
              return 0.0
          diff = mid - state["ewma"]
          state["ema_var"] = alpha * (diff * diff) + (1.0 - alpha) * state["ema_var"]
          state["ewma"] = alpha * mid + (1.0 - alpha) * state["ewma"]
          std = max(state["ema_var"] ** 0.5, 1e-12)
          return (mid - state["ewma"]) / std
signal: |
  def evaluate(features, params):
      if not features.warm or features.stale:
          return None
      zscore = features.values.get("mid_zscore", 0.0)
      threshold = params["zscore_entry"]
      if zscore < -threshold:
          direction = LONG
      elif zscore > threshold:
          direction = SHORT
      else:
          return None
      strength = min(abs(zscore) / 5.0, 1.0)
      return Signal(
          timestamp_ns=features.timestamp_ns,
          correlation_id=features.correlation_id,
          sequence=features.sequence,
          symbol=features.symbol,
          strategy_id=alpha_id,
          direction=direction,
          strength=strength,
          edge_estimate_bps=params["edge_estimate_bps"],
      )
"""


def _q(bid: float, ask: float, seq: int, ts_ns: int) -> NBBOQuote:
    return NBBOQuote(
        timestamp_ns=ts_ns,
        correlation_id=f"AAPL:{ts_ns}:{seq}",
        sequence=seq,
        symbol="AAPL",
        bid=Decimal(str(bid)),
        ask=Decimal(str(ask)),
        bid_size=100,
        ask_size=200,
        exchange_timestamp_ns=ts_ns - 100,
    )


class TestYAMLBootPath:
    """End-to-end: YAML config file -> build_platform -> boot -> run_backtest."""

    def _setup_yaml(self, tmp_path: Path) -> Path:
        alpha_dir = tmp_path / "alphas"
        alpha_dir.mkdir()
        (alpha_dir / "test_mean_rev.alpha.yaml").write_text(
            MEAN_REV_ALPHA_YAML, encoding="utf-8",
        )
        yaml_content = PLATFORM_YAML_TEMPLATE.format(alpha_dir=alpha_dir)
        yaml_path = tmp_path / "platform.yaml"
        yaml_path.write_text(yaml_content, encoding="utf-8")
        return yaml_path

    def test_yaml_path_produces_orchestrator(self, tmp_path: Path) -> None:
        yaml_path = self._setup_yaml(tmp_path)
        orchestrator, config = build_platform(str(yaml_path))
        assert isinstance(orchestrator, Orchestrator)
        assert config.symbols == frozenset({"AAPL"})
        assert config.account_equity == 100_000.0

    def test_alpha_discovered_and_registered(self, tmp_path: Path) -> None:
        yaml_path = self._setup_yaml(tmp_path)
        orchestrator, _ = build_platform(str(yaml_path))
        assert len(orchestrator._alpha_registry) == 1
        assert "yaml_test_mean_rev" in orchestrator._alpha_registry

    def test_config_snapshot_captures_all_fields(self, tmp_path: Path) -> None:
        yaml_path = self._setup_yaml(tmp_path)
        orchestrator, config = build_platform(str(yaml_path))
        snap = orchestrator.config_snapshot  # type: ignore[attr-defined]
        assert isinstance(snap, ConfigSnapshot)
        assert snap.data["mode"] == "BACKTEST"
        assert snap.data["account_equity"] == 100_000.0
        assert snap.data["backtest_fill_latency_ns"] == 0
        assert snap.data["risk_max_position_per_symbol"] == 500

    def test_yaml_boot_backtest_produces_feature_vectors(self, tmp_path: Path) -> None:
        yaml_path = self._setup_yaml(tmp_path)
        quotes = [_q(150, 152, i, i * 1_000_000_000) for i in range(1, 8)]
        event_log = InMemoryEventLog()
        event_log.append_batch(quotes)
        orchestrator, config = build_platform(str(yaml_path), event_log=event_log)

        recorder = []
        orchestrator._bus.subscribe(FeatureVector, lambda e: recorder.append(e))
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert len(recorder) >= len(quotes)
        fv = recorder[0]
        assert fv.symbol == "AAPL"
        assert "mid_price" in fv.values
        assert "mid_ewma" in fv.values
        assert "mid_zscore" in fv.values

    def test_yaml_boot_backtest_fires_signal_on_deviation(self, tmp_path: Path) -> None:
        yaml_path = self._setup_yaml(tmp_path)
        quotes = [
            _q(150, 152, 1, 1_000_000_000),
            _q(150, 152, 2, 2_000_000_000),
            _q(150, 152, 3, 3_000_000_000),
            _q(150, 152, 4, 4_000_000_000),
            _q(150, 152, 5, 5_000_000_000),
            _q(160, 162, 6, 6_000_000_000),
            _q(170, 172, 7, 7_000_000_000),
        ]
        event_log = InMemoryEventLog()
        event_log.append_batch(quotes)
        orchestrator, config = build_platform(str(yaml_path), event_log=event_log)

        signals: list[Signal] = []
        orchestrator._bus.subscribe(Signal, lambda e: signals.append(e))
        orchestrator.boot(config)
        orchestrator.run_backtest()

        assert len(signals) >= 1, (
            "Large price jump should trigger a z-score signal"
        )
        assert all(s.symbol == "AAPL" for s in signals)
        assert all(s.strategy_id == "yaml_test_mean_rev" for s in signals)

    def test_yaml_boot_deterministic_replay(self, tmp_path: Path) -> None:
        yaml_path = self._setup_yaml(tmp_path)
        quotes = [
            _q(150, 152, 1, 1_000_000_000),
            _q(150, 152, 2, 2_000_000_000),
            _q(150, 152, 3, 3_000_000_000),
            _q(150, 152, 4, 4_000_000_000),
            _q(150, 152, 5, 5_000_000_000),
            _q(160, 162, 6, 6_000_000_000),
            _q(170, 172, 7, 7_000_000_000),
        ]

        results = []
        for _ in range(3):
            event_log = InMemoryEventLog()
            event_log.append_batch(quotes)
            orch, cfg = build_platform(str(yaml_path), event_log=event_log)
            run_signals: list[Signal] = []
            orch._bus.subscribe(Signal, lambda e: run_signals.append(e))
            orch.boot(cfg)
            orch.run_backtest()
            pos = orch._positions.get("AAPL")
            results.append({
                "quantity": pos.quantity,
                "avg_price": pos.avg_entry_price,
                "num_signals": len(run_signals),
            })

        for i in range(1, len(results)):
            assert results[i]["quantity"] == results[0]["quantity"]
            assert results[i]["avg_price"] == results[0]["avg_price"]
            assert results[i]["num_signals"] == results[0]["num_signals"]
